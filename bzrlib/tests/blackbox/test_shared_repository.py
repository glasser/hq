# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Black-box tests for repositories with shared branches"""

import os

from bzrlib.bzrdir import BzrDir
import bzrlib.errors as errors
from bzrlib.tests import TestCaseInTempDir

class TestSharedRepo(TestCaseInTempDir):

    def test_make_repository(self):
        out, err = self.run_bzr("init-repository a")
        self.assertEqual(out,
"""Shared repository with trees (format: pack-0.92)
Location:
  shared repository: a
""")
        self.assertEqual(err, "")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)

    def test_make_repository_quiet(self):
        out, err = self.run_bzr("init-repository a -q")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)

    def test_init_repo_existing_dir(self):
        """Make repo in existing directory.
        
        (Malone #38331)
        """
        out, err = self.run_bzr("init-repository .")
        dir = BzrDir.open('.')
        self.assertTrue(dir.open_repository())

    def test_init(self):
        self.run_bzr("init-repo a")
        self.run_bzr("init --format=default a/b")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)
        bdir = BzrDir.open('a/b')
        bdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, bdir.open_repository)
        wt = bdir.open_workingtree()

    def test_branch(self):
        self.run_bzr("init-repo a")
        self.run_bzr("init --format=default a/b")
        self.run_bzr('branch a/b a/c')
        cdir = BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        cdir.open_workingtree()

    def test_branch_tree(self):
        self.run_bzr("init-repo --trees a")
        self.run_bzr("init --format=default b")
        file('b/hello', 'wt').write('bar')
        self.run_bzr("add b/hello")
        self.run_bzr("commit -m bar b/hello")

        self.run_bzr('branch b a/c')
        cdir = BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        self.failUnlessExists('a/c/hello')
        cdir.open_workingtree()

    def test_trees_default(self):
        # 0.15 switched to trees by default
        self.run_bzr("init-repo repo")
        repo = BzrDir.open("repo").open_repository()
        self.assertEqual(True, repo.make_working_trees())

    def test_trees_argument(self):
        # Supplying the --trees argument should be harmless,
        # as it was previously non-default we need to get it right.
        self.run_bzr("init-repo --trees trees")
        repo = BzrDir.open("trees").open_repository()
        self.assertEqual(True, repo.make_working_trees())

    def test_no_trees_argument(self):
        # --no-trees should make it so that there is no working tree
        self.run_bzr("init-repo --no-trees notrees")
        repo = BzrDir.open("notrees").open_repository()
        self.assertEqual(False, repo.make_working_trees())
