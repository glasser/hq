#!/usr/bin/env python2.5
import os.path
import random
import re
import StringIO

from hq import model
from hq import handler

from google.appengine.api import users
from google.appengine.ext import db

import atom.core
import bzrlib.merge3
from django.utils import html
import gdata.acl.data
import gdata.docs.client
import gdata.docs.data
import gdata.gauth
import gdata.spreadsheets.client

# The file named here should not be checked into version control.
def LoadConsumerSecret():
  f = file(os.path.join(os.path.dirname(__file__), '..', 'CONSUMER_SECRET'))
  return f.read().strip()


GDATA_SETTINGS = {
  'CONSUMER_KEY': 'cic.battlestarelectronica.org',
  'CONSUMER_SECRET': LoadConsumerSecret(),
  'REQUEST_TOKEN': 'RequestToken',
  'ACCESS_TOKEN':  'AccessToken',
  'SCOPES': (gdata.docs.client.DocsClient.auth_scopes +
             gdata.spreadsheets.client.SpreadsheetsClient.auth_scopes),
}


def LoadAccessToken():
  access_token = gdata.gauth.AeLoad(GDATA_SETTINGS['ACCESS_TOKEN'])
  if isinstance(access_token, gdata.gauth.OAuthHmacToken):
    return access_token
  return None


class PuzzleListHandler(handler.RequestHandler):
  def get(self, tags=None):
    puzzles = model.PuzzleQuery.parse(tags)
    # Convert to list so we can iterate multiple times.
    families = list(model.TagFamily.all())
    self.render_template("puzzle-list", {
      "puzzles": puzzles,
      "families": families,
    })


class PuzzleHandler(handler.RequestHandler):
  def get(self, key_id):
    puzzle = model.Puzzle.get_by_id(long(key_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None
    comments = model.Comment.all()
    comments.ancestor(puzzle)
    comments.filter("replaced_by =", None)
    comments.order('priority')
    comments.order('-created')
    # Convert to list so we can iterate multiple times.
    families = list(model.TagFamily.all())
    self.render_template("puzzle", {
      "puzzle": puzzle,
      "comments": comments,
      "families": families,
      "has_access_token": LoadAccessToken() is not None,
    })


class PuzzleCreateHandler(handler.RequestHandler):
  def post(self):
    title = self.request.get('title')
    # TODO(glasser): Better error handling.
    assert len(title)
    tags = self.request.get('tags')
    tag_set = set(map(model.CanonicalizeTagName, tags.split()))
    for tag in tag_set:
      if model.TagIsFamilial(tag):
        # TODO(glasser): Check that familial tags actually exist.
        # (Or ban familial tags from the free-form tag box.)
        pass
    puzzle = model.Puzzle()
    puzzle.title = title
    for family in model.TagFamily.all():
      family_value = self.request.get('tag_' + family.key().name())
      if family_value:
        tag_set.add('%s:%s' % (family.key().name(), family_value))
    # TODO(glasser): Better error handling.
    puzzle.tags = list(tag_set)
    for metadatum in model.PuzzleMetadata.all():
      field_name = model.PuzzleMetadata.puzzle_field_name(
          metadatum.key().name())
      field_value = self.request.get(field_name)
      if field_value:
        setattr(puzzle, field_name, field_value)
    puzzle_key = puzzle.put()

    # we've just created a puzzle, add that to the newsfeeds
    puzzle_url = PuzzleHandler.get_url(puzzle_key.id())
    newsfeed = model.Newsfeed(
        contents='<a href="%s">%s</a> added' % (puzzle_url, html.escape(title)))
    newsfeed.put()

    self.redirect(puzzle_url)


class PuzzleTagDeleteHandler(handler.RequestHandler):
  def get(self, puzzle_id, tag):
    puzzle_id = long(puzzle_id)
    tag = model.CanonicalizeTagNameFromQuery(tag)
    model.Puzzle.delete_tag(puzzle_id, tag)
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class PuzzleTagAddHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle_id = long(puzzle_id)
    # Note that "foo:" is a valid tag value here, meaning to delete
    # all tags in the "foo" family.
    tag = model.CanonicalizeTagName(self.request.get('tag'))
    # TODO(glasser): Better error handling.
    model.Puzzle.add_tag(puzzle_id, tag)

    puzzle_url = PuzzleHandler.get_url(puzzle_id)
    # if we've just solved a puzzle, add that to the newsfeeds
    if tag == 'status:solved':
      title = html.escape(model.Puzzle.get_by_id(puzzle_id).title)
      newsfeed = model.Newsfeed(
          contents='<a href="%s">%s</a> solved!' % (puzzle_url, title))
      newsfeed.put()

    self.redirect(puzzle_url)


class MetadataConflictError(Exception):
  def __init__(self, newest):
    self.newest = newest


class PuzzleMetadataSetHandler(handler.RequestHandler):
  def post(self, puzzle_id, metadata_name):
    puzzle_id = long(puzzle_id)
    model.ValidateTagPiece(metadata_name)
    field_name = model.PuzzleMetadata.puzzle_field_name(metadata_name)
    value = self.request.get('value', '')
    base_value = self.request.get('base_value', '')
    def txn():
      puzzle = model.Puzzle.get_by_id(puzzle_id)
      newest_value = ''
      try:
        newest_value = getattr(puzzle, field_name)
      except AttributeError:
        pass
      if base_value != newest_value:
        raise MetadataConflictError(newest_value)
      setattr(puzzle, field_name, value)
      puzzle.put()
    try:
      db.run_in_transaction(txn)
    except MetadataConflictError, e:
      return self.conflict_resolution(puzzle_id, metadata_name,
                                      base_value, e.newest)
    self.redirect(PuzzleHandler.get_url(puzzle_id))

  def conflict_resolution(self, puzzle_id, metadata_name,
                          base_value, newest_value):
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    your_value = self.request.get('value', '')
    self.render_template("resolve-metadata-conflict", {
      "puzzle": puzzle,
      "metadata_name": metadata_name,
      "base_value": base_value,
      "newest_value": newest_value,
      "your_value": your_value,
    })


class CommentAddHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle = model.Puzzle.get_by_id(long(puzzle_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None
    comment = model.Comment(puzzle=puzzle,
                            author=self.username,
                            text=model.Comment.canonicalize(
                                self.request.get('text')),
                            parent=puzzle)
    comment.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class CommentConflictError(Exception):
  def __init__(self, base_comment):
    self.base_comment = base_comment


class CommentEditHandler(handler.RequestHandler):
  def post(self, puzzle_id, comment_id):
    puzzle = model.Puzzle.get_by_id(long(puzzle_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None

    def txn():
      old_comment = model.Comment.get_by_id(long(comment_id), parent=puzzle)
      # TODO(glasser): Better error handling.
      assert old_comment is not None

      if old_comment.replaced_by is not None:
        raise CommentConflictError(old_comment)
      new_comment = model.Comment(puzzle=puzzle,
                                  author=self.username,
                                  text=model.Comment.canonicalize(
                                      self.request.get('text')),
                                  priority=old_comment.priority,
                                  parent=puzzle)
      new_comment.put()
      old_comment.replaced_by = new_comment
      old_comment.put()
    try:
      db.run_in_transaction(txn)
    except CommentConflictError, e:
      return self.conflict_resolution(puzzle, e.base_comment)
    self.redirect(PuzzleHandler.get_url(puzzle.key().id()))

  def conflict_resolution(self, puzzle, base_comment):
    newest_comment = base_comment.newest_version()
    your_text = model.Comment.canonicalize(self.request.get('text'))

    base_lines = base_comment.text.splitlines(True)
    newest_lines = newest_comment.text.splitlines(True)
    your_lines = your_text.splitlines(True)
    m3 = bzrlib.merge3.Merge3(base_lines, newest_lines, your_lines)
    merged_text = "".join(m3.merge_lines(reprocess=True))

    self.render_template("resolve-conflict", {
      "puzzle": puzzle,
      "base_comment": base_comment,
      "newest_comment": newest_comment,
      "your_text": your_text,
      "merged_text": merged_text,
    })


class CommentPrioritizeHandler(handler.RequestHandler):
  def post(self, puzzle_id, comment_id):
    priority = self.request.get('priority')
    # TODO(glasser): Better error handling.
    assert priority in model.Comment.PRIORITIES

    puzzle = model.Puzzle.get_by_id(long(puzzle_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None

    def txn():
      old_comment = model.Comment.get_by_id(long(comment_id), parent=puzzle)
      # TODO(glasser): Better error handling.
      assert old_comment is not None
      comment = old_comment.newest_version()
      comment.priority = priority
      comment.put()
    db.run_in_transaction(txn)
    self.redirect(PuzzleHandler.get_url(puzzle.key().id()))


class LogOutForTokensHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    gdata.gauth.AeDelete(GDATA_SETTINGS['REQUEST_TOKEN'])
    gdata.gauth.AeDelete(GDATA_SETTINGS['ACCESS_TOKEN'])
    self.redirect(users.create_logout_url(
        dest_url=GetOAuthTokenHandler.get_url(puzzle_id)))


class GetOAuthTokenHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    callback_url = ('http://' + GDATA_SETTINGS['CONSUMER_KEY']
                    + GetAccessTokenHandler.get_url(puzzle_id))
    client = gdata.docs.client.DocsClient()
    request_token = client.GetOAuthToken(
      GDATA_SETTINGS['SCOPES'], callback_url, GDATA_SETTINGS['CONSUMER_KEY'],
      GDATA_SETTINGS['CONSUMER_SECRET'])
    gdata.gauth.AeSave(request_token, GDATA_SETTINGS['REQUEST_TOKEN'])
    self.redirect(str(request_token.generate_authorization_url()))


class GetAccessTokenHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    request_token = gdata.gauth.AeLoad(GDATA_SETTINGS['REQUEST_TOKEN'])
    request_token.token = self.request.get('oauth_token')
    assert request_token.token != ''
    request_token.verifier = self.request.get('oauth_verifier')
    assert request_token.verifier != ''
    request_token.auth_state = gdata.gauth.AUTHORIZED_REQUEST_TOKEN
    client = gdata.docs.client.DocsClient()
    access_token = client.GetAccessToken(request_token)
    gdata.gauth.AeSave(access_token, GDATA_SETTINGS['ACCESS_TOKEN'])
    self.redirect(LogOutAfterTokensHandler.get_url(puzzle_id))


class LogOutAfterTokensHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    self.redirect(users.create_logout_url(
        dest_url=PuzzleHandler.get_url(puzzle_id)))


class AclWithKey(atom.core.XmlElement):
  _qname = gdata.acl.data.GACL_TEMPLATE % 'withKey'
  key = 'key'
  role = gdata.acl.data.AclRole


gdata.acl.data.AclEntry.with_key = AclWithKey


class SpreadsheetAddHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    puzzle_id = long(puzzle_id)
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    # TODO(glasser): Better error handling.
    assert puzzle is not None

    access_token = LoadAccessToken()
    if access_token is None:
      self.redirect(GetOAuthTokenHandler.get_url(puzzle_id))
      return
    client = gdata.docs.client.DocsClient()
    auth_token = gdata.gauth.OAuthHmacToken(
      GDATA_SETTINGS['CONSUMER_KEY'], GDATA_SETTINGS['CONSUMER_SECRET'],
      access_token.token, access_token.token_secret,
      gdata.gauth.ACCESS_TOKEN,
      next=None, verifier=None)
    doc = client.Create(gdata.docs.data.SPREADSHEET_LABEL,
                        "%s [%s]" % (self.request.get('title'), puzzle.title),
                        auth_token=auth_token)
    match = gdata.docs.data.RESOURCE_ID_PATTERN.match(doc.resource_id.text)
    assert match
    assert match.group(1) == gdata.docs.data.SPREADSHEET_LABEL
    doc_key = match.group(3)
    acl_entry = gdata.docs.data.Acl(
      with_key=AclWithKey(key='ignored',
                          role=gdata.acl.data.AclRole(value='writer')),
      scope=gdata.acl.data.AclScope(type='default'))
    acl_entry.category.append(atom.data.Category(
      scheme=gdata.docs.data.DATA_KIND_SCHEME,
      term="http://schemas.google.com/acl/2007#accessRule"))
    acl_from_server = client.post(
      acl_entry, doc.get_acl_feed_link().href, auth_token=auth_token)
    auth_key = acl_from_server.with_key.key
    sheet = model.Spreadsheet(puzzle=puzzle, spreadsheet_key=doc_key,
                              auth_key=auth_key)
    sheet.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class RelatedAddHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle_id = long(puzzle_id)
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    # TODO(glasser): Better error handling.
    assert puzzle is not None

    query = self.request.get('query')
    # For validation.
    # TODO(glasser): Better error handling.
    model.PuzzleQuery.parse(query)

    related = model.Related(puzzle=puzzle, query=query)
    related.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))

class RelatedDeleteHandler(handler.RequestHandler):
  def get(self, related_id):
    related_id = long(related_id)
    related = model.Related.get_by_id(related_id)
    # TODO(glasser): Better error handling.
    puzzle_id = related.puzzle.key().id()
    related.delete()
    self.redirect(PuzzleHandler.get_url(puzzle_id))


_USERNAME_RE = re.compile('^[a-zA-Z0-9._-]+$')
class UserChangeHandler(handler.RequestHandler):
  def post(self):
    name = self.request.get('other')
    if not name:
      name = self.request.get('username')
    if name:
      assert _USERNAME_RE.match(name), (
        "Bad username: usernames may only contain letters, numbers, periods, " +
        "dashes, and underscores")
      self.set_username(name)
      model.Username.get_or_insert(name)
    self.redirect(PuzzleListHandler.get_url())


class TopPageHandler(handler.RequestHandler):
  def get(self):
    self.redirect(PuzzleListHandler.get_url('showmeta=answer'))


class ImageUploadHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle_id = long(puzzle_id)
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    # TODO(glasser): Better error handling.
    assert puzzle
    data = db.Blob(self.request.get('data'))
    image = model.Image(data=data, puzzle=puzzle,
                        content_type=self.request.get('content_type'))
    image.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class ImageViewHandler(handler.RequestHandler):
  def get(self, image_id):
    image_id = long(image_id)
    image = model.Image.get_by_id(image_id)
    # TODO(glasser): Better error handling.
    assert image
    self.response.headers['Content-Type'] = str(image.content_type)
    self.response.out.write(image.data)


class ImageDeleteHandler(handler.RequestHandler):
  def get(self, image_id):
    image_id = long(image_id)
    image = model.Image.get_by_id(image_id)
    # TODO(glasser): Better error handling.
    assert image
    # Don't actually delete; just "un-link"
    puzzle_id = image.puzzle.key().id()
    image.puzzle = None
    image.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))


HANDLERS = [
    ('/puzzles/?', PuzzleListHandler),
    # TODO(glasser): Support multiple tags (intersection).
    ('/puzzles/search/(.+)/?', PuzzleListHandler),
    ('/puzzles/create/?', PuzzleCreateHandler),
    ('/puzzles/show/(\\d+)/?', PuzzleHandler),
    ('/puzzles/add-tag/(\\d+)/?', PuzzleTagAddHandler),
    ('/puzzles/delete-tag/(\\d+)/(%s)/?' % model.TAG_NAME,
     PuzzleTagDeleteHandler),
    ('/puzzles/set-metadata/(\\d+)/(%s)/?' % model.METADATA_NAME,
     PuzzleMetadataSetHandler),
    ('/puzzles/add-comment/(\\d+)/?', CommentAddHandler),
    ('/puzzles/edit-comment/(\\d+)/(\\d+)/?', CommentEditHandler),
    ('/puzzles/set-comment-priority/(\\d+)/(\\d+)/?', CommentPrioritizeHandler),
    ('/puzzles/add-spreadsheet/(\\d+)/?', SpreadsheetAddHandler),
    ('/puzzles/add-related/(\\d+)/?', RelatedAddHandler),
    ('/puzzles/delete-related/(\\d+)/?', RelatedDeleteHandler),
    ('/image/(\\d+)/?', ImageViewHandler),
    ('/puzzles/add-image/(\\d+)/?', ImageUploadHandler),
    ('/puzzles/delete-image/(\\d+)/?', ImageDeleteHandler),
    ('/change-user/?', UserChangeHandler),
    ('/log-out-for-tokens/(\\d+)', LogOutForTokensHandler),
    ('/get-oauth-token/(\\d+)', GetOAuthTokenHandler),
    ('/get-access-token/(\\d+)', GetAccessTokenHandler),
    ('/log-out-after-tokens/(\\d+)', LogOutAfterTokensHandler),
    ('/?', TopPageHandler),
]
