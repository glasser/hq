# Copyright (C) 2005, 2006 Canonical Ltd
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

"""Tests for the 'checkout' CLI command."""

from cStringIO import StringIO
import os
import re
import shutil
import sys

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    errors,
    workingtree,
    )
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import HardlinkFeature


class TestCheckout(ExternalBase):
    
    def setUp(self):
        super(TestCheckout, self).setUp()
        tree = bzrdir.BzrDir.create_standalone_workingtree('branch')
        tree.commit('1', rev_id='1', allow_pointless=True)
        self.build_tree(['branch/added_in_2'])
        tree.add('added_in_2')
        tree.commit('2', rev_id='2')

    def test_checkout_makes_bound_branch(self):
        self.run_bzr('checkout branch checkout')
        # if we have a checkout, the branch base should be 'branch'
        source = bzrdir.BzrDir.open('branch')
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(source.open_branch().bzrdir.root_transport.base,
                         result.open_branch().get_bound_location())

    def test_checkout_light_makes_checkout(self):
        self.run_bzr('checkout --lightweight branch checkout')
        # if we have a checkout, the branch base should be 'branch'
        source = bzrdir.BzrDir.open('branch')
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(source.open_branch().bzrdir.root_transport.base,
                         result.open_branch().bzrdir.root_transport.base)

    def test_checkout_dash_r(self):
        self.run_bzr('checkout -r -2 branch checkout')
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(['1'], result.open_workingtree().get_parent_ids())
        self.failIfExists('checkout/added_in_2')

    def test_checkout_light_dash_r(self):
        self.run_bzr('checkout --lightweight -r -2 branch checkout')
        # the working tree should now be at revision '1' with the content
        # from 1.
        result = bzrdir.BzrDir.open('checkout')
        self.assertEqual(['1'], result.open_workingtree().get_parent_ids())
        self.failIfExists('checkout/added_in_2')

    def test_checkout_reconstitutes_working_trees(self):
        # doing a 'bzr checkout' in the directory of a branch with no tree
        # or a 'bzr checkout path' with path the name of a directory with
        # a branch with no tree will reconsistute the tree.
        os.mkdir('treeless-branch')
        branch = bzrdir.BzrDir.create_branch_convenience(
            'treeless-branch',
            force_new_tree=False,
            format=bzrdir.BzrDirMetaFormat1())
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.bzrdir.open_workingtree)
        out, err = self.run_bzr('checkout treeless-branch')
        # we should have a tree now
        branch.bzrdir.open_workingtree()
        # with no diff
        out, err = self.run_bzr('diff treeless-branch')

        # now test with no parameters
        branch = bzrdir.BzrDir.create_branch_convenience(
            '.',
            force_new_tree=False,
            format=bzrdir.BzrDirMetaFormat1())
        # check no tree was created
        self.assertRaises(errors.NoWorkingTree, branch.bzrdir.open_workingtree)
        out, err = self.run_bzr('checkout')
        # we should have a tree now
        branch.bzrdir.open_workingtree()
        # with no diff
        out, err = self.run_bzr('diff')

    def _test_checkout_existing_dir(self, lightweight):
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', 'content1'),
                                  ('source/file2', 'content2'),])
        source.add(['file1', 'file2'])
        source.commit('added files')
        self.build_tree_contents([('target/', ''),
                                  ('target/file1', 'content1'),
                                  ('target/file2', 'content3'),])
        cmd = ['checkout', 'source', 'target']
        if lightweight:
            cmd.append('--lightweight')
        self.run_bzr('checkout source target')
        # files with unique content should be moved
        self.failUnlessExists('target/file2.moved')
        # files with content matching tree should not be moved
        self.failIfExists('target/file1.moved')

    def test_checkout_existing_dir_heavy(self):
        self._test_checkout_existing_dir(False)

    def test_checkout_existing_dir_lightweight(self):
        self._test_checkout_existing_dir(True)

    def test_checkout_in_branch_with_r(self):
        branch = _mod_branch.Branch.open('branch')
        branch.bzrdir.destroy_workingtree()
        os.chdir('branch')
        self.run_bzr('checkout -r 1')
        tree = workingtree.WorkingTree.open('.')
        self.assertEqual('1', tree.last_revision())
        branch.bzrdir.destroy_workingtree()
        self.run_bzr('checkout -r 0')
        self.assertEqual('null:', tree.last_revision())

    def test_checkout_files_from(self):
        branch = _mod_branch.Branch.open('branch')
        self.run_bzr(['checkout', 'branch', 'branch2', '--files-from',
                      'branch'])

    def test_checkout_hardlink(self):
        self.requireFeature(HardlinkFeature)
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1'])
        source.add('file1')
        source.commit('added file')
        self.run_bzr(['checkout', 'source', 'target', '--files-from', 'source',
                      '--hardlink'])
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)
