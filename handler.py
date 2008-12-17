#!/usr/bin/env python2.5

import os

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

INSTANCE_NAME = 'Primal Funk'

class RequestHandler(webapp.RequestHandler):
  def render_template(self, template_name, params):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['current_user'] = users.get_current_user()
    params['log_out_url'] = users.create_logout_url('/')
    params['instance_name'] = INSTANCE_NAME
    self.response.out.write(template.render(path, params))
