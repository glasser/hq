#!/usr/bin/env python2.5
import random
import unittest

from google.appengine.ext import db

import model

class TagTest(unittest.TestCase):

  def test_good_tag_pieces(self):
    for x in ('foo', 'bar24', '1', '35', 'foo-bar',
              '5th-level', '-foo-', 'bLaLaLa'):
      model.ValidateTagPiece(x)

  def test_bad_tag_pieces(self):
    for x in ('round:1', 'status:solved', 'foo_bar', '',
              'foo bar', '<', '>', '&'):
      self.assertRaises(db.BadValueError, model.ValidateTagPiece, x)


class PuzzleTest(unittest.TestCase):

  def test_tag_race_condition(self):
    """This is a failed attempt to make a test that shows that there could
    be race conditions in add_tag and delete_tag, but that they are
    avoided.  However, there's a problem: the 'correct' API requires
    that the test make single calls to a Puzzle.add_tag(id, tag),
    which doesn't let it insert any sort of explicit "yield", and you
    can't actually use threading or multiprocessing in App Engine, so
    yields really do have to be explicit.  So I couldn't figure out
    how to structure the code to expose the race condition *and* allow
    for a transaction-based solution, at the same time (though each
    separate was possible).

    But for the hell of it, a test that doesn't actually have a race
    condition."""

    puzzle = model.Puzzle(title='Some puzzle')
    puzzle_id = puzzle.put().id()

    runs = 20
    prefixes = ('a', 'b', 'c', 'd')

    def incrementer_coroutine(my_prefix):
      for index in xrange(runs):
        old_tag = '%s%d' % (my_prefix, index)
        self.assertTrue(model.Puzzle.delete_tag(puzzle_id, old_tag),
                        "Couldn't delete '%s'" % old_tag)
        yield
        new_tag = '%s%d' % (my_prefix, index + 1)
        self.assertTrue(model.Puzzle.add_tag(puzzle_id, new_tag),
                        "Couldn't add '%s'" % new_tag)
        yield

    incrementers = []
    for prefix in prefixes:
      model.Puzzle.add_tag(puzzle_id, '%s0' % prefix)
      incrementers.append(incrementer_coroutine(prefix))

    while incrementers:
      incrementer = incrementers.pop(random.randint(0, len(incrementers) - 1))
      try:
        incrementer.next()
      except StopIteration:
        continue
      incrementers.append(incrementer)

    puzzle = model.Puzzle.get_by_id(puzzle_id)
    self.assertEquals(set([u'%s%d' % (prefix, runs) for prefix in prefixes]),
                      set(puzzle.tags))
