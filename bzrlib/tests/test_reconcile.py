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

"""Tests for reconiliation behaviour that is repository independent."""


from bzrlib import bzrdir, errors, tests
from bzrlib.reconcile import reconcile, Reconciler
from bzrlib.revision import Revision
from bzrlib.tests.per_repository import TestCaseWithRepository
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree


class TestWorksWithSharedRepositories(TestCaseWithRepository):

    def test_reweave_empty(self):
        # we want a repo capable format
        parent = bzrdir.BzrDirMetaFormat1().initialize('.')
        parent.create_repository(shared=True)
        parent.root_transport.mkdir('child')
        child = bzrdir.BzrDirMetaFormat1().initialize('child')
        self.assertRaises(errors.NoRepositoryPresent, child.open_repository)
        reconciler = Reconciler(child)
        reconciler.reconcile()
        # smoke test for reconcile appears to work too.
        reconcile(child)
        # no inconsistent parents should have been found
        # but the values should have been set.
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)


class TestReconciler(tests.TestCaseWithTransport):
    
    def test_reconciler_with_no_branch(self):
        repo = self.make_repository('repo')
        reconciler = Reconciler(repo.bzrdir)
        reconciler.reconcile()
        # no inconsistent parents should have been found
        # but the values should have been set.
        self.assertEqual(0, reconciler.inconsistent_parents)
        # and no garbage inventories
        self.assertEqual(0, reconciler.garbage_inventories)
        self.assertIs(None, reconciler.fixed_branch_history)

    def test_reconciler_finds_branch(self):
        a_branch = self.make_branch('a_branch')
        reconciler = Reconciler(a_branch.bzrdir)
        reconciler.reconcile()

        # It should have checked the repository, and the branch
        self.assertEqual(0, reconciler.inconsistent_parents)
        self.assertEqual(0, reconciler.garbage_inventories)
        self.assertIs(False, reconciler.fixed_branch_history)
