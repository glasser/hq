#!/usr/bin/env python2.5

import re

from google.appengine.ext import db


TAG_PIECE = '[a-zA-Z0-9-]+'
_VALID_TAG_PIECE_RE = re.compile('^%s$' % TAG_PIECE)
def IsValidTagPiece(name):
  """Checks to see if NAME is a valid name for a tag family, a family option,
  or a non-family tag."""
  return _VALID_TAG_PIECE_RE.match(name)


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
