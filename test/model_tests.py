#!/usr/bin/env python2.5
import threading
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
    puzzle = model.Puzzle(title='Some puzzle',
                          tags=['a0', 'b0'])
    puzzle_id = puzzle.put().id()

    class Incrementer(threading.Thread):
      def __init__(self, puzzle_id, prefix):
        super(Incrementer, self).__init__()
        self.puzzle_id = puzzle_id
        self.prefix = prefix
        self.failed = False

      def run(self):
        for index in xrange(500):
          my_puzzle = model.Puzzle.get_by_id(self.puzzle_id)
          if not my_puzzle.delete_tag('%s%d' % (self.prefix, index)):
            self.failed = True
          my_puzzle.put()
          my_puzzle = model.Puzzle.get_by_id(self.puzzle_id)
          if not my_puzzle.add_tag('%s%d' % (self.prefix, index + 1)):
            self.failed = True
          my_puzzle.put()

    a_incrementer = Incrementer(puzzle_id, 'a')
    b_incrementer = Incrementer(puzzle_id, 'b')
    a_incrementer.start()
    b_incrementer.start()
    a_incrementer.join()
    b_incrementer.join()
    self.assertFalse(a_incrementer.failed)
    self.assertFalse(b_incrementer.failed)
