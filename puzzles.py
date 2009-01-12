#!/usr/bin/env python2.5
import random
import StringIO

import model
import handler

from google.appengine.api import users
from google.appengine.ext import db

import bzrlib.merge3
import atom
import gdata
import gdata.auth
import gdata.alt.appengine
import gdata.calendar  # Used for ACL stuff which isn't actually cal-specific
import gdata.docs.service
import gdata.service

class PuzzleListHandler(handler.RequestHandler):
  def get(self, tags=None):
    puzzles = model.PuzzleQuery.parse(tags)
    self.render_template("puzzle-list", {
      "puzzles": puzzles,
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
    self.render_template("puzzle", {
      "puzzle": puzzle,
      "comments": comments,
    })


class PuzzleCreateHandler(handler.RequestHandler):
  def post(self):
    title = self.request.get('title')
    # TODO(glasser): Better error handling.
    assert len(title)
    tags = self.request.get('tags')
    tag_list = list(set(map(model.CanonicalizeTagName, tags.split())))
    for tag in tag_list:
      if model.TagIsFamilial(tag):
        # TODO(glasser): Check that familial tags actually exist.
        # (Or ban familial tags from the free-form tag box.)
        pass
    puzzle = model.Puzzle()
    puzzle.title = title
    # TODO(glasser): Better error handling.
    puzzle.tags = tag_list
    puzzle_key = puzzle.put()
    self.redirect(PuzzleHandler.get_url(puzzle_key.id()))


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
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class PuzzleMetadataSetHandler(handler.RequestHandler):
  def post(self, puzzle_id, metadata_name):
    puzzle_id = long(puzzle_id)
    model.ValidateTagPiece(metadata_name)
    field_name = model.PuzzleMetadata.puzzle_field_name(metadata_name)
    value = self.request.get('value')
    def txn():
      puzzle = model.Puzzle.get_by_id(puzzle_id)
      setattr(puzzle, field_name, value)
      puzzle.put()
    db.run_in_transaction(txn)
    self.redirect(PuzzleHandler.get_url(puzzle_id))


class CommentAddHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle = model.Puzzle.get_by_id(long(puzzle_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None
    comment = model.Comment(puzzle=puzzle,
                            author=users.get_current_user(),
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
                                  author=users.get_current_user(),
                                  text=model.Comment.canonicalize(
                                      self.request.get('text')),
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


class SpreadsheetAddHandler(handler.RequestHandler):
  def get(self, puzzle_id):
    puzzle_id = long(puzzle_id)
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    # TODO(glasser): Better error handling.
    assert puzzle is not None

    client = gdata.docs.service.DocsService()
    gdata.alt.appengine.run_on_appengine(client)
    auth_token = gdata.auth.extract_auth_sub_token_from_url(self.request.uri)
    if auth_token:
      client.UpgradeToSessionToken(auth_token)

    virtual_csv_file = StringIO.StringIO(',,,')
    virtual_media_source = gdata.MediaSource(file_handle=virtual_csv_file,
                                             content_type='text/csv',
                                             content_length=3)
    random_junk = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz')
                           for i in xrange(25)])
    title = '%s [%s]' % (self.request.get('title'), random_junk)
    doc_key = None
    acl_link = None
    try:
      media_entry = client.UploadSpreadsheet(virtual_media_source,
                                             title)
    except gdata.service.RequestError, request_error:
      # If fetching fails, then tell the user that they need to login to
      # authorize this app by logging in at the following URL.
      if request_error[0]['status'] == 401:
        # Get the URL of the current page so that our AuthSub request will
        # send the user back to here.
        next = self.request.uri
        auth_sub_url = client.GenerateAuthSubURL(
            next,
            gdata.service.lookup_scopes('writely') +  # Doclist
            gdata.service.lookup_scopes('wise'),  # Spreadsheets
            domain=handler.APPS_DOMAIN)
        self.redirect(str(auth_sub_url))
        return
      elif (request_error[0]['status'] == 503 and
            request_error[0]['body'] == 'An unknown error has occurred.'):
        # Ugh.  This is a bug in spreadsheets, but I guess it's one we
        # can work around.
        query = gdata.docs.service.DocumentQuery(params={
            'title': title,
            'title-exact': 'true',
            })
        docfeed = client.QueryDocumentListFeed(query.ToUri())
        # TODO(glasser): Better error handling.
        assert docfeed.total_results.text == '1', "Made one spreadsheet"
        entry = docfeed.entry[0]
        doc_url = entry.id.text
        doc_url_prefix = ('http://docs.google.com/' +
                          'feeds/documents/private/full/spreadsheet%3A')
        assert doc_url.startswith(doc_url_prefix)
        doc_key = doc_url[len(doc_url_prefix):]
      else:
        self.response.out.write(
            'Something else went wrong, here is the error object: %s ' % (
                str(request_error[0])))
        return
    else:
      # Hmm, I've never actually gotten this to work without the 503,
      # so I don't know how to write the code for the correct case!
      self.response.out.write("""
        Sorry, the spreadsheet code was developed when the Spreadsheets API
        had a bug I had to work around.  Apparently the bug is fixed, so I
        can now write code for the non-buggy case... but I haven't yet.""")
      return
    # TODO(glasser): Better error handling.
    assert doc_key is not None
    acl_url = ('/feeds/acl/private/full/spreadsheet%3A'
               + doc_key)
    acl_feed = client.Get(acl_url,
                          converter=gdata.calendar.CalendarAclFeedFromString)
    assert acl_feed.total_results.text == '1', "Got one ACL entry"
    acl_edit_link = acl_feed.entry[0].GetEditLink()
    assert acl_edit_link is not None
    scope_everyone = gdata.calendar.Scope(scope_type='user',
                                          value='everyone')
    role_writer = gdata.calendar.Role(value='writer')
    category_access_rule = atom.Category(
        scheme='http://schemas.google.com/g/2005#kind',
        term='http://schemas.google.com/acl/2007#accessRule')
    acl_entry = gdata.calendar.CalendarAclEntry(
        role=role_writer,
        scope=scope_everyone,
        category=category_access_rule)
    new_entry = client.Post(acl_entry, acl_edit_link.href,
                            converter=gdata.calendar.CalendarAclEntryFromString)
    sheet = model.Spreadsheet(puzzle=puzzle, spreadsheet_key=doc_key)
    sheet.put()
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
]
