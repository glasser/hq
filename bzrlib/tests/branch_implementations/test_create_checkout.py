# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the Branch.create_checkout"""

from bzrlib import (
    branch,
    )
from bzrlib.remote import RemoteBranch
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch


class TestCreateCheckout(TestCaseWithBranch):

    def test_checkout_format(self):
        """Make sure the new checkout uses the desired branch format."""
        a_branch = self.make_branch('branch')
        tree = a_branch.create_checkout('checkout')
        # All branches can define the format they want checkouts made in.
        # This checks it is honoured.
        expected_format = a_branch._get_checkout_format().get_branch_format()
        self.assertEqual(expected_format.__class__,
                         tree.branch._format.__class__)

    def test_create_revision_checkout(self):
        """Test that we can create a checkout from an earlier revision."""
        tree1 = self.make_branch_and_tree('base')
        self.build_tree(['base/a'])
        tree1.add(['a'], ['a-id'])
        tree1.commit('first', rev_id='rev-1')
        self.build_tree(['base/b'])
        tree1.add(['b'], ['b-id'])
        tree1.commit('second', rev_id='rev-2')

        tree2 = tree1.branch.create_checkout('checkout', revision_id='rev-1')
        self.assertEqual('rev-1', tree2.last_revision())
        self.failUnlessExists('checkout/a')
        self.failIfExists('checkout/b')

    def test_create_lightweight_checkout(self):
        """We should be able to make a lightweight checkout."""
        tree1 = self.make_branch_and_tree('base')
        tree2 = tree1.branch.create_checkout('checkout', lightweight=True)
        self.assertNotEqual(tree1.basedir, tree2.basedir)
        self.assertEqual(tree1.branch.base, tree2.branch.base)

    def test_create_checkout_exists(self):
        """We shouldn't fail if the directory already exists."""
        tree1 = self.make_branch_and_tree('base')
        self.build_tree(['checkout/'])
        tree2 = tree1.branch.create_checkout('checkout', lightweight=True)
