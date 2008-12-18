#!/usr/bin/env python2.5

import re

from google.appengine.ext import db

# We assume throughout the templates that tag names don't need to be
# escaped.

TAG_PIECE = '[a-zA-Z0-9-]+'
_VALID_TAG_PIECE_RE = re.compile('^%s$' % TAG_PIECE)
def ValidateTagPiece(name):
  """Checks to see if NAME is a valid name for a tag family, a family option,
  or a non-family tag; raises db.BadValueError if not."""
  if not _VALID_TAG_PIECE_RE.match(name):
    raise db.BadValueError("Invalid tag piece '%s'" % name)


def ValidateTagPieces(names):
  for name in names:
    ValidateTagPiece(name)


def ValidateTagName(name):
  """Checks to see if NAME is a *syntactically* valid tag name (but not that
  it necessarily exists, if it's a familial tag); raises db.BadValueError if
  not."""
  if TagIsFamilial(name):
    family, option = name.split(':', 1)
    ValidateTagPiece(family)
    ValidateTagPiece(option)
  else:
    ValidateTagPiece(name)


def ValidateTagNames(names):
  for name in names:
    ValidateTagNames(name)


def TagIsFamilial(name):
  return ':' in name


def CanonicalizeTagName(name):
  return name.lower()


class TagFamily(db.Model):
  # Its key_name is the family name.
  options = db.StringListProperty(validator=ValidateTagPieces)


class Puzzle(db.Model):
  # TODO(glasser): Maximum length is 500 for StringProperty (unindexed
  # TextProperty is unlimited); is this OK?
  # TODO(glasser): Test that unicode titles work properly.
  title = db.StringProperty()
  tags = db.StringListProperty(validator=ValidateTagNames)
