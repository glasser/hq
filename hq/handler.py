#!/usr/bin/env python2.5

import base64
import logging
import os

from google.appengine.api import memcache
from google.appengine.ext import webapp

from hq import my_template
from hq import model

INSTANCE_NAME = 'Battlestar Electronica'

port = os.environ['SERVER_PORT']
if port and port != '80':
  HOST_NAME = '%s:%s' % (os.environ['SERVER_NAME'], port)
else:
  HOST_NAME = os.environ['SERVER_NAME']

# Inspired by mox's MoxMetaTestBase.
class RequestHandlerMetaClass(type):
  """Metaclass to do auth checks at the beginning of get and post methods."""

  def __init__(cls, name, bases, d):
    type.__init__(cls, name, bases, d)
    # Also get all of the attributes from base classes to account for a case
    # when the handler class is not the immediate child of RequestHandler.
    for base in bases:
      for attr_name in dir(base):
        if attr_name not in d:
          d[attr_name] = getattr(base, attr_name)

      for func_name, func in d.items():
        if callable(func) and (func_name == 'get' or func_name == 'post'):
          setattr(cls, func_name, RequestHandlerMetaClass.wrap_with_auth(
              cls, func))

  @staticmethod
  def wrap_with_auth(cls, func):
    def new_method(self, *args, **kwargs):
      if self.check_basic_auth():
        func(self, *args, **kwargs)
    new_method.__name__ = func.__name__
    new_method.__doc__ = func.__doc__
    new_method.__module__ = func.__module__
    return new_method


class RequestHandler(webapp.RequestHandler):

  __metaclass__ = RequestHandlerMetaClass

  COOKIE_NAME = 'hq_username'
  NOBODY = 'nobody'

  BASIC_AUTH_USER = 'nugget'
  BASIC_AUTH_PASSWORD = 'hotdog'

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

  def check_basic_auth(self):
    auth_header = self.request.headers.get('Authorization')
    if auth_header:
      try:
        (scheme, base64_raw) = auth_header.split(' ')
        if scheme != 'Basic':
          raise ValueError, 'scheme is not Basic!'
        (username, password) = base64.b64decode(base64_raw).split(':')
      except (ValueError, TypeError), err:
        username = password = ''
        logging.warn(type(err))
      finally:
        if (username == self.BASIC_AUTH_USER and
            password == self.BASIC_AUTH_PASSWORD):
          return True
        else:
          self.error(401)
          self.response.headers['WWW-Authenticate'] = 'Basic realm="CIC"'
          return False
    else:
      self.error(401)
      self.response.headers['WWW-Authenticate'] = 'Basic realm="CIC"'
      return False

  def render_template(self, template_name, params, **kwds):
    params['usernames'] = model.Username.all()
    params['current_user'] = self.username
    params['unsolved_puzzle_count'] = model.Puzzle.unsolved_count()
    self.response.out.write(self.render_template_to_string(template_name,
                                                           params, **kwds))

  @classmethod
  def render_template_to_string(cls, template_name, params,
                                include_custom_css=True,
                                include_rendered_banners=True,
                                include_rendered_newsfeeds=True):
    path = os.path.join(os.path.dirname(__file__), '..', 'templates',
                        '%s.html' % template_name)
    params['instance_name'] = INSTANCE_NAME
    if include_custom_css:
      params['custom_css'] = model.Css.get_custom_css()
    if include_rendered_banners:
      params['rendered_banners'] = cls.render_banners()
    if include_rendered_newsfeeds:
      params['rendered_newsfeeds'] = cls.render_newsfeeds()
    params['header_links'] = model.HeaderLink.all().order('created')
    return my_template.render(path, params)

  @classmethod
  def render_banners(cls):
    rendered = memcache.get(model.Banner.MEMCACHE_KEY)
    if rendered is not None:
      return rendered
    banners = model.Banner.all().order('-created')
    rendered = cls.render_template_to_string('banners', {
      'banners': banners,
    }, include_rendered_banners=False, include_rendered_newsfeeds=False)
    memcache.set(model.Banner.MEMCACHE_KEY, rendered)
    return rendered

  @classmethod
  def render_newsfeeds(cls):
    rendered = memcache.get(model.Newsfeed.MEMCACHE_KEY)
    if rendered is not None:
      return rendered
    newsfeeds = model.Newsfeed.all().order('-created')
    rendered = cls.render_template_to_string('newsfeeds', {
      'newsfeeds': newsfeeds.fetch(15),
    }, include_rendered_banners=False, include_rendered_newsfeeds=False)
    memcache.set(model.Newsfeed.MEMCACHE_KEY, rendered)
    return rendered
