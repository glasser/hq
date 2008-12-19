#!/usr/bin/env python2.5
import model
import handler

class PuzzleListHandler(handler.RequestHandler):
  def get(self, tag=None):
    puzzles = model.Puzzle.all()
    if tag is not None:
      tag = model.CanonicalizeTagNameFromQuery(tag)
      puzzles.filter("tags =", tag)
    self.render_template("puzzle-list", {
      "puzzles": puzzles
    })


class PuzzleCreateHandler(handler.RequestHandler):
  def post(self):
    title = self.request.get('title')
    # TODO(glasser): Better error handling.
    assert len(title)
    tags = self.request.get('tags')
    tag_list = map(model.CanonicalizeTagName, tags.split())
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

HANDLERS = [
    ('/puzzles/?', PuzzleListHandler),
    # TODO(glasser): Support multiple tags (intersection).
    ('/puzzles/tags/(%s)/?' % model.TAG_NAME, PuzzleListHandler),
    ('/puzzles/create/?', PuzzleCreateHandler),
]
