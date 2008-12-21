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
    puzzle = model.Puzzle(title='Some puzzle')
    puzzle_id = puzzle.put().id()

    runs = 20
    prefixes = ('a', 'b', 'c', 'd')

    def incrementer_coroutine(my_prefix):
      for index in xrange(runs):
        my_puzzle = model.Puzzle.get_by_id(puzzle_id)
        old_tag = '%s%d' % (my_prefix, index)
        self.assertTrue(my_puzzle.delete_tag(old_tag),
                        "Couldn't delete '%s'" % old_tag)
        yield
        my_puzzle.put()
        yield
        my_puzzle = model.Puzzle.get_by_id(puzzle_id)
        new_tag = '%s%d' % (my_prefix, index + 1)
        self.assertTrue(my_puzzle.add_tag(new_tag),
                        "Couldn't add '%s'" % new_tag)
        yield
        my_puzzle.put()
        yield

    incrementers = []
    puzzle = model.Puzzle.get_by_id(puzzle_id)
    for prefix in prefixes:
      puzzle.add_tag('%s0' % prefix)
      incrementers.append(incrementer_coroutine(prefix))
    puzzle.put()
    my_puzzle = model.Puzzle.get_by_id(puzzle_id)

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
