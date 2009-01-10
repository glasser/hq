# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""


import os

from bzrlib.branch import Branch
from bzrlib.config import extract_email_address
from bzrlib.tests import TestCaseWithTransport


class TestAnnotate(TestCaseWithTransport):

    def setUp(self):
        super(TestAnnotate, self).setUp()
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree_contents([('hello.txt', 'my helicopter\n'),
                                  ('nomail.txt', 'nomail\n')])
        wt.add(['hello.txt'])
        self.revision_id_1 = wt.commit('add hello',
                              committer='test@user',
                              timestamp=1165960000.00, timezone=0)
        wt.add(['nomail.txt'])
        self.revision_id_2 = wt.commit('add nomail',
                              committer='no mail',
                              timestamp=1165970000.00, timezone=0)
        self.build_tree_contents([('hello.txt', 'my helicopter\n'
                                                'your helicopter\n')])
        self.revision_id_3 = wt.commit('mod hello',
                              committer='user@test',
                              timestamp=1166040000.00, timezone=0)
        self.build_tree_contents([('hello.txt', 'my helicopter\n'
                                                'your helicopter\n'
                                                'all of\n'
                                                'our helicopters\n'
                                  )])
        self.revision_id_4 = wt.commit('mod hello',
                              committer='user@test',
                              timestamp=1166050000.00, timezone=0)

    def test_help_annotate(self):
        """Annotate command exists"""
        out, err = self.run_bzr('--no-plugins annotate --help')

    def test_annotate_cmd(self):
        out, err = self.run_bzr('annotate hello.txt')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
3   user@te | your helicopter
4   user@te | all of
            | our helicopters
''', out)

    def test_annotate_cmd_full(self):
        out, err = self.run_bzr('annotate hello.txt --all')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
3   user@te | your helicopter
4   user@te | all of
4   user@te | our helicopters
''', out)

    def test_annotate_cmd_long(self):
        out, err = self.run_bzr('annotate hello.txt --long')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@user 20061212 | my helicopter
3   user@test 20061213 | your helicopter
4   user@test 20061213 | all of
                       | our helicopters
''', out)

    def test_annotate_cmd_show_ids(self):
        out, err = self.run_bzr('annotate hello.txt --show-ids')
        max_len = max([len(self.revision_id_1),
                       len(self.revision_id_3),
                       len(self.revision_id_4)])
        self.assertEqual('', err)
        self.assertEqualDiff('''\
%*s | my helicopter
%*s | your helicopter
%*s | all of
%*s | our helicopters
''' % (max_len, self.revision_id_1,
       max_len, self.revision_id_3,
       max_len, self.revision_id_4,
       max_len, '',
      )
, out)

    def test_no_mail(self):
        out, err = self.run_bzr('annotate nomail.txt')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
2   no mail | nomail
''', out)

    def test_annotate_cmd_revision(self):
        out, err = self.run_bzr('annotate hello.txt -r1')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
''', out)

    def test_annotate_cmd_revision3(self):
        out, err = self.run_bzr('annotate hello.txt -r3')
        self.assertEqual('', err)
        self.assertEqualDiff('''\
1   test@us | my helicopter
3   user@te | your helicopter
''', out)

    def test_annotate_cmd_unknown_revision(self):
        out, err = self.run_bzr('annotate hello.txt -r 10',
                                retcode=3)
        self.assertEqual('', out)
        self.assertContainsRe(err, 'Requested revision: \'10\' does not exist')

    def test_annotate_cmd_two_revisions(self):
        out, err = self.run_bzr('annotate hello.txt -r1..2',
                                retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: bzr annotate --revision takes'
                         ' exactly one revision identifier\n',
                         err)


class TestSimpleAnnotate(TestCaseWithTransport):
    """Annotate tests with no complex setup."""

    def _setup_edited_file(self):
        """Create a tree with a locally edited file."""
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('file', 'foo\ngam\n')])
        tree.add('file')
        tree.commit('add file', committer="test@host", rev_id="rev1")
        self.build_tree_contents([('file', 'foo\nbar\ngam\n')])
        tree.branch.get_config().set_user_option('email', 'current@host2')

    def test_annotate_edited_file(self):
        tree = self._setup_edited_file()
        out, err = self.run_bzr('annotate file')
        self.assertEqual(
            '1   test@ho | foo\n'
            '2?  current | bar\n'
            '1   test@ho | gam\n',
            out)

    def test_annotate_edited_file_show_ids(self):
        tree = self._setup_edited_file()
        out, err = self.run_bzr('annotate file --show-ids')
        self.assertEqual(
            '    rev1 | foo\n'
            'current: | bar\n'
            '    rev1 | gam\n',
            out)

    def _create_merged_file(self):
        """Create a file with a pending merge and local edit."""
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('file', 'foo\ngam\n')])
        tree.add('file')
        tree.commit('add file', rev_id="rev1", committer="test@host")
        # right side
        self.build_tree_contents([('file', 'foo\nbar\ngam\n')])
        tree.commit("right", rev_id="rev1.1.1", committer="test@host")
        tree.pull(tree.branch, True, "rev1")
        # left side
        self.build_tree_contents([('file', 'foo\nbaz\ngam\n')])
        tree.commit("left", rev_id="rev2", committer="test@host")
        # merge
        tree.merge_from_branch(tree.branch, "rev1.1.1")
        # edit the file to be 'resolved' and have a further local edit
        self.build_tree_contents([('file', 'local\nfoo\nbar\nbaz\ngam\n')])

    def test_annotated_edited_merged_file_revnos(self):
        self._create_merged_file()
        out, err = self.run_bzr('annotate file')
        email = extract_email_address(Branch.open('.').get_config().username())
        self.assertEqual(
            '3?    %-7s | local\n'
            '1     test@ho | foo\n'
            '1.1.1 test@ho | bar\n'
            '2     test@ho | baz\n'
            '1     test@ho | gam\n' % email[:7],
            out)

    def test_annotated_edited_merged_file_ids(self):
        self._create_merged_file()
        out, err = self.run_bzr('annotate file --show-ids')
        self.assertEqual(
            'current: | local\n'
            '    rev1 | foo\n'
            'rev1.1.1 | bar\n'
            '    rev2 | baz\n'
            '    rev1 | gam\n',
            out)

    def test_annotate_empty_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/empty', '')])
        tree.add('empty')
        tree.commit('add empty file')

        os.chdir('tree')
        out, err = self.run_bzr('annotate empty')
        self.assertEqual('', out)

    def test_annotate_nonexistant_file(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add(['file'])
        tree.commit('add a file')

        os.chdir('tree')
        out, err = self.run_bzr("annotate doesnotexist", retcode=3)
        self.assertEqual('', out)
        self.assertEqual("bzr: ERROR: doesnotexist is not versioned.\n", err)

    def test_annotate_without_workingtree(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/empty', '')])
        tree.add('empty')
        tree.commit('add empty file')
        bzrdir = tree.branch.bzrdir
        bzrdir.destroy_workingtree()
        self.assertFalse(bzrdir.has_workingtree())

        os.chdir('branch')
        out, err = self.run_bzr('annotate empty')
        self.assertEqual('', out)
