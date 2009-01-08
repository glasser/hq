#!/usr/bin/env python2.5
import model
import handler

from google.appengine.api import users

class PuzzleListHandler(handler.RequestHandler):
  def get(self, tag=None):
    puzzles = model.Puzzle.all()
    if tag is not None:
      tag = model.CanonicalizeTagNameFromQuery(tag)
      # TODO(glasser): Better error handling.
      model.ValidateTagName(tag)
      puzzles.filter("tags =", tag)
    self.render_template("puzzle-list", {
      "puzzles": puzzles,
      "searchtag": tag,
    })


class PuzzleHandler(handler.RequestHandler):
  def get(self, key_id):
    puzzle = model.Puzzle.get_by_id(long(key_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None
    comments = puzzle.comment_set
    comments.filter("replaced_by =", None)
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
    puzzle.put()
    # TODO(glasser): Redirect to individual puzzle page.
    self.redirect(PuzzleListHandler.get_url())


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


class CommentAddHandler(handler.RequestHandler):
  def post(self, puzzle_id):
    puzzle = model.Puzzle.get_by_id(long(puzzle_id))
    # TODO(glasser): Better error handling.
    assert puzzle is not None
    comment = model.Comment(puzzle=puzzle,
                            author=users.get_current_user(),
                            text=self.request.get('text'))
    comment.put()
    self.redirect(PuzzleHandler.get_url(puzzle_id))

HANDLERS = [
    ('/puzzles/?', PuzzleListHandler),
    # TODO(glasser): Support multiple tags (intersection).
    ('/puzzles/tags/(%s)/?' % model.TAG_NAME, PuzzleListHandler),
    ('/puzzles/create/?', PuzzleCreateHandler),
    ('/puzzles/show/(\\d+)/?', PuzzleHandler),
    ('/puzzles/add-tag/(\\d+)/?', PuzzleTagAddHandler),
    ('/puzzles/delete-tag/(\\d+)/(%s)/?' % model.TAG_NAME,
     PuzzleTagDeleteHandler),
    ('/puzzles/add-comment/(\\d+)/?', CommentAddHandler),
]
