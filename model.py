#!/usr/bin/env python2.5

import re

from google.appengine.api import memcache
from google.appengine.ext import db

import handler

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
    family, option = SplitFamilialTag(name)
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


def SplitFamilialTag(name):
  assert TagIsFamilial(name)
  return name.split(':', 1)


def TagIsFamilial(name):
  return ':' in name


def TagIsGeneric(name):
  return not TagIsFamilial(name)


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
  # TODO(glasser): Validate that no family has multiple tags.
  tags = ValidatingStringListProperty(validator=ValidateUniqueTagNames)

  @classmethod
  def add_tag(cls, id, tag):
    """Adds a tag to the puzzle; returns True if this was a change
    (ie, the tag was not already there.  If it is a familial tag,
    deletes all other tags of the same family.  As a special case,
    'family:' deletes all tags in the given family without adding
    anything."""
    def txn():
      puzzle = cls.get_by_id(id)
      # TODO(glasser): Better error handling.
      assert puzzle is not None

      changed = False

      if TagIsFamilial(tag):
        family, option = SplitFamilialTag(tag)
        old_len = len(puzzle.tags)
        puzzle.tags = filter(lambda t: not t.startswith('%s:' % family),
                             puzzle.tags)
        changed = old_len != len(puzzle.tags)
        if not option:
          if changed:
            puzzle.put()
          return changed

      ValidateTagName(tag)
      if tag in puzzle.tags:
        if changed:
          puzzle.put()
        return changed
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
      # TODO(glasser): Better error handling.
      assert puzzle is not None
      if tag in puzzle.tags:
        puzzle.tags.remove(tag)
        puzzle.put()
        return True
      return False
    return db.run_in_transaction(txn)

  def generic_tags(self):
    return filter(TagIsGeneric, self.tags)

  def families(self):
    ret = {}
    families = TagFamily.all()
    for family in families:
      puzzle_options = []
      found_any = False
      for option in family.options:
        tag_name = '%s:%s' % (family.key().name(), option)
        found = tag_name in self.tags
        puzzle_options.append((option, found, tag_name))
        if found:
          found_any = True
      puzzle_options.insert(0, ('', not found_any, ''))
      ret[family.key().name()] = puzzle_options
    return ret

  def tags_as_css_classes(self):
    def as_css_class(tag):
      return 'tag_' + tag.replace(':', '_')
    return ' '.join(map(as_css_class, self.tags))


class Comment(db.Model):
  # A comment's parent is the puzzle it is on (this allows
  # transactions to modify two comments at once).
  replaced_by = db.SelfReferenceProperty()
  created = db.DateTimeProperty(auto_now_add=True)
  author = db.UserProperty()
  text = db.TextProperty()


class Banner(db.Model):
  contents = db.TextProperty()

  MEMCACHE_KEY = 'rendered:banners'

  # Warning: using db.put or db.delete won't trigger these memcache flushes!
  def delete(self):
    super(Banner, self).delete()
    memcache.flush_all()
  def put(self):
    super(Banner, self).put()
    memcache.flush_all()

  @classmethod
  def get_rendered(cls):
    rendered = memcache.get(cls.MEMCACHE_KEY)
    if rendered is not None:
      return rendered
    banners = cls.all()
    rendered = handler.RequestHandler.render_template_to_string('banners', {
      'banners': banners,
    }, include_rendered_banners=False)
    memcache.set(cls.MEMCACHE_KEY, rendered)
    return rendered


# Don't manipulate elements of this class directly: just use
# get_custom_css and set_custom_css.
class Css(db.Model):
  contents = db.TextProperty()

  SINGLETON_DB_KEY = 'singleton'
  MEMCACHE_KEY = 'rendered:css'

  @classmethod
  def get_custom_css(cls):
    rendered = memcache.get(cls.MEMCACHE_KEY)
    if rendered is not None:
      return rendered

    css_obj = cls.get_by_key_name(cls.SINGLETON_DB_KEY)
    rendered = ''
    if css_obj is not None:
      rendered = css_obj.contents

    memcache.set(cls.MEMCACHE_KEY, rendered)
    return rendered

  @classmethod
  def set_custom_css(cls, rendered):
    # Similar to get_or_insert, but sets the contents either way.
    def txn():
      entity = cls.get_by_key_name(cls.SINGLETON_DB_KEY)
      if entity is None:
        entity = cls(key_name=cls.SINGLETON_DB_KEY,
                     contents=rendered)
      else:
        entity.contents = rendered
      entity.put()
    db.run_in_transaction(txn)
    memcache.set(cls.MEMCACHE_KEY, rendered)
