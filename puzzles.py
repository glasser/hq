#!/usr/bin/env python2.5
import model
import handler

class PuzzleListHandler(handler.RequestHandler):
  def get(self):
    puzzles = model.Puzzle.all()
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
      # TODO(glasser): Better error handling.
      assert model.IsValidTagName(tag)
      if model.TagIsFamilial(tag):
        # TODO(glasser): Check that familial tags actually exist.
        # (Or ban familial tags from the free-form tag box.)
        pass
    puzzle = model.Puzzle()
    puzzle.title = title
    puzzle.tags = tag_list
    puzzle.put()
    # TODO(glasser): Redirect to individual puzzle page.
    self.redirect(PuzzleListHandler.get_url())

HANDLERS = [
    ('/puzzles/?', PuzzleListHandler),
    ('/puzzles/create/?', PuzzleCreateHandler),
]
