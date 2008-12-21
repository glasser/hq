#!/usr/bin/env python2.5

import re

from google.appengine.ext import db

# Temporary workaround for an upstream bug where ListPropertys are
# only validated at set time (ie, mutation isn't detected).
# TODO(glasser): See if upstream patch is accepted and released.
class ValidatingStringListProperty(db.StringListProperty):
  def get_value_for_datastore(self, model_instance):
    value = super(ValidatingStringListProperty, self).get_value_for_datastore(
        model_instance)
    if self.validator:
      self.validator(value)
    return value

# We assume throughout the templates that tag names don't need to be
# escaped.

# TAG_PIECE and TAG_NAME can be interpolated into URL regexps in
# handler lists; if so, they should be in parentheses (specifically,
# because TAG_NAME uses |).  Note that TAG_NAME can't use (?:) because
# reverse_helper does not support that.  Also, you need to pass tag
# names through CanonicalizeTagNameFromQuery.
TAG_PIECE = '[a-zA-Z0-9-]+'
_VALID_TAG_PIECE_RE = re.compile('^%s$' % TAG_PIECE)
TAG_NAME = '%s|%s%%3[Aa]%s' % (TAG_PIECE, TAG_PIECE, TAG_PIECE)
def ValidateTagPiece(name):
  """Checks to see if NAME is a valid name for a tag family, a family option,
  or a non-family tag; raises db.BadValueError if not."""
  if not _VALID_TAG_PIECE_RE.match(name):
    raise db.BadValueError("Invalid tag piece '%s'" % name)


def ValidateTagPieces(names):
  for name in names:
    ValidateTagPiece(name)


def ValidateUniqueTagPieces(pieces):
  ValidateTagPieces(pieces)
  if len(pieces) != len(set(pieces)):
    raise db.BadValueError("Duplicated tag pieces")


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
    ValidateTagName(name)


def ValidateUniqueTagNames(names):
  ValidateTagNames(names)
  if len(names) != len(set(names)):
    raise db.BadValueError("Duplicated tag names")


def TagIsFamilial(name):
  return ':' in name


def CanonicalizeTagName(name):
  return name.lower()


def CanonicalizeTagNameFromQuery(name):
  return name.replace('%3a', ':').replace('%3A', ':').lower()


class TagFamily(db.Model):
  # Its key_name is the family name.
  def __init__(self, *args, **kwds):
    if 'key_name' in kwds:
      assert kwds['key_name'] is not None
      # TODO(glasser): Better error handling.
      ValidateTagPiece(kwds['key_name'])
    super(TagFamily, self).__init__(*args, **kwds)

  options = ValidatingStringListProperty(validator=ValidateUniqueTagPieces)


class Puzzle(db.Model):
  # TODO(glasser): Maximum length is 500 for StringProperty (unindexed
  # TextProperty is unlimited); is this OK?
  # TODO(glasser): Test that unicode titles work properly.
  title = db.StringProperty()
  tags = ValidatingStringListProperty(validator=ValidateUniqueTagNames)

  @classmethod
  def add_tag(cls, id, tag):
    """Adds a tag to the puzzle; returns True if this was a change (ie, the
    tag was not already there."""
    def txn():
      puzzle = cls.get_by_id(id)
      ValidateTagName(tag)
      if tag in puzzle.tags:
        return False
      puzzle.tags.append(tag)
      puzzle.put()
      return True
    return db.run_in_transaction(txn)

  @classmethod
  def delete_tag(cls, id, tag):
    """Removes a tag from the puzzle; returns True if this was a change (ie,
    the tag was actually there."""
    def txn():
      puzzle = cls.get_by_id(id)
      if tag in puzzle.tags:
        puzzle.tags.remove(tag)
        puzzle.put()
        return True
      return False
    return db.run_in_transaction(txn)
