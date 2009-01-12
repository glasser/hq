#!/usr/bin/env python2.5

import os

from google.appengine.api import users
from google.appengine.ext import webapp

import my_template
import model

INSTANCE_NAME = 'Optimus Funk'

class RequestHandler(webapp.RequestHandler):

  def render_template(self, *args, **kwds):
    self.response.out.write(self.render_template_to_string(*args, **kwds))

  @classmethod
  def render_template_to_string(cls, template_name, params,
                                include_custom_css=True,
                                include_rendered_banners=True):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['current_user'] = users.get_current_user()
    params['log_out_url'] = users.create_logout_url('/')
    params['instance_name'] = INSTANCE_NAME
    if include_custom_css:
      params['custom_css'] = model.Css.get_custom_css()
    if include_rendered_banners:
      params['rendered_banners'] = model.Banner.get_rendered()
    return my_template.render(path, params)
