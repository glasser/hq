# Copyright (C) 2007 Canonical Ltd
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


"""Tests for the switch command of bzr."""

import os

from bzrlib.workingtree import WorkingTree
from bzrlib.tests.blackbox import ExternalBase


class TestSwitch(ExternalBase):

    def test_switch_up_to_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('branch branch branch2')
        self.run_bzr('checkout --lightweight branch checkout')
        os.chdir('checkout')
        out, err = self.run_bzr('switch ../branch2')
        self.assertContainsRe(err, 'Tree is up to date at revision 0.\n')
        self.assertContainsRe(err, 'Switched to branch: .*/branch2.\n')
        self.assertEqual('', out)

    def test_switch_out_of_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('branch branch branch2')
        self.build_tree(['branch2/file'])
        self.run_bzr('add branch2/file')
        self.run_bzr('commit -m add-file branch2')
        self.run_bzr('checkout --lightweight branch checkout')
        os.chdir('checkout')
        out, err = self.run_bzr('switch ../branch2')
        #self.assertContainsRe(err, '\+N  file')
        self.assertContainsRe(err, 'Updated to revision 1.\n')
        self.assertContainsRe(err, 'Switched to branch: .*/branch2.\n')
        self.assertEqual('', out)

    def _test_switch_nick(self, lightweight):
        """Check that the nick gets switched too."""
        tree1 = self.make_branch_and_tree('branch1')
        tree2 = self.make_branch_and_tree('branch2')
        tree2.pull(tree1.branch)
        checkout =  tree1.branch.create_checkout('checkout',
            lightweight=lightweight)
        self.assertEqual(checkout.branch.nick, tree1.branch.nick)
        self.assertEqual(checkout.branch.get_config().has_explicit_nickname(),
            False)
        self.run_bzr('switch branch2', working_dir='checkout')

        # we need to get the tree again, otherwise we don't get the new branch
        checkout = WorkingTree.open('checkout')
        self.assertEqual(checkout.branch.nick, tree2.branch.nick)
        self.assertEqual(checkout.branch.get_config().has_explicit_nickname(),
            False)

    def test_switch_nick(self):
        self._test_switch_nick(lightweight=False)

    def test_switch_nick_lightweight(self):
        self._test_switch_nick(lightweight=True)

    def _test_switch_explicit_nick(self, lightweight):
        """Check that the nick gets switched too."""
        tree1 = self.make_branch_and_tree('branch1')
        tree2 = self.make_branch_and_tree('branch2')
        tree2.pull(tree1.branch)
        checkout =  tree1.branch.create_checkout('checkout',
            lightweight=lightweight)
        self.assertEqual(checkout.branch.nick, tree1.branch.nick)
        checkout.branch.nick = "explicit_nick"
        self.assertEqual(checkout.branch.nick, "explicit_nick")
        self.assertEqual(checkout.branch.get_config()._get_explicit_nickname(),
            "explicit_nick")
        self.run_bzr('switch branch2', working_dir='checkout')

        # we need to get the tree again, otherwise we don't get the new branch
        checkout = WorkingTree.open('checkout')
        self.assertEqual(checkout.branch.nick, tree2.branch.nick)
        self.assertEqual(checkout.branch.get_config()._get_explicit_nickname(),
            tree2.branch.nick)

    def test_switch_explicit_nick(self):
        self._test_switch_explicit_nick(lightweight=False)

    def test_switch_explicit_nick_lightweight(self):
        self._test_switch_explicit_nick(lightweight=True)

    def test_switch_finds_relative_branch(self):
        """Switch will find 'foo' relative to the branch the checkout is of."""
        self.build_tree(['repo/'])
        tree1 = self.make_branch_and_tree('repo/brancha')
        tree1.commit('foo')
        tree2 = self.make_branch_and_tree('repo/branchb')
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit('bar')
        checkout =  tree1.branch.create_checkout('checkout', lightweight=True)
        self.run_bzr(['switch', 'branchb'], working_dir='checkout')
        self.assertEqual(branchb_id, checkout.last_revision())
        checkout = checkout.bzrdir.open_workingtree()
        self.assertEqual(tree2.branch.base, checkout.branch.base)

    def test_switch_finds_relative_bound_branch(self):
        """Using switch on a heavy checkout should find master sibling

        The behaviour of lighweight and heavy checkouts should be 
        consistentwhen using the convenient "switch to sibling" feature
        Both should switch to a sibling of the branch
        they are bound to, and not a sibling of themself"""

        self.build_tree(['repo/',
                         'heavyco/'])
        tree1 = self.make_branch_and_tree('repo/brancha')
        tree1.commit('foo')
        tree2 = self.make_branch_and_tree('repo/branchb')
        tree2.pull(tree1.branch)
        branchb_id = tree2.commit('bar')
        checkout = tree1.branch.create_checkout('heavyco/a', lightweight=False)
        self.run_bzr(['switch', 'branchb'], working_dir='heavyco/a')
        self.assertEqual(branchb_id, checkout.last_revision())
        self.assertEqual(tree2.branch.base, checkout.branch.get_bound_location())
