# Copyright (C) 2006 Canonical Ltd
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

import os

from bzrlib import (
    conflicts
    )
from bzrlib.workingtree import WorkingTree
from bzrlib.tests.blackbox import ExternalBase

# FIXME: These don't really look at the output of the conflict commands, just
# the number of lines - there should be more examination.

class TestConflicts(ExternalBase):

    def setUp(self):
        super(ExternalBase, self).setUp()
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([
            ('a/myfile', 'contentsa\n'),
            ('a/my_other_file', 'contentsa\n'),
            ('a/mydir/',),
            ])
        a_tree.add('myfile')
        a_tree.add('my_other_file')
        a_tree.add('mydir')
        a_tree.commit(message="new")
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([
            ('b/myfile', 'contentsb\n'),
            ('b/my_other_file', 'contentsb\n'),
            ])
        b_tree.rename_one('mydir', 'mydir2')
        b_tree.commit(message="change")
        self.build_tree_contents([
            ('a/myfile', 'contentsa2\n'),
            ('a/my_other_file', 'contentsa2\n'),
            ])
        a_tree.rename_one('mydir', 'mydir3')
        a_tree.commit(message='change')
        a_tree.merge_from_branch(b_tree.branch)
        os.chdir('a')

    def test_conflicts(self):
        conflicts, errs = self.run_bzr('conflicts')
        self.assertEqual(3, len(conflicts.splitlines()))

    def test_conflicts_text(self):
        conflicts = self.run_bzr('conflicts --text')[0].splitlines()
        self.assertEqual(['my_other_file', 'myfile'], conflicts)

    def test_resolve(self):
        self.run_bzr('resolve myfile')
        conflicts, errs = self.run_bzr('conflicts')
        self.assertEqual(2, len(conflicts.splitlines()))
        self.run_bzr('resolve my_other_file')
        self.run_bzr('resolve mydir2')
        conflicts, errs = self.run_bzr('conflicts')
        self.assertEqual(len(conflicts.splitlines()), 0)

    def test_resolve_all(self):
        self.run_bzr('resolve --all')
        conflicts, errs = self.run_bzr('conflicts')
        self.assertEqual(len(conflicts.splitlines()), 0)

    def test_resolve_in_subdir(self):
        """resolve when run from subdirectory should handle relative paths"""
        orig_dir = os.getcwdu()
        try:
            os.mkdir("subdir")
            os.chdir("subdir")
            self.run_bzr("resolve ../myfile")
            os.chdir("../../b")
            self.run_bzr("resolve ../a/myfile")
            wt = WorkingTree.open_containing('.')[0]
            conflicts = wt.conflicts()
            if not conflicts.is_empty():
                self.fail("tree still contains conflicts: %r" % conflicts)
        finally:
            os.chdir(orig_dir)

    def test_auto_resolve(self):
        """Text conflicts can be resolved automatically"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file',
            '<<<<<<<\na\n=======\n>>>>>>>\n')])
        tree.add('file', 'file_id')
        self.assertEqual(tree.kind('file_id'), 'file')
        file_conflict = conflicts.TextConflict('file', file_id='file_id')
        tree.set_conflicts(conflicts.ConflictList([file_conflict]))
        os.chdir('tree')
        note = self.run_bzr('resolve', retcode=1)[1]
        self.assertContainsRe(note, '0 conflict\\(s\\) auto-resolved.')
        self.assertContainsRe(note,
            'Remaining conflicts:\nText conflict in file')
        self.build_tree_contents([('file', 'a\n')])
        note = self.run_bzr('resolve')[1]
        self.assertContainsRe(note, 'All conflicts resolved.')
