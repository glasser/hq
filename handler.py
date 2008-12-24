#!/usr/bin/env python2.5

import os

from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

import model

INSTANCE_NAME = 'Primal Funk'

class RequestHandler(webapp.RequestHandler):
  RENDERED_BANNERS_KEY = 'rendered:banners'

  def render_template(self, template_name, params, include_custom_css=True):
    if include_custom_css:
      params['custom_css'] = model.Css.get_custom_css()
    self.response.out.write(self.render_template_to_string(template_name,
                                                           params))

  def render_template_to_string(self, template_name, params):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['current_user'] = users.get_current_user()
    params['log_out_url'] = users.create_logout_url('/')
    params['instance_name'] = INSTANCE_NAME
    if template_name != 'banners':
      params['rendered_banners'] = self.render_banners()
    return template.render(path, params)

  def render_banners(self):
    rendered = memcache.get(self.RENDERED_BANNERS_KEY)
    if rendered is not None:
      return rendered
    banners = model.Banner.all()
    rendered = self.render_template_to_string('banners', {
      "banners": banners,
    })
    memcache.set(self.RENDERED_BANNERS_KEY, rendered)
    return rendered
