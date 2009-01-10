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

"""Tests for bzrdir implementations - tests a bzrdir format."""

from cStringIO import StringIO
import errno
from itertools import izip
import os
from stat import S_ISDIR
import sys

import bzrlib.branch
from bzrlib import (
    bzrdir,
    errors,
    lockdir,
    repository,
    revision as _mod_revision,
    transactions,
    transport,
    ui,
    workingtree,
    )
from bzrlib.branch import Branch, needs_read_lock, needs_write_lock
from bzrlib.check import check_branch
from bzrlib.errors import (FileExists,
                           NoSuchRevision,
                           NoSuchFile,
                           UninitializableFormat,
                           NotBranchError,
                           )
import bzrlib.revision
from bzrlib.tests import (
                          ChrootedTestCase,
                          TestCase,
                          TestCaseWithTransport,
                          TestNotApplicable,
                          TestSkipped,
                          )
from bzrlib.tests.bzrdir_implementations import TestCaseWithBzrDir
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.transport.local import LocalTransport
from bzrlib.upgrade import upgrade
from bzrlib.remote import RemoteBzrDir
from bzrlib.repofmt import weaverepo


class TestBzrDir(TestCaseWithBzrDir):
    # Many of these tests test for disk equality rather than checking
    # for semantic equivalence. This works well for some tests but
    # is not good at handling changes in representation or the addition
    # or removal of control data. It would be nice to for instance:
    # sprout a new branch, check that the nickname has been reset by hand
    # and then set the nickname to match the source branch, at which point
    # a semantic equivalence should pass

    def assertDirectoriesEqual(self, source, target, ignore_list=[]):
        """Assert that the content of source and target are identical.

        paths in ignore list will be completely ignored.
        
        We ignore paths that represent data which is allowed to change during
        a clone or sprout: for instance, inventory.knit contains gzip fragements
        which have timestamps in them, and as we have read the inventory from 
        the source knit, the already-read data is recompressed rather than
        reading it again, which leads to changed timestamps. This is ok though,
        because the inventory.kndx file is not ignored, and the integrity of
        knit joins is tested by test_knit and test_versionedfile.

        :seealso: Additionally, assertRepositoryHasSameItems provides value
            rather than representation checking of repositories for
            equivalence.
        """
        files = []
        directories = ['.']
        while directories:
            dir = directories.pop()
            for path in set(source.list_dir(dir) + target.list_dir(dir)):
                path = dir + '/' + path
                if path in ignore_list:
                    continue
                try:
                    stat = source.stat(path)
                except errors.NoSuchFile:
                    self.fail('%s not in source' % path)
                if S_ISDIR(stat.st_mode):
                    self.assertTrue(S_ISDIR(target.stat(path).st_mode))
                    directories.append(path)
                else:
                    self.assertEqualDiff(source.get(path).read(),
                                         target.get(path).read(),
                                         "text for file %r differs:\n" % path)

    def assertRepositoryHasSameItems(self, left_repo, right_repo):
        """require left_repo and right_repo to contain the same data."""
        # XXX: TODO: Doesn't work yet, because we need to be able to compare
        # local repositories to remote ones...  but this is an as-yet unsolved
        # aspect of format management and the Remote protocols...
        # self.assertEqual(left_repo._format.__class__,
        #     right_repo._format.__class__)
        left_repo.lock_read()
        try:
            right_repo.lock_read()
            try:
                # revs
                all_revs = left_repo.all_revision_ids()
                self.assertEqual(left_repo.all_revision_ids(),
                    right_repo.all_revision_ids())
                for rev_id in left_repo.all_revision_ids():
                    self.assertEqual(left_repo.get_revision(rev_id),
                        right_repo.get_revision(rev_id))
                # inventories
                left_inv_weave = left_repo.inventories
                right_inv_weave = right_repo.inventories
                self.assertEqual(set(left_inv_weave.keys()),
                    set(right_inv_weave.keys()))
                # XXX: currently this does not handle indirectly referenced
                # inventories (e.g. where the inventory is a delta basis for
                # one that is fully present but that the revid for that
                # inventory is not yet present.)
                self.assertEqual(set(left_inv_weave.keys()),
                    set(left_repo.revisions.keys()))
                left_trees = left_repo.revision_trees(all_revs)
                right_trees = right_repo.revision_trees(all_revs)
                for left_tree, right_tree in izip(left_trees, right_trees):
                    self.assertEqual(left_tree.inventory, right_tree.inventory)
                # texts
                text_index = left_repo._generate_text_key_index()
                self.assertEqual(text_index,
                    right_repo._generate_text_key_index())
                desired_files = []
                for file_id, revision_id in text_index.iterkeys():
                    desired_files.append(
                        (file_id, revision_id, (file_id, revision_id)))
                left_texts = list(left_repo.iter_files_bytes(desired_files))
                right_texts = list(right_repo.iter_files_bytes(desired_files))
                left_texts.sort()
                right_texts.sort()
                self.assertEqual(left_texts, right_texts)
                # signatures
                for rev_id in all_revs:
                    try:
                        left_text = left_repo.get_signature_text(rev_id)
                    except NoSuchRevision:
                        continue
                    right_text = right_repo.get_signature_text(rev_id)
                    self.assertEqual(left_text, right_text)
            finally:
                right_repo.unlock()
        finally:
            left_repo.unlock()

    def skipIfNoWorkingTree(self, a_bzrdir):
        """Raises TestSkipped if a_bzrdir doesn't have a working tree.
        
        If the bzrdir does have a workingtree, this is a no-op.
        """
        try:
            a_bzrdir.open_workingtree()
        except (errors.NotLocalUrl, errors.NoWorkingTree):
            raise TestSkipped("bzrdir on transport %r has no working tree"
                              % a_bzrdir.transport)

    def createWorkingTreeOrSkip(self, a_bzrdir):
        """Create a working tree on a_bzrdir, or raise TestSkipped.
        
        A simple wrapper for create_workingtree that translates NotLocalUrl into
        TestSkipped.  Returns the newly created working tree.
        """
        try:
            return a_bzrdir.create_workingtree()
        except errors.NotLocalUrl:
            raise TestSkipped("cannot make working tree with transport %r"
                              % a_bzrdir.transport)

    def sproutOrSkip(self, from_bzrdir, to_url, revision_id=None,
                     force_new_repo=False, accelerator_tree=None):
        """Sprout from_bzrdir into to_url, or raise TestSkipped.
        
        A simple wrapper for from_bzrdir.sprout that translates NotLocalUrl into
        TestSkipped.  Returns the newly sprouted bzrdir.
        """
        to_transport = get_transport(to_url)
        if not isinstance(to_transport, LocalTransport):
            raise TestSkipped('Cannot sprout to remote bzrdirs.')
        target = from_bzrdir.sprout(to_url, revision_id=revision_id,
                                    force_new_repo=force_new_repo,
                                    possible_transports=[to_transport],
                                    accelerator_tree=accelerator_tree)
        return target

    def test_create_null_workingtree(self):
        dir = self.make_bzrdir('dir1')
        dir.create_repository()
        dir.create_branch()
        try:
            wt = dir.create_workingtree(revision_id=bzrlib.revision.NULL_REVISION)
        except errors.NotLocalUrl:
            raise TestSkipped("cannot make working tree with transport %r"
                              % dir.transport)
        self.assertEqual([], wt.get_parent_ids())

    def test_destroy_workingtree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        tree.commit('first commit')
        bzrdir = tree.bzrdir
        try:
            bzrdir.destroy_workingtree()
        except errors.UnsupportedOperation:
            raise TestSkipped('Format does not support destroying tree')
        self.failIfExists('tree/file')
        self.assertRaises(errors.NoWorkingTree, bzrdir.open_workingtree)
        bzrdir.create_workingtree()
        self.failUnlessExists('tree/file')
        bzrdir.destroy_workingtree_metadata()
        self.failUnlessExists('tree/file')
        self.assertRaises(errors.NoWorkingTree, bzrdir.open_workingtree)

    def test_destroy_branch(self):
        branch = self.make_branch('branch')
        bzrdir = branch.bzrdir
        try:
            bzrdir.destroy_branch()
        except (errors.UnsupportedOperation, errors.TransportNotPossible):
            raise TestNotApplicable('Format does not support destroying tree')
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch)
        bzrdir.create_branch()
        bzrdir.open_branch()

    def test_destroy_repository(self):
        repo = self.make_repository('repository')
        bzrdir = repo.bzrdir
        try:
            bzrdir.destroy_repository()
        except (errors.UnsupportedOperation, errors.TransportNotPossible):
            raise TestNotApplicable('Format does not support destroying'
                                    ' repository')
        self.assertRaises(errors.NoRepositoryPresent, bzrdir.open_repository)
        bzrdir.create_repository()
        bzrdir.open_repository()

    def test_open_workingtree_raises_no_working_tree(self):
        """BzrDir.open_workingtree() should raise NoWorkingTree (rather than
        e.g. NotLocalUrl) if there is no working tree.
        """
        dir = self.make_bzrdir('source')
        vfs_dir = bzrdir.BzrDir.open(self.get_vfs_only_url('source'))
        if vfs_dir.has_workingtree():
            # This BzrDir format doesn't support BzrDirs without working trees,
            # so this test is irrelevant.
            return
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)

    def test_clone_on_transport(self):
        a_dir = self.make_bzrdir('source')
        target_transport = a_dir.root_transport.clone('..').clone('target')
        target = a_dir.clone_on_transport(target_transport)
        self.assertNotEqual(a_dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(a_dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])

    def test_clone_bzrdir_empty(self):
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])
    
    def test_clone_bzrdir_empty_force_new_ignored(self):
        # the force_new_repo parameter should have no effect on an empty
        # bzrdir's clone logic
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])
    
    def test_clone_bzrdir_repository(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

    def test_clone_bzrdir_repository_under_shared(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)

    def test_clone_bzrdir_repository_branch_both_under_shared(self):
        # Create a shared repository
        try:
            shared_repo = self.make_repository('shared', shared=True)
        except errors.IncompatibleFormat:
            return
        # Make a branch, 'commit_tree', and working tree outside of the shared
        # repository, and commit some revisions to it.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.root_transport)
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        # Copy the content (i.e. revisions) from the 'commit_tree' branch's
        # repository into the shared repository.
        tree.branch.repository.copy_content_into(shared_repo)
        # Make a branch 'source' inside the shared repository.
        dir = self.make_bzrdir('shared/source')
        dir.create_branch()
        # Clone 'source' to 'target', also inside the shared repository.
        target = dir.clone(self.get_url('shared/target'))
        # 'source', 'target', and the shared repo all have distinct bzrdirs.
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertNotEqual(dir.transport.base, shared_repo.bzrdir.transport.base)
        # The shared repository will contain revisions from the 'commit_tree'
        # repository, even revisions that are not part of the history of the
        # 'commit_tree' branch.
        self.assertTrue(shared_repo.has_revision('1'))

    def test_clone_bzrdir_repository_branch_only_source_under_shared(self):
        try:
            shared_repo = self.make_repository('shared', shared=True)
        except errors.IncompatibleFormat:
            return
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.branch.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        tree.branch.repository.copy_content_into(shared_repo)
        if shared_repo.make_working_trees():
            shared_repo.set_make_working_trees(False)
            self.assertFalse(shared_repo.make_working_trees())
        self.assertTrue(shared_repo.has_revision('1'))
        dir = self.make_bzrdir('shared/source')
        dir.create_branch()
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertNotEqual(dir.transport.base, shared_repo.bzrdir.transport.base)
        branch = target.open_branch()
        self.assertTrue(branch.repository.has_revision('1'))
        self.assertFalse(branch.repository.make_working_trees())
        self.assertTrue(branch.repository.is_shared())
        
    def test_clone_bzrdir_repository_under_shared_force_new_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_repository_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and clone it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.branch.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.branch.repository.copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='2')
        raise TestSkipped('revision limiting not strict yet')

    def test_clone_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/basis-inventory-cache',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     './.bzr/stat-cache',
                                    ])
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository())

    def test_clone_bzrdir_branch_and_repo_into_shared_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.bzrdir
        target = dir.clone(self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)
        self.assertEqual(source.revision_history(),
                         target.open_branch().revision_history())

    def test_clone_bzrdir_branch_and_repo_into_shared_repo_force_new_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.bzrdir
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        repo = target.open_repository()
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_branch_reference(self):
        # cloning should preserve the reference status of the branch in a bzrdir
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_clone_bzrdir_branch_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a branch with some revisions,
        # and clone it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_branch().last_revision())
        
    def test_clone_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())
        target.open_workingtree().revert()

    def test_clone_on_transport_preserves_repo_format(self):
        if self.bzrdir_format == bzrdir.format_registry.make_bzrdir('default'):
            format = 'knit'
        else:
            format = None
        source_branch = self.make_branch('source', format=format)
        # Ensure no format data is cached
        a_dir = bzrlib.branch.Branch.open_from_transport(
            self.get_transport('source')).bzrdir
        target_transport = a_dir.root_transport.clone('..').clone('target')
        target_bzrdir = a_dir.clone_on_transport(target_transport)
        target_repo = target_bzrdir.open_repository()
        source_branch = bzrlib.branch.Branch.open(
            self.get_vfs_only_url('source'))
        self.assertEqual(target_repo._format, source_branch.repository._format)

    def test_revert_inventory(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

        target.open_workingtree().revert()
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

    def test_clone_bzrdir_tree_branch_reference(self):
        # a tree with a branch reference (aka a checkout) 
        # should stay a checkout on clone.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.createWorkingTreeOrSkip(dir)
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository/inventory.knit',
                                     ])

    def test_clone_bzrdir_tree_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a tree with a revision with a last-revision
        # and clone it with a revision limit.
        # This smoke test just checks the revision-id is right. Tree specific
        # tests will check corner cases.
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'), revision_id='1')
        self.skipIfNoWorkingTree(target)
        self.assertEqual(['1'], target.open_workingtree().get_parent_ids())

    def test_clone_bzrdir_into_notrees_repo(self):
        """Cloning into a no-trees repo should not create a working tree"""
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1')

        try:
            repo = self.make_repository('repo', shared=True)
        except errors.IncompatibleFormat:
            raise TestNotApplicable('must support shared repositories')
        if repo.make_working_trees():
            repo.set_make_working_trees(False)
            self.assertFalse(repo.make_working_trees())

        dir = tree.bzrdir
        a_dir = dir.clone(self.get_url('repo/a'))
        a_dir.open_branch()
        self.assertRaises(errors.NoWorkingTree, a_dir.open_workingtree)

    def test_clone_respects_stacked(self):
        branch = self.make_branch('parent')
        child_transport = branch.bzrdir.root_transport.clone('../child')
        child = branch.bzrdir.clone_on_transport(child_transport,
                                                 stacked_on=branch.base)
        self.assertEqual(child.open_branch().get_stacked_on_url(), branch.base)

    def test_get_branch_reference_on_reference(self):
        """get_branch_reference should return the right url."""
        referenced_branch = self.make_branch('referenced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertEqual(referenced_branch.bzrdir.root_transport.abspath('') + '/',
            dir.get_branch_reference())

    def test_get_branch_reference_on_non_reference(self):
        """get_branch_reference should return None for non-reference branches."""
        branch = self.make_branch('referenced')
        self.assertEqual(None, branch.bzrdir.get_branch_reference())

    def test_get_branch_reference_no_branch(self):
        """get_branch_reference should not mask NotBranchErrors."""
        dir = self.make_bzrdir('source')
        if dir.has_branch():
            # this format does not support branchless bzrdirs.
            return
        self.assertRaises(errors.NotBranchError, dir.get_branch_reference)

    def test_sprout_bzrdir_empty(self):
        dir = self.make_bzrdir('source')
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # creates a new repository branch and tree
        target.open_repository()
        target.open_branch()
        target.open_workingtree()

    def test_sprout_bzrdir_empty_under_shared_repo(self):
        # sprouting an empty dir into a repo uses the repo
        dir = self.make_bzrdir('source')
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'))
        self.assertRaises(errors.NoRepositoryPresent, target.open_repository)
        target.open_branch()
        try:
            target.open_workingtree()
        except errors.NoWorkingTree:
            # bzrdir's that never have working trees are allowed to pass;
            # whitelist them for now.
            self.assertIsInstance(target, RemoteBzrDir)

    def test_sprout_bzrdir_empty_under_shared_repo_force_new(self):
        # the force_new_repo parameter should force use of a new repo in an empty
        # bzrdir's sprout logic
        dir = self.make_bzrdir('source')
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'),
                                   force_new_repo=True)
        target.open_repository()
        target.open_branch()
        target.open_workingtree()
    
    def test_sprout_bzrdir_repository(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        try:
            self.assertTrue(
                _mod_revision.is_null(_mod_revision.ensure_null(
                dir.open_branch().last_revision())))
        except errors.NotBranchError:
            pass
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # testing inventory isn't reasonable for repositories
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/branch',
                                     './.bzr/checkout',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository/inventory.knit',
                                     ])
        try:
            # If we happen to have a tree, we'll guarantee everything
            # except for the tree root is the same.
            inventory_f = file(dir.transport.base+'inventory', 'rb')
            self.assertContainsRe(inventory_f.read(), 
                                  '<inventory file_id="TREE_ROOT[^"]*"'
                                  ' format="5">\n</inventory>\n')
            inventory_f.close()
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

    def test_sprout_bzrdir_with_repository_to_shared(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.branch.repository.copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_repository_branch_both_under_shared(self):
        try:
            shared_repo = self.make_repository('shared', shared=True)
        except errors.IncompatibleFormat:
            return
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        tree.branch.repository.copy_content_into(shared_repo)
        dir = self.make_bzrdir('shared/source')
        dir.create_branch()
        target = self.sproutOrSkip(dir, self.get_url('shared/target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertNotEqual(dir.transport.base, shared_repo.bzrdir.transport.base)
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_repository_branch_only_source_under_shared(self):
        try:
            shared_repo = self.make_repository('shared', shared=True)
        except errors.IncompatibleFormat:
            return
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        tree.branch.repository.copy_content_into(shared_repo)
        if shared_repo.make_working_trees():
            shared_repo.set_make_working_trees(False)
            self.assertFalse(shared_repo.make_working_trees())
        self.assertTrue(shared_repo.has_revision('1'))
        dir = self.make_bzrdir('shared/source')
        dir.create_branch()
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertNotEqual(dir.transport.base, shared_repo.bzrdir.transport.base)
        branch = target.open_branch()
        self.assertTrue(branch.repository.has_revision('1'))
        if not isinstance(branch.bzrdir, RemoteBzrDir):
            self.assertTrue(branch.repository.make_working_trees())
        self.assertFalse(branch.repository.is_shared())

    def test_sprout_bzrdir_repository_under_shared_force_new_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.branch.repository.copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'),
                                   force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_repository_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and sprout it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.bzrdir.open_branch().set_revision_history([])
        tree.set_parent_trees([])
        tree.commit('revision 2', rev_id='2')
        source = self.make_repository('source')
        tree.branch.repository.copy_content_into(source)
        dir = source.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'), revision_id='2')
        raise TestSkipped('revision limiting not strict yet')

    def test_sprout_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/basis-inventory-cache',
                                     './.bzr/branch/branch.conf',
                                     './.bzr/branch/parent',
                                     './.bzr/checkout',
                                     './.bzr/checkout/inventory',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository/inventory.knit',
                                     './.bzr/stat-cache',
                                     './foo',
                                     ])

    def test_sprout_bzrdir_branch_and_repo_shared(self):
        # sprouting a branch with a repo into a shared repo uses the shared
        # repo
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'))
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_and_repo_shared_force_new_repo(self):
        # sprouting a branch with a repo into a shared repo uses the shared
        # repo
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'),
                                   force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_reference(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()

    def test_sprout_bzrdir_branch_reference_shared(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_tree = self.make_branch_and_tree('referenced')
        referenced_tree.commit('1', rev_id='1', allow_pointless=True)
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_tree.branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and we want no repository as the target is shared
        self.assertRaises(errors.NoRepositoryPresent, 
                          target.open_repository)
        # and we want revision '1' in the shared repo
        self.assertTrue(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_reference_shared_force_new_repo(self):
        # sprouting should create a repository if needed and a sprouted branch.
        referenced_tree = self.make_branch_and_tree('referenced')
        referenced_tree.commit('1', rev_id='1', allow_pointless=True)
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_tree.branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        try:
            shared_repo = self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = self.sproutOrSkip(dir, self.get_url('target/child'),
                                   force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and we want revision '1' in the new repo
        self.assertTrue(target.open_repository().has_revision('1'))
        # but not the shared one
        self.assertFalse(shared_repo.has_revision('1'))

    def test_sprout_bzrdir_branch_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a repository with some revisions,
        # and sprout it with a revision limit.
        # 
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'), revision_id='1')
        self.assertEqual('1', target.open_branch().last_revision())
        
    def test_sprout_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/branch/branch.conf',
                                     './.bzr/branch/parent',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/inventory',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository',
                                     './.bzr/stat-cache',
                                     ])
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository())

    def test_sprout_bzrdir_tree_branch_reference(self):
        # sprouting should create a repository if needed and a sprouted branch.
        # the tree state should not be copied.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        tree = self.createWorkingTreeOrSkip(dir)
        self.build_tree(['source/subdir/'])
        tree.add('subdir')
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()
        result_tree = target.open_workingtree()
        self.assertFalse(result_tree.has_filename('subdir'))

    def test_sprout_bzrdir_tree_branch_reference_revision(self):
        # sprouting should create a repository if needed and a sprouted branch.
        # the tree state should not be copied but the revision changed,
        # and the likewise the new branch should be truncated too
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        tree = self.createWorkingTreeOrSkip(dir)
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        target = dir.sprout(self.get_url('target'), revision_id='1')
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # we want target to have a branch that is in-place.
        self.assertEqual(target, target.open_branch().bzrdir)
        # and as we dont support repositories being detached yet, a repo in 
        # place
        target.open_repository()
        # we trust that the working tree sprouting works via the other tests.
        self.assertEqual(['1'], target.open_workingtree().get_parent_ids())
        self.assertEqual('1', target.open_branch().last_revision())

    def test_sprout_bzrdir_tree_revision(self):
        # test for revision limiting, [smoke test, not corner case checks].
        # make a tree with a revision with a last-revision
        # and sprout it with a revision limit.
        # This smoke test just checks the revision-id is right. Tree specific
        # tests will check corner cases.
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        dir = tree.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'), revision_id='1')
        self.assertEqual(['1'], target.open_workingtree().get_parent_ids())

    def test_sprout_takes_accelerator(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        dir = tree.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'),
                                   accelerator_tree=tree)
        self.assertEqual(['2'], target.open_workingtree().get_parent_ids())

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = get_transport(self.get_url())
        readonly_t = get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        self.failUnless(isinstance(made_control, bzrdir.BzrDir))
        self.assertEqual(self.bzrdir_format,
                         bzrdir.BzrDirFormat.find_format(readonly_t))
        direct_opened_dir = self.bzrdir_format.open(readonly_t)
        opened_dir = bzrdir.BzrDir.open(t.base)
        self.assertEqual(made_control._format,
                         opened_dir._format)
        self.assertEqual(direct_opened_dir._format,
                         opened_dir._format)
        self.failUnless(isinstance(opened_dir, bzrdir.BzrDir))

    def test_open_not_bzrdir(self):
        # test the formats specific behaviour for no-content or similar dirs.
        self.assertRaises(NotBranchError,
                          self.bzrdir_format.open,
                          get_transport(self.get_readonly_url()))

    def test_create_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        self.failUnless(isinstance(made_branch, bzrlib.branch.Branch))
        self.assertEqual(made_control, made_branch.bzrdir)
        
    def test_open_branch(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        opened_branch = made_control.open_branch()
        self.assertEqual(made_control, opened_branch.bzrdir)
        self.failUnless(isinstance(opened_branch, made_branch.__class__))
        self.failUnless(isinstance(opened_branch._format, made_branch._format.__class__))

    def test_create_repository(self):
        # a bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        # Check that we have a repository object.
        made_repo.has_revision('foo')
        self.assertEqual(made_control, made_repo.bzrdir)

    def test_create_repository_shared(self):
        # a bzrdir can create a shared repository or 
        # fail appropriately
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        try:
            made_repo = made_control.create_repository(shared=True)
        except errors.IncompatibleFormat:
            # Old bzrdir formats don't support shared repositories
            # and should raise IncompatibleFormat
            return
        self.assertTrue(made_repo.is_shared())

    def test_create_repository_nonshared(self):
        # a bzrdir can create a non-shared repository 
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository(shared=False)
        self.assertFalse(made_repo.is_shared())
        
    def test_open_repository(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        opened_repo = made_control.open_repository()
        self.assertEqual(made_control, opened_repo.bzrdir)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.failUnless(isinstance(opened_repo._format, made_repo._format.__class__))

    def test_create_workingtree(self):
        # a bzrdir can construct a working tree for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = self.get_transport()
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        made_branch = made_control.create_branch()
        made_tree = self.createWorkingTreeOrSkip(made_control)
        self.failUnless(isinstance(made_tree, workingtree.WorkingTree))
        self.assertEqual(made_control, made_tree.bzrdir)
        
    def test_create_workingtree_revision(self):
        # a bzrdir can construct a working tree for itself @ a specific revision.
        t = self.get_transport()
        source = self.make_branch_and_tree('source')
        source.commit('a', rev_id='a', allow_pointless=True)
        source.commit('b', rev_id='b', allow_pointless=True)
        t.mkdir('new')
        t_new = t.clone('new')
        made_control = self.bzrdir_format.initialize_on_transport(t_new)
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        try:
            made_tree = made_control.create_workingtree(revision_id='a')
        except errors.NotLocalUrl:
            raise TestSkipped("Can't make working tree on transport %r" % t)
        self.assertEqual(['a'], made_tree.get_parent_ids())
        
    def test_open_workingtree(self):
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # this has to be tested with local access as we still support creating
        # format 6 bzrdirs
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
            made_repo = made_control.create_repository()
            made_branch = made_control.create_branch()
            made_tree = made_control.create_workingtree()
        except errors.NotLocalUrl:
            raise TestSkipped("Can't initialize %r on transport %r"
                              % (self.bzrdir_format, t))
        opened_tree = made_control.open_workingtree()
        self.assertEqual(made_control, opened_tree.bzrdir)
        self.failUnless(isinstance(opened_tree, made_tree.__class__))
        self.failUnless(isinstance(opened_tree._format, made_tree._format.__class__))

    def test_get_branch_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_branch_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_branch_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # branches, or it supports anonymous  branch formats, but not both.
        anonymous_format = bzrlib.branch.BzrBranchFormat4()
        identifiable_format = bzrlib.branch.BzrBranchFormat5()
        try:
            found_transport = dir.get_branch_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_branch_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_branch_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir('.')

    def test_get_repository_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_repository_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_repository_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # repositories, or it supports anonymous  repository formats, but not both.
        anonymous_format = weaverepo.RepositoryFormat6()
        identifiable_format = weaverepo.RepositoryFormat7()
        try:
            found_transport = dir.get_repository_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_repository_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_repository_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir('.')

    def test_get_workingtree_transport(self):
        dir = self.make_bzrdir('.')
        # without a format, get_workingtree_transport gives use a transport
        # which -may- point to an existing dir.
        self.assertTrue(isinstance(dir.get_workingtree_transport(None),
                                   transport.Transport))
        # with a given format, either the bzr dir supports identifiable
        # trees, or it supports anonymous tree formats, but not both.
        anonymous_format = workingtree.WorkingTreeFormat2()
        identifiable_format = workingtree.WorkingTreeFormat3()
        try:
            found_transport = dir.get_workingtree_transport(anonymous_format)
            self.assertRaises(errors.IncompatibleFormat,
                              dir.get_workingtree_transport,
                              identifiable_format)
        except errors.IncompatibleFormat:
            found_transport = dir.get_workingtree_transport(identifiable_format)
        self.assertTrue(isinstance(found_transport, transport.Transport))
        # and the dir which has been initialized for us must exist.
        found_transport.list_dir('.')

    def test_root_transport(self):
        dir = self.make_bzrdir('.')
        self.assertEqual(dir.root_transport.base,
                         get_transport(self.get_url('.')).base)

    def test_find_repository_no_repo_under_standalone_branch(self):
        # finding a repo stops at standalone branches even if there is a
        # higher repository available.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('intermediate')
        get_transport(self.get_url()).mkdir('intermediate')
        get_transport(self.get_url()).mkdir('intermediate/child')
        made_control = self.bzrdir_format.initialize(url)
        made_control.create_repository()
        innermost_control = self.bzrdir_format.initialize(
            self.get_url('intermediate/child'))
        try:
            child_repo = innermost_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        self.assertRaises(errors.NoRepositoryPresent,
                          innermost_control.find_repository)

    def test_find_repository_containing_shared_repository(self):
        # find repo inside a shared repo with an empty control dir
        # returns the shared repo.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('childbzrdir')
        get_transport(self.get_url()).mkdir('childbzrdir')
        made_control = self.bzrdir_format.initialize(url)
        try:
            child_repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        found_repo = made_control.find_repository()
        self.assertEqual(repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        
    def test_find_repository_standalone_with_containing_shared_repository(self):
        # find repo inside a standalone repo inside a shared repo finds the standalone repo
        try:
            containing_repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        child_repo = self.make_repository('childrepo')
        opened_control = bzrdir.BzrDir.open(self.get_url('childrepo'))
        found_repo = opened_control.find_repository()
        self.assertEqual(child_repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)

    def test_find_repository_shared_within_shared_repository(self):
        # find repo at a shared repo inside a shared repo finds the inner repo
        try:
            containing_repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('childrepo')
        get_transport(self.get_url()).mkdir('childrepo')
        child_control = self.bzrdir_format.initialize(url)
        child_repo = child_control.create_repository(shared=True)
        opened_control = bzrdir.BzrDir.open(self.get_url('childrepo'))
        found_repo = opened_control.find_repository()
        self.assertEqual(child_repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        self.assertNotEqual(child_repo.bzrdir.root_transport.base,
                            containing_repo.bzrdir.root_transport.base)

    def test_find_repository_with_nested_dirs_works(self):
        # find repo inside a bzrdir inside a bzrdir inside a shared repo 
        # finds the outer shared repo.
        try:
            repo = self.make_repository('.', shared=True)
        except errors.IncompatibleFormat:
            # need a shared repository to test this.
            return
        url = self.get_url('intermediate')
        get_transport(self.get_url()).mkdir('intermediate')
        get_transport(self.get_url()).mkdir('intermediate/child')
        made_control = self.bzrdir_format.initialize(url)
        try:
            child_repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        innermost_control = self.bzrdir_format.initialize(
            self.get_url('intermediate/child'))
        try:
            child_repo = innermost_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        found_repo = innermost_control.find_repository()
        self.assertEqual(repo.bzrdir.root_transport.base,
                         found_repo.bzrdir.root_transport.base)
        
    def test_can_and_needs_format_conversion(self):
        # check that we can ask an instance if its upgradable
        dir = self.make_bzrdir('.')
        if dir.can_convert_format():
            # if its default updatable there must be an updater 
            # (we force the latest known format as downgrades may not be
            # available
            self.assertTrue(isinstance(dir._format.get_converter(
                format=dir._format), bzrdir.Converter))
        dir.needs_format_conversion(None)

    def test_upgrade_new_instance(self):
        """Does an available updater work?"""
        dir = self.make_bzrdir('.')
        # for now, upgrade is not ready for partial bzrdirs.
        dir.create_repository()
        dir.create_branch()
        self.createWorkingTreeOrSkip(dir)
        if dir.can_convert_format():
            # if its default updatable there must be an updater 
            # (we force the latest known format as downgrades may not be
            # available
            pb = ui.ui_factory.nested_progress_bar()
            try:
                dir._format.get_converter(format=dir._format).convert(dir, pb)
            finally:
                pb.finished()
            # and it should pass 'check' now.
            check_branch(bzrdir.BzrDir.open(self.get_url('.')).open_branch(),
                         False)

    def test_format_description(self):
        dir = self.make_bzrdir('.')
        text = dir._format.get_format_description()
        self.failUnless(len(text))

    def test_retire_bzrdir(self):
        bd = self.make_bzrdir('.')
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(['.bzr.retired.0/', '.bzr.retired.0/junk',],
            transport=transport)
        self.failUnless(transport.has('.bzr'))
        bd.retire_bzrdir()
        self.failIf(transport.has('.bzr'))
        self.failUnless(transport.has('.bzr.retired.1'))

    def test_retire_bzrdir_limited(self):
        bd = self.make_bzrdir('.')
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(['.bzr.retired.0/', '.bzr.retired.0/junk',],
            transport=transport)
        self.failUnless(transport.has('.bzr'))
        self.assertRaises((errors.FileExists, errors.DirectoryNotEmpty),
            bd.retire_bzrdir, limit=0) 


class TestBreakLock(TestCaseWithBzrDir):

    def setUp(self):
        super(TestBreakLock, self).setUp()
        # we want a UI factory that accepts canned input for the tests:
        # while SilentUIFactory still accepts stdin, we need to customise
        # ours
        self.old_factory = bzrlib.ui.ui_factory
        self.addCleanup(self.restoreFactory)
        bzrlib.ui.ui_factory = bzrlib.ui.SilentUIFactory()

    def restoreFactory(self):
        bzrlib.ui.ui_factory = self.old_factory

    def test_break_lock_empty(self):
        # break lock on an empty bzrdir should work silently.
        dir = self.make_bzrdir('.')
        try:
            dir.break_lock()
        except NotImplementedError:
            pass

    def test_break_lock_repository(self):
        # break lock with just a repo should unlock the repo.
        repo = self.make_repository('.')
        repo.lock_write()
        lock_repo = repo.bzrdir.open_repository()
        if not lock_repo.get_physical_lock_status():
            # This bzrdir's default repository does not physically lock things
            # and thus this interaction cannot be tested at the interface
            # level.
            repo.unlock()
            return
        # only one yes needed here: it should only be unlocking
        # the repo
        bzrlib.ui.ui_factory.stdin = StringIO("y\n")
        try:
            repo.bzrdir.break_lock()
        except NotImplementedError:
            # this bzrdir does not implement break_lock - so we cant test it.
            repo.unlock()
            return
        lock_repo.lock_write()
        lock_repo.unlock()
        self.assertRaises(errors.LockBroken, repo.unlock)

    def test_break_lock_branch(self):
        # break lock with just a repo should unlock the branch.
        # and not directly try the repository.
        # we test this by making a branch reference to a branch
        # and repository in another bzrdir
        # for pre-metadir formats this will fail, thats ok.
        master = self.make_branch('branch')
        thisdir = self.make_bzrdir('this')
        try:
            bzrlib.branch.BranchReferenceFormat().initialize(
                thisdir, master)
        except errors.IncompatibleFormat:
            return
        unused_repo = thisdir.create_repository()
        master.lock_write()
        unused_repo.lock_write()
        try:
            # two yes's : branch and repository. If the repo in this
            # dir is inappropriately accessed, 3 will be needed, and
            # we'll see that because the stream will be fully consumed
            bzrlib.ui.ui_factory.stdin = StringIO("y\ny\ny\n")
            # determine if the repository will have been locked;
            this_repo_locked = \
                thisdir.open_repository().get_physical_lock_status()
            master.bzrdir.break_lock()
            if this_repo_locked:
                # only two ys should have been read
                self.assertEqual("y\n", bzrlib.ui.ui_factory.stdin.read())
            else:
                # only one y should have been read
                self.assertEqual("y\ny\n", bzrlib.ui.ui_factory.stdin.read())
            # we should be able to lock a newly opened branch now
            branch = master.bzrdir.open_branch()
            branch.lock_write()
            branch.unlock()
            if this_repo_locked:
                # we should not be able to lock the repository in thisdir as
                # its still held by the explicit lock we took, and the break
                # lock should not have touched it.
                repo = thisdir.open_repository()
                self.assertRaises(errors.LockContention, repo.lock_write)
        finally:
            unused_repo.unlock()
        self.assertRaises(errors.LockBroken, master.unlock)

    def test_break_lock_tree(self):
        # break lock with a tree should unlock the tree but not try the 
        # branch explicitly. However this is very hard to test for as we 
        # dont have a tree reference class, nor is one needed; 
        # the worst case if this code unlocks twice is an extra question
        # being asked.
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        # three yes's : tree, branch and repository.
        bzrlib.ui.ui_factory.stdin = StringIO("y\ny\ny\ny\n")
        try:
            tree.bzrdir.break_lock()
        except (NotImplementedError, errors.LockActive):
            # bzrdir does not support break_lock
            # or one of the locked objects (currently only tree does this)
            # raised a LockActive because we do still have a live locked
            # object.
            tree.unlock()
            return
        self.assertEqual("y\n", bzrlib.ui.ui_factory.stdin.read())
        lock_tree = tree.bzrdir.open_workingtree()
        lock_tree.lock_write()
        lock_tree.unlock()
        self.assertRaises(errors.LockBroken, tree.unlock)


class TestTransportConfig(TestCaseWithBzrDir):

    def test_get_config(self):
        my_dir = self.make_bzrdir('.')
        config = my_dir.get_config()
        if config is None:
            self.assertFalse(
                isinstance(my_dir, (bzrdir.BzrDirMeta1, RemoteBzrDir)),
                "%r should support configs" % my_dir)
            raise TestNotApplicable(
                'This BzrDir format does not support configs.')
        config.set_default_stack_on('http://example.com')
        self.assertEqual('http://example.com', config.get_default_stack_on())
        my_dir2 = bzrdir.BzrDir.open(self.get_url('.'))
        config2 = my_dir2.get_config()
        self.assertEqual('http://example.com', config2.get_default_stack_on())


class ChrootedBzrDirTests(ChrootedTestCase):

    def test_find_repository_no_repository(self):
        # loopback test to check the current format fails to find a 
        # share repository correctly.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        # - do the vfs initialisation over the basic vfs transport
        # XXX: TODO this should become a 'bzrdirlocation' api call.
        url = self.get_vfs_only_url('subdir')
        get_transport(self.get_vfs_only_url()).mkdir('subdir')
        made_control = self.bzrdir_format.initialize(self.get_url('subdir'))
        try:
            repo = made_control.open_repository()
            # if there is a repository, then the format cannot ever hit this 
            # code path.
            return
        except errors.NoRepositoryPresent:
            pass
        made_control = bzrdir.BzrDir.open(self.get_readonly_url('subdir'))
        self.assertRaises(errors.NoRepositoryPresent,
                          made_control.find_repository)

