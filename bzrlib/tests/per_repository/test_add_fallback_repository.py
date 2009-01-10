# Copyright (C) 2008 Canonical Ltd
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

"""Tests for Repository.add_fallback_repository."""

from bzrlib import errors
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestAddFallbackRepository(TestCaseWithRepository):

    def test_add_fallback_repository(self):
        repo = self.make_repository('repo')
        tree = self.make_branch_and_tree('branch')
        if not repo._format.supports_external_lookups:
            self.assertRaises(errors.UnstackableRepositoryFormat,
                repo.add_fallback_repository, tree.branch.repository)
            raise TestNotApplicable
        repo.add_fallback_repository(tree.branch.repository)
        # the repository has been added correctly if we can query against it.
        revision_id = tree.commit('1st post')
        repo.lock_read()
        self.addCleanup(repo.unlock)
        # can see all revisions
        self.assertEqual(set([revision_id]), set(repo.all_revision_ids()))
        # and can also query the parent map, either on the revisions
        # versionedfiles, which works in tuple keys...
        self.assertEqual({(revision_id,): ()},
            repo.revisions.get_parent_map([(revision_id,)]))
        # ... or on the repository directly...
        self.assertEqual({revision_id: (NULL_REVISION,)},
            repo.get_parent_map([revision_id]))

    def test_add_fallback_sets_fetch_order(self):
        repo = self.make_repository('repo')
        tree = self.make_branch_and_tree('branch')
        if not repo._format.supports_external_lookups:
            self.assertRaises(errors.UnstackableRepositoryFormat,
                repo.add_fallback_repository, tree.branch.repository)
            raise TestNotApplicable
        repo.add_fallback_repository(tree.branch.repository)
        self.assertEqual('topological', repo._fetch_order)
