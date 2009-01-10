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

"""Tests for implementations of Repository.has_revisions."""

from bzrlib.revision import NULL_REVISION
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestHasRevisions(TestCaseWithRepository):

    def test_empty_list(self):
        repo = self.make_repository('.')
        self.assertEqual(set(), repo.has_revisions([]))

    def test_superset(self):
        tree = self.make_branch_and_tree('.')
        repo = tree.branch.repository
        rev1 = tree.commit('1')
        rev2 = tree.commit('2')
        rev3 = tree.commit('3')
        self.assertEqual(set([rev1, rev3]),
            repo.has_revisions([rev1, rev3, 'foobar:']))

    def test_NULL(self):
        # NULL_REVISION is always present. So for
        # compatibility with 'has_revision' we make this work.
        repo = self.make_repository('.')
        self.assertEqual(set([NULL_REVISION]),
            repo.has_revisions([NULL_REVISION]))
