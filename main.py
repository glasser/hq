#!/usr/bin/env python2.5

import os
import re
import wsgiref.handlers

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template


INSTANCE_NAME = 'Primal Funk'


TAG_PIECE = '[a-zA-Z0-9-]+'
VALID_TAG_PIECE_RE = re.compile('^%s$' % TAG_PIECE)
def IsValidTagPiece(name):
  """Checks to see if NAME is a valid name for a tag family, a family option,
  or a non-family tag."""
  return VALID_TAG_PIECE_RE.match(name)


def IsValidTagName(name):
  """Checks to see if NAME is a *syntactically* valid tag name (but not that
  it necessarily exists, if it's a familial tag)."""
  if TagIsFamilial(name):
    family, option = name.split(':', 1)
    return IsValidTagPiece(family) and IsValidTagPiece(option)
  else:
    return IsValidTagPiece(name)


def TagIsFamilial(name):
  return ':' in name


def CanonicalizeTagName(name):
  return name.lower()


class TagFamily(db.Model):
  # Its key_name is the family name.
  options = db.StringListProperty()


class RequestHandler(webapp.RequestHandler):
  def render_template(self, template_name, params):
    path = os.path.join(os.path.dirname(__file__), 'templates',
                        '%s.html' % template_name)
    params['current_user'] = users.get_current_user()
    params['log_out_url'] = users.create_logout_url('/')
    params['instance_name'] = INSTANCE_NAME
    self.response.out.write(template.render(path, params))


class FamilyListHandler(RequestHandler):
  def get(self):
    families = TagFamily.all()
    self.render_template("families", {
      "families": families
    })


class FamilyCreateHandler(RequestHandler):
  def post(self):
    name = self.request.get('name')
    # TODO(glasser): Better error handling.
    assert IsValidTagPiece(name)
    TagFamily.get_or_insert(name)
    self.redirect(FamilyListHandler.get_url())


class FamilyOptionCreateHandler(RequestHandler):
  def post(self, family_name):
    family = TagFamily.get_by_key_name(family_name)
    # TODO(glasser): Better error handling.
    assert family is not None
    option = self.request.get('option')
    # TODO(glasser): Better error handling.
    assert IsValidTagPiece(option)
    # TODO(glasser): Technically this is an unlocked read-modify-write
    # and there could be a race condition; in this particular
    # admin-only case I'm going to lean towards the impact being
    # marginal.
    if option not in family.options:
      family.options.append(option)
    family.put()
    self.redirect(FamilyListHandler.get_url())


def main():
  application = webapp.WSGIApplication([('/family/?', FamilyListHandler),
                                        (('/family/add-option/(%s)/?'
                                          % TAG_PIECE),
                                         FamilyOptionCreateHandler),
                                        ('/family/add/?', FamilyCreateHandler),
                                        ],
                                       debug=True)
  wsgiref.handlers.CGIHandler().run(application)


if __name__ == '__main__':
  main()
