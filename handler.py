#!/usr/bin/env python2.5

import os

from google.appengine.ext import webapp

import my_template
import model

INSTANCE_NAME = 'Optimus Funk'
APPS_DOMAIN = 'optimusfunk.org'  # For spreadsheets, etc

port = os.environ['SERVER_PORT']
if port and port != '80':
  HOST_NAME = '%s:%s' % (os.environ['SERVER_NAME'], port)
else:
  HOST_NAME = os.environ['SERVER_NAME']

class RequestHandler(webapp.RequestHandler):
  COOKIE_NAME = 'hq_username'
  NOBODY = 'nobody'

  def initialize(self, *args, **kwds):
    super(RequestHandler, self).initialize(*args, **kwds)

    # Deal with username cookie.
    self.username = self.request.cookies.get(self.COOKIE_NAME, self.NOBODY)

  def set_username(self, username):
    self.username = username
    self.response.headers.add_header(
        'Set-Cookie',
        '%s=%s; path=/; expires=Fri, 31-Dec-2020 23:59:59 GMT' \
          % (self.COOKIE_NAME, username.encode()))

  def render_template(self, template_name, params, **kwds):
    params['usernames'] = model.Username.all()
    params['current_user'] = self.username
    self.response.out.write(self.render_template_to_string(template_name,
                                                           params, **kwds))

  @classmethod
  def render_template_to_string(cls, template_name, params,
                                include_custom_css=True,
                                include_rendered_banners=True,
                                include_rendered_newsfeeds=True):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['instance_name'] = INSTANCE_NAME
    if include_custom_css:
      params['custom_css'] = model.Css.get_custom_css()
    if include_rendered_banners:
      params['rendered_banners'] = model.Banner.get_rendered()
    if include_rendered_newsfeeds:
      params['rendered_newsfeeds'] = model.Newsfeed.get_rendered()
    return my_template.render(path, params)
