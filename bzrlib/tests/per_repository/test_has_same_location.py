# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Tests for implementations of Repository.has_same_location."""

from bzrlib import bzrdir
from bzrlib.tests import (
    TestNotApplicable,
    )
from bzrlib.tests.per_repository import TestCaseWithRepository
from bzrlib.transport import get_transport


class TestHasSameLocation(TestCaseWithRepository):
    """Tests for Repository.has_same_location method."""

    def assertSameRepo(self, a, b):
        """Asserts that two objects are the same repository.

        This method does the comparison both ways (`a.has_same_location(b)` as
        well as `b.has_same_location(a)`) to make sure both objects'
        `has_same_location` methods give the same results.
        """
        self.assertTrue(a.has_same_location(b),
                        "%r is not the same repository as %r" % (a, b))
        self.assertTrue(b.has_same_location(a),
                        "%r is the same as %r, but not vice versa" % (a, b))

    def assertDifferentRepo(self, a, b):
        """Asserts that two objects are the not same repository.

        This method does the comparison both ways (`a.has_same_location(b)` as
        well as `b.has_same_location(a)`) to make sure both objects'
        `has_same_location` methods give the same results.

        :seealso: assertDifferentRepo
        """
        self.assertFalse(a.has_same_location(b),
                         "%r is not the same repository as %r" % (a, b))
        self.assertFalse(b.has_same_location(a),
                         "%r is the same as %r, but not vice versa" % (a, b))

    def test_same_repo_instance(self):
        """A repository object is the same repository as itself."""
        repo = self.make_repository('.')
        self.assertSameRepo(repo, repo)

    def test_same_repo_location(self):
        """Different repository objects for the same location are the same."""
        repo = self.make_repository('.')
        reopened_repo = repo.bzrdir.open_repository()
        self.failIf(
            repo is reopened_repo,
            "This test depends on reopened_repo being a different instance of "
            "the same repo.")
        self.assertSameRepo(repo, reopened_repo)

    def test_different_repos_not_equal(self):
        """Repositories at different locations are not the same."""
        repo_one = self.make_repository('one')
        repo_two = self.make_repository('two')
        self.assertDifferentRepo(repo_one, repo_two)

    def test_same_bzrdir_different_control_files_not_equal(self):
        """Repositories in the same bzrdir, but with different control files,
        are not the same.

        This can happens e.g. when upgrading a repository.  This test mimics how
        CopyConverter creates a second repository in one bzrdir.
        """
        repo = self.make_repository('repo')
        try:
            control_transport = repo._transport
        except AttributeError:
            raise TestNotApplicable(
                "%r has no transport" % (repo,))
        if control_transport.base == repo.bzrdir.transport.base:
            raise TestNotApplicable(
                "%r has repository files directly in the bzrdir"
                % (repo,))
            # This test only applies to repository formats where the repo
            # control_files are separate from other bzrdir files, i.e. metadir
            # formats.
        control_transport.copy_tree('.', '../repository.backup')
        backup_transport = control_transport.clone('../repository.backup')
        backup_repo = repo._format.open(repo.bzrdir, _found=True,
                                        _override_transport=backup_transport)
        self.assertDifferentRepo(repo, backup_repo)

    def test_different_format_not_equal(self):
        """Different format repositories are comparable and not the same.

        Comparing different format repository objects should give a negative
        result, rather than trigger an exception (which could happen with a
        naive __eq__ implementation, e.g. due to missing attributes).
        """
        repo = self.make_repository('repo')
        other_repo = self.make_repository('other', format='default')
        if repo._format == other_repo._format:
            # We're testing the default format!  So we have to use a non-default
            # format for other_repo.
            get_transport(self.get_vfs_only_url()).delete_tree('other')
            other_repo = self.make_repository('other', format='metaweave')
        # Make sure the other_repo is not a RemoteRepository.
        other_bzrdir = bzrdir.BzrDir.open(self.get_vfs_only_url('other'))
        other_repo = other_bzrdir.open_repository()
        self.assertDifferentRepo(repo, other_repo)


