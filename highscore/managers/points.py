# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

import time
import sqlalchemy as sa
from twisted.internet import defer
from twisted.application import service

class PointsManager(service.MultiService):

    def __init__(self, highscore, config):
        service.MultiService.__init__(self)
        self.setName('highscore.points')
        self.highscore = highscore
        self.config = config

    @defer.inlineCallbacks
    def addPoints(self, userid, points, comments):
        def thd(conn):
            tbl = self.highscore.db.model.points
            r = conn.execute(tbl.insert(), dict(
                userid=userid,
                when=time.time(),
                points=points,
                comments=comments))
            pointsid = r.inserted_primary_key[0]
            return pointsid
        pointsid = yield self.highscore.db.pool.do(thd)

        display_name = yield self.highscore.users.getDisplayName(userid)
        self.highscore.mq.produce('points.add.%d' % userid,
                dict(pointsid=pointsid, userid=userid,
                        display_name=display_name, points=points,
                        comments=comments))

    def getHighscores(self):
        def thd(conn):
            pointsTbl = self.highscore.db.model.points
            usersTbl = self.highscore.db.model.users

            now = time.time()
            HALFLIFE = 3600*24*30 # points lose half their value after a month
            MAX_AGE = HALFLIFE * 4 # points disappear after losing 15/16th of their value

            # we want to use exponential decay of points, and sqlite doesn't
            # support this, so we just download the whole list of (recent)
            # points, sorted by userid, and futz with it in memory from there
            r = conn.execute(sa.select([ usersTbl.c.display_name,
                    pointsTbl.c.userid, pointsTbl.c.when, pointsTbl.c.points ],
                (usersTbl.c.id == pointsTbl.c.userid) &
                (pointsTbl.c.when > now - MAX_AGE)))

            user_points = {}
            user_names = {}
            for row in r:
                if row.userid not in user_names:
                    user_names[row.userid] = row.display_name
                    user_points[row.userid] = 0
                mult = 0.5 ** ((now - row.when) / HALFLIFE)
                user_points[row.userid] += mult * row.points

            # sort highest scores
            by_score = sorted(
                    [ (p, u) for (u, p) in user_points.iteritems() ],
                    reverse=True)
            by_score = [ dict(points=p, userid=u, display_name=user_names[u])
                         for (p, u) in by_score ]

            return by_score
        return self.highscore.db.pool.do(thd)
