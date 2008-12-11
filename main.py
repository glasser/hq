#!/usr/bin/env python2.5

import os
import wsgiref.handlers

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template


class TagFamily(db.Model):
  name = db.StringProperty()
  options = db.StringListProperty()


class FamilyHandler(webapp.RequestHandler):

  def render_template(self, template_name, params):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['current_user'] = users.get_current_user()
    self.response.out.write(template.render(path, params))

  def get(self):
    self.render_template("families", {})


def main():
  application = webapp.WSGIApplication([('/family', FamilyHandler)],
                                       debug=True)
  wsgiref.handlers.CGIHandler().run(application)


if __name__ == '__main__':
  main()
