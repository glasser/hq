#!/usr/bin/env python2.5
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
