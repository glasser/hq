#!/usr/bin/env python2.5

import datetime
import re

from google.appengine.api import datastore
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
TAG_PIECE = METADATA_NAME = '[a-zA-Z0-9-]+'
_VALID_TAG_PIECE_RE = re.compile('^%s$' % TAG_PIECE)
TAG_NAME = '%s|%s%%3[Aa]%s' % (TAG_PIECE, TAG_PIECE, TAG_PIECE)
def ValidateTagPiece(name):
  """Checks to see if NAME is a valid name for a tag family, a family option,
  or a non-family tag; raises db.BadValueError if not."""
  if not _VALID_TAG_PIECE_RE.match(name):
    raise db.BadValueError("Invalid piece '%s'" % name)
ValidateMetadataName = ValidateTagPiece

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
CanonicalizeTagPiece = CanonicalizeTagName

def CanonicalizeTagNameFromQuery(name):
  return name.replace('%3a', ':').replace('%3A', ':').replace(
    '%3d', '=').replace('%3D', '=').lower()


class TagFamily(db.Model):
  # Its key_name is the family name.
  def __init__(self, *args, **kwds):
    if 'key_name' in kwds:
      assert kwds['key_name'] is not None
      # TODO(glasser): Better error handling.
      ValidateTagPiece(kwds['key_name'])
    super(TagFamily, self).__init__(*args, **kwds)

  options = ValidatingStringListProperty(validator=ValidateUniqueTagPieces)


class PuzzleMetadata(db.Model):
  # Its key_name is the metadata's name, and follows the same rule as
  # tag pieces.
  def __init__(self, *args, **kwds):
    if 'key_name' in kwds:
      assert kwds['key_name'] is not None
      # TODO(glasser): Better error handling.
      ValidateMetadataName(kwds['key_name'])
    super(PuzzleMetadata, self).__init__(*args, **kwds)

  @staticmethod
  def puzzle_field_name(name):
    return 'metadata_%s' % name.replace('-', '_')


class Puzzle(db.Expando):
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

  def ordered_families(self):
    ret = []
    for family in TagFamily.all():
      for option in family.options:
        tag_name = '%s:%s' % (family.key().name(), option)
        if tag_name in self.tags:
          ret.append((family, option, tag_name))
          break
      else:
        ret.append((family, None))
    return ret

  def option_for_family(self, family_name):
    prefix = '%s:' % family_name
    for tag in self.tags:
      if tag.startswith(prefix):
        return tag[len(prefix):]
    return None

  def metadata(self):
    metadata = []
    for metadatum in PuzzleMetadata.all():
      field_name = PuzzleMetadata.puzzle_field_name(metadatum.key().name())
      try:
        value = getattr(self, field_name)
      except AttributeError, e:
        value = None
      metadata.append((metadatum.key().name(), value))
    return metadata

  def tags_as_css_classes(self):
    def as_css_class(tag):
      return 'tag_' + tag.replace(':', '_')
    return ' '.join(map(as_css_class, self.tags))


class PuzzleQuery(object):
  def __init__(self, db_query, orders, tags, negative_tags, show_metas):
    self.__db_query = db_query
    # We want to be able to sort on custom fields, but we can't create
    # new indexes after deploying, so we need to sort ourselves.
    # (Plus, we want to be able to include puzzles that lack the field
    # that we're sorting on, which we can't with datastore's sort.)
    # __orders is a list of tuples (field_name,
    # datastore.Query.ASCENDING/DESCENDING).
    self.__orders = orders
    # The query already is filtered on these tags; this is just for
    # description.
    self.__tags = tags
    # The way that list properties work, there's no real way to filter
    # on "doesn't contain a tag", so we do it in this class.
    self.__negative_tags = negative_tags
    # Just a list of metadata names that should be shown in any
    # displayed list.  (You may access this directly.)
    self.show_metas = show_metas

  @classmethod
  def parse(cls, path):
    if path is None:
      path = ''
    pieces = [CanonicalizeTagNameFromQuery(t)
              for t in path.split('/')
              if t]
    db_query = Puzzle.all()
    orders = []
    tags = set()
    negative_tags = set()
    show_metas = []
    show_deleted = False

    for piece in pieces:
      if '=' not in piece:
        piece = 'tag=' + piece
      command, arg = piece.split('=', 1)

      if command == 'tag':
        # TODO(glasser): better error handling.
        assert arg
        if arg[0] == '-':
          arg = arg[1:]
          ValidateTagName(arg)
          negative_tags.add(arg)
        else:
          if arg == 'deleted':
            show_deleted = True
          ValidateTagName(arg)
          tags.add(arg)  # This is just for describe purposes.
          db_query.filter('tags = ', arg)
      elif command == 'ascmeta' or command == 'descmeta':
        ValidateMetadataName(arg)
        field_name = PuzzleMetadata.puzzle_field_name(arg)
        direction = datastore.Query.ASCENDING
        if command == 'descmeta':
          direction = datastore.Query.DESCENDING
        orders.append((field_name, direction))
      elif command == 'showmeta':
        ValidateMetadataName(arg)
        show_metas.append(arg)
      else:
        assert False, "error in search query: unknown command '%s'" % command

    if not show_deleted:
        negative_tags.add('deleted')
    return cls(db_query, orders, tags, negative_tags, show_metas)

  def __iter__(self):
    puzzles = []
    for puzzle in self.__db_query:
      valid = True
      for tag in puzzle.tags:
        if tag in self.__negative_tags:
          valid = False
          break
      if valid:
        puzzles.append(puzzle)

    def compare_by_orders(a, b):
      # Based loosely on order_compare_entities in datastore_file_stub.
      for o in self.__orders:
        try:
          a_val = getattr(a, o[0])
        except AttributeError:
          a_val = None
        try:
          b_val = getattr(b, o[0])
        except AttributeError:
          b_val = None
        cmped = cmp(a_val, b_val)
        if o[1] == datastore.Query.DESCENDING:
          cmped = -cmped
        if cmped != 0:
          return cmped
      return cmp(a.key(), b.key())

    puzzles.sort(compare_by_orders)
    return iter(puzzles)

  def describe_query(self):
    return " ".join(["[%s]" % tag for tag in self.__tags]
                    + ["[-%s]" % tag for tag in self.__negative_tags])

  def show_meta_fields(self):
    return map(PuzzleMetadata.puzzle_field_name, self.show_metas)


# Borrowed from ryanb@google.com's timezones demo.
class UtcTzinfo(datetime.tzinfo):
  def utcoffset(self, dt): return datetime.timedelta(0)
  def dst(self, dt): return datetime.timedelta(0)
  def tzname(self, dt): return 'UTC'
  def olsen_name(self): return 'UTC'

UTC = UtcTzinfo()

class EstTzinfo(datetime.tzinfo):
  def utcoffset(self, dt): return datetime.timedelta(hours=-5)
  def dst(self, dt): return datetime.timedelta(0)
  def tzname(self, dt): return 'EST+05EDT'
  def olsen_name(self): return 'US/Eastern'

EST = EstTzinfo()

def to_eastern(dt):
  return dt.replace(tzinfo=UTC).astimezone(EST)

def datetime_display(dt):
  """The date as a displayable string; doesn't need to be escaped.  This
  is Mystery Hunt, so we can assume Eastern time, and the weekday name
  is enough to differentiate days."""
  return to_eastern(dt).strftime("%r on %A")


class Spreadsheet(db.Model):
  puzzle = db.ReferenceProperty(reference_class=Puzzle, required=True)
  spreadsheet_key = db.StringProperty(required=True)


class Comment(db.Model):
  # A comment's parent is the puzzle it is on (this allows
  # transactions to modify two comments at once).
  replaced_by = db.SelfReferenceProperty()
  created = db.DateTimeProperty(auto_now_add=True)
  author = db.StringProperty()
  text = db.TextProperty()
  # Note: the choices here are intentionally sorted from most
  # important to least important.
  PRIORITIES = ('important', 'normal', 'useless')
  priority = db.StringProperty(choices=PRIORITIES, default='normal')

  def newest_version(self):
    current = self
    next = self.replaced_by
    while next is not None:
      current = next
      next = current.replaced_by
    return current

  def created_display(self):
    """The date as a displayable string; doesn't need to be escaped.  This
    is Mystery Hunt, so we can assume Eastern time, and the weekday name
    is enough to differentiate days."""
    return datetime_display(self.created)

  @staticmethod
  def canonicalize(some_text):
    if some_text.endswith('\n'):
      return some_text
    return some_text + '\n'


class Banner(db.Model):
  contents = db.TextProperty()
  created = db.DateTimeProperty(auto_now_add=True)
  
  MEMCACHE_KEY = 'rendered:banners'

  # Warning: using db.put or db.delete won't trigger these memcache flushes!
  def delete(self):
    super(Banner, self).delete()
    memcache.flush_all()
  def put(self):
    super(Banner, self).put()
    memcache.flush_all()

  def created_display(self):
    """The date as a displayable string; doesn't need to be escaped.  This
    is Mystery Hunt, so we can assume Eastern time, and the weekday name
    is enough to differentiate days."""
    return datetime_display(self.created)

  @classmethod
  def get_rendered(cls):
    rendered = memcache.get(cls.MEMCACHE_KEY)
    if rendered is not None:
      return rendered
    banners = cls.all()
    rendered = handler.RequestHandler.render_template_to_string('banners', {
      'banners': banners,
    }, include_rendered_banners=False, include_rendered_newsfeeds=False)
    memcache.set(cls.MEMCACHE_KEY, rendered)
    return rendered


class Newsfeed(db.Model):
  contents = db.TextProperty()
  created  = db.DateTimeProperty(auto_now_add=True)

  MEMCACHE_KEY = 'rendered:newsfeeds'

  # Warning: using db.put or db.delete won't trigger these memcache flushes!
  def delete(self):
    super(Banner, self).delete()
    memcache.flush_all()
  def put(self):
    super(Newsfeed, self).put()
    memcache.flush_all()

  def created_display(self):
    """The date as a displayable string; doesn't need to be escaped.  This
    is Mystery Hunt, so we can assume Eastern time, and the weekday name
    is enough to differentiate days."""
    return datetime_display(self.created)

  @classmethod
  def get_rendered(cls):
    rendered = memcache.get(cls.MEMCACHE_KEY)
    if rendered is not None:
      return rendered
    newsfeeds = cls.all().order("-created")
    rendered = handler.RequestHandler.render_template_to_string('newsfeeds', {
      'newsfeeds': newsfeeds.fetch(5),
    }, include_rendered_banners=False, include_rendered_newsfeeds=False)
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


class Username(db.Model):
  # Its key_name is the username.
  pass
