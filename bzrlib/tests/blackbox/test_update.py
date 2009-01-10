# Copyright (C) 2006 Canonical Ltd
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


"""Tests for the update command of bzr."""

import os

from bzrlib import branch, bzrdir
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestUpdate(ExternalBase):

    def test_update_standalone_trivial(self):
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('update')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_standalone_trivial_with_alias_up(self):
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('up')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('checkout --lightweight branch checkout')
        out, err = self.run_bzr('update checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('checkout branch checkout')
        out, err = self.run_bzr('update checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_out_of_date_standalone_tree(self):
        # FIXME the default format has to change for this to pass
        # because it currently uses the branch last-revision marker.
        self.make_branch_and_tree('branch')
        # make a checkout
        self.run_bzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.run_bzr('add checkout/file')
        self.run_bzr('commit -m add-file checkout')
        # now branch should be out of date
        out,err = self.run_bzr('update branch')
        self.assertEqual('', out)
        self.assertContainsRe(err, '\+N  file')
        self.assertEndsWith(err, 'All changes applied successfully.\n'
                         'Updated to revision 1.\n')
        self.failUnlessExists('branch/file')

    def test_update_out_of_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.run_bzr('checkout --lightweight branch checkout')
        self.run_bzr('checkout --lightweight branch checkout2')
        self.build_tree(['checkout/file'])
        self.run_bzr('add checkout/file')
        self.run_bzr('commit -m add-file checkout')
        # now checkout2 should be out of date
        out,err = self.run_bzr('update checkout2')
        self.assertContainsRe(err, '\+N  file')
        self.assertEndsWith(err, 'All changes applied successfully.\n'
                         'Updated to revision 1.\n')
        self.assertEqual('', out)

    def test_update_conflicts_returns_2(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.run_bzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.run_bzr('add checkout/file')
        self.run_bzr('commit -m add-file checkout')
        self.run_bzr('checkout --lightweight branch checkout2')
        # now alter file in checkout
        a_file = file('checkout/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.run_bzr('commit -m checnge-file checkout')
        # now checkout2 should be out of date
        # make a local change to file
        a_file = file('checkout2/file', 'wt')
        a_file.write('Bar')
        a_file.close()
        out,err = self.run_bzr('update checkout2', retcode=1)
        self.assertContainsRe(err, 'M  file')
        self.assertEqual(['1 conflicts encountered.',
                          'Updated to revision 2.'],
                         err.split('\n')[-3:-1])
        self.assertContainsRe(err, 'Text conflict in file\n')
        self.assertEqual('', out)

    def test_smoke_update_checkout_bound_branch_local_commits(self):
        # smoke test for doing an update of a checkout of a bound
        # branch with local commits.
        master = self.make_branch_and_tree('master')
        # make a bound branch
        self.run_bzr('checkout master child')
        # get an object form of child
        child = WorkingTree.open('child')
        # check that out
        self.run_bzr('checkout --lightweight child checkout')
        # get an object form of the checkout to manipulate
        wt = WorkingTree.open('checkout')
        # change master
        a_file = file('master/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        master.add(['file'])
        master_tip = master.commit('add file')
        # change child
        a_file = file('child/file_b', 'wt')
        a_file.write('Foo')
        a_file.close()
        child.add(['file_b'])
        child_tip = child.commit('add file_b', local=True)
        # check checkout
        a_file = file('checkout/file_c', 'wt')
        a_file.write('Foo')
        a_file.close()
        wt.add(['file_c'])

        # now, update checkout ->
        # get all three files and a pending merge.
        out, err = self.run_bzr('update checkout')
        self.assertEqual('', out)
        self.assertContainsRe(err, '\+N  file')
        self.assertContainsRe(err, '\+N  file_b')
        self.assertContainsRe(err, 'Updated to revision 1.\n'
                                   'Your local commits will now show as'
                                   ' pending merges')
        self.assertEqual([master_tip, child_tip], wt.get_parent_ids())
        self.failUnlessExists('checkout/file')
        self.failUnlessExists('checkout/file_b')
        self.failUnlessExists('checkout/file_c')
        self.assertTrue(wt.has_filename('file_c'))

    def test_update_with_merges(self):
        # Test that 'bzr update' works correctly when you have
        # an update in the master tree, and a lightweight checkout
        # which has merged another branch
        master = self.make_branch_and_tree('master')
        self.build_tree(['master/file'])
        master.add(['file'])
        master.commit('one', rev_id='m1')

        self.build_tree(['checkout1/'])
        checkout_dir = bzrdir.BzrDirMetaFormat1().initialize('checkout1')
        branch.BranchReferenceFormat().initialize(checkout_dir, master.branch)
        checkout1 = checkout_dir.create_workingtree('m1')

        # Create a second branch, with an extra commit
        other = master.bzrdir.sprout('other').open_workingtree()
        self.build_tree(['other/file2'])
        other.add(['file2'])
        other.commit('other2', rev_id='o2')

        # Create a new commit in the master branch
        self.build_tree(['master/file3'])
        master.add(['file3'])
        master.commit('f3', rev_id='m2')

        # Merge the other branch into checkout
        os.chdir('checkout1')
        self.run_bzr('merge ../other')

        self.assertEqual(['o2'], checkout1.get_parent_ids()[1:])

        # At this point, 'commit' should fail, because we are out of date
        self.run_bzr_error(["please run 'bzr update'"],
                           'commit -m merged')

        # This should not report about local commits being pending
        # merges, because they were real merges
        out, err = self.run_bzr('update')
        self.assertEqual('', out)
        self.assertEndsWith(err, 'All changes applied successfully.\n'
                         'Updated to revision 2.\n')
        self.assertContainsRe(err, r'\+N  file3')
        # The pending merges should still be there
        self.assertEqual(['o2'], checkout1.get_parent_ids()[1:])

    def test_readonly_lightweight_update(self):
        """Update a light checkout of a readonly branch"""
        tree = self.make_branch_and_tree('branch')
        readonly_branch = branch.Branch.open(self.get_readonly_url('branch'))
        checkout = readonly_branch.create_checkout('checkout',
                                                   lightweight=True)
        tree.commit('empty commit')
        self.run_bzr('update checkout')
