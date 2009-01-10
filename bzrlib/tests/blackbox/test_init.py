# Copyright (C) 2006, 2007 Canonical Ltd
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


"""Test "bzr init"""

import os
import re

from bzrlib import (
    branch as _mod_branch,
    )
from bzrlib.bzrdir import BzrDirMetaFormat1
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.workingtree import WorkingTree


class TestInit(ExternalBase):

    def test_init_with_format(self):
        # Verify bzr init --format constructs something plausible
        t = self.get_transport()
        self.run_bzr('init --format default')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)

    def test_init_weave(self):
        # --format=weave should be accepted to allow interoperation with
        # old releases when desired.
        out, err = self.run_bzr('init --format=weave')
        self.assertEqual("""Standalone tree (format: weave)
Location:
  branch root: .
""", out)
        self.assertEqual('', err)

    def test_init_at_repository_root(self):
        # bzr init at the root of a repository should create a branch
        # and working tree even when creation of working trees is disabled.
        t = self.get_transport()
        t.mkdir('repo')
        format = BzrDirMetaFormat1()
        newdir = format.initialize(t.abspath('repo'))
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(False)
        out, err = self.run_bzr('init repo')
        self.assertEqual(
"""Repository tree (format: pack-0.92)
Location:
  shared repository: repo
  repository branch: repo
""", out)
        self.assertEqual('', err)
        newdir.open_branch()
        newdir.open_workingtree()
        
    def test_init_branch(self):
        out, err = self.run_bzr('init')
        self.assertEqual(
"""Standalone tree (format: pack-0.92)
Location:
  branch root: .
""", out)
        self.assertEqual('', err)

        # Can it handle subdirectories of branches too ?
        out, err = self.run_bzr('init subdir1')
        self.assertEqual(
"""Standalone tree (format: pack-0.92)
Location:
  branch root: subdir1
""", out)
        self.assertEqual('', err)
        WorkingTree.open('subdir1')
        
        self.run_bzr_error(['Parent directory of subdir2/nothere does not exist'],
                            'init subdir2/nothere')
        out, err = self.run_bzr('init subdir2/nothere', retcode=3)
        self.assertEqual('', out)
        
        os.mkdir('subdir2')
        out, err = self.run_bzr('init subdir2')
        self.assertEqual("""Standalone tree (format: pack-0.92)
Location:
  branch root: subdir2
""", out)
        self.assertEqual('', err)
        # init an existing branch.
        out, err = self.run_bzr('init subdir2', retcode=3)
        self.assertEqual('', out)
        self.failUnless(err.startswith('bzr: ERROR: Already a branch:'))

    def test_init_branch_quiet(self):
        out, err = self.run_bzr('init -q')
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_init_existing_branch(self):
        self.run_bzr('init')
        out, err = self.run_bzr('init', retcode=3)
        self.assertContainsRe(err, 'Already a branch')
        # don't suggest making a checkout, there's already a working tree
        self.assertFalse(re.search(r'checkout', err))

    def test_init_existing_without_workingtree(self):
        # make a repository
        repo = self.make_repository('.', shared=True)
        repo.set_make_working_trees(False)
        # make a branch; by default without a working tree
        self.run_bzr('init subdir')
        # fail
        out, err = self.run_bzr('init subdir', retcode=3)
        # suggests using checkout
        self.assertContainsRe(err,
                              'ontains a branch.*but no working tree.*checkout')

    def test_no_defaults(self):
        """Init creates no default ignore rules."""
        self.run_bzr('init')
        self.assertFalse(os.path.exists('.bzrignore'))

    def test_init_unicode(self):
        # Make sure getcwd can handle unicode filenames
        try:
            os.mkdir(u'mu-\xb5')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")
        # try to init unicode dir
        self.run_bzr(['init', '-q', u'mu-\xb5'])

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        tree.commit('one', rev_id='r1')
        return tree

    def test_init_create_prefix(self):
        """'bzr init --create-prefix; will create leading directories."""
        tree = self.create_simple_tree()

        self.run_bzr_error(['Parent directory of ../new/tree does not exist'],
                            'init ../new/tree', working_dir='tree')
        self.run_bzr('init ../new/tree --create-prefix', working_dir='tree')
        self.failUnlessExists('new/tree/.bzr')


class TestSFTPInit(TestCaseWithSFTPServer):

    def test_init(self):
        # init on a remote url should succeed.
        out, err = self.run_bzr(['init', self.get_url()])
        self.assertStartsWith(out, """Standalone branch (format: pack-0.92)
Location:
  branch root: """)
        self.assertEqual('', err)
    
    def test_init_existing_branch(self):
        # when there is already a branch present, make mention
        self.make_branch('.')

        # rely on SFTPServer get_url() pointing at '.'
        out, err = self.run_bzr_error(['Already a branch'],
                                      ['init', self.get_url()])

        # make sure using 'bzr checkout' is not suggested
        # for remote locations missing a working tree
        self.assertFalse(re.search(r'use bzr checkout', err))

    def test_init_existing_branch_with_workingtree(self):
        # don't distinguish between the branch having a working tree or not
        # when the branch itself is remote.
        self.make_branch_and_tree('.')

        # rely on SFTPServer get_url() pointing at '.'
        self.run_bzr_error(['Already a branch'], ['init', self.get_url()])

    def test_init_append_revisions_only(self):
        self.run_bzr('init --dirstate-tags normal_branch6')
        branch = _mod_branch.Branch.open('normal_branch6')
        self.assertEqual(False, branch._get_append_revisions_only())
        self.run_bzr('init --append-revisions-only --dirstate-tags branch6')
        branch = _mod_branch.Branch.open('branch6')
        self.assertEqual(True, branch._get_append_revisions_only())
        self.run_bzr_error(['cannot be set to append-revisions-only'],
                           'init --append-revisions-only --knit knit')
