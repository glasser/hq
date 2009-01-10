# Copyright (C) 2005, 2006, 2007 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
#           and others
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

from cStringIO import StringIO
import errno
import os
import sys

from bzrlib import (
    branch,
    bzrdir,
    errors,
    osutils,
    tests,
    urlutils,
    workingtree,
    )
from bzrlib.errors import (NotBranchError, NotVersionedError,
                           UnsupportedOperation, PathsNotVersionedError)
from bzrlib.inventory import Inventory
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestSkipped, TestNotApplicable
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree, WorkingTree2)
from bzrlib.conflicts import ConflictList, TextConflict, ContentsConflict


class TestWorkingTree(TestCaseWithWorkingTree):

    def test_list_files(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'file'])
        if has_symlinks():
            os.symlink('target', 'symlink')
        tree.lock_read()
        files = list(tree.list_files())
        tree.unlock()
        self.assertEqual(files[0], ('dir', '?', 'directory', None, TreeDirectory()))
        self.assertEqual(files[1], ('file', '?', 'file', None, TreeFile()))
        if has_symlinks():
            self.assertEqual(files[2], ('symlink', '?', 'symlink', None, TreeLink()))

    def test_list_files_sorted(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'file', 'dir/file', 'dir/b',
                         'dir/subdir/', 'a', 'dir/subfile',
                         'zz_dir/', 'zz_dir/subfile'])
        tree.lock_read()
        files = [(path, kind) for (path, v, kind, file_id, entry)
                               in tree.list_files()]
        tree.unlock()
        self.assertEqual([
            ('a', 'file'),
            ('dir', 'directory'),
            ('file', 'file'),
            ('zz_dir', 'directory'),
            ], files)

        tree.add(['dir', 'zz_dir'])
        tree.lock_read()
        files = [(path, kind) for (path, v, kind, file_id, entry)
                               in tree.list_files()]
        tree.unlock()
        self.assertEqual([
            ('a', 'file'),
            ('dir', 'directory'),
            ('dir/b', 'file'),
            ('dir/file', 'file'),
            ('dir/subdir', 'directory'),
            ('dir/subfile', 'file'),
            ('file', 'file'),
            ('zz_dir', 'directory'),
            ('zz_dir/subfile', 'file'),
            ], files)

    def test_list_files_kind_change(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/filename'])
        tree.add('filename', 'file-id')
        os.unlink('tree/filename')
        self.build_tree(['tree/filename/'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        result = list(tree.list_files())
        self.assertEqual(1, len(result))
        self.assertEqual(('filename', 'V', 'directory', 'file-id'),
                         result[0][:4])

    def test_open_containing(self):
        branch = self.make_branch_and_tree('.').branch
        local_base = urlutils.local_path_from_url(branch.base)

        # Empty opens '.'
        wt, relpath = WorkingTree.open_containing()
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # '.' opens this dir
        wt, relpath = WorkingTree.open_containing(u'.')
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # './foo' finds '.' and a relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # abspath(foo) finds '.' and relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        wt, relpath = WorkingTree.open_containing(getcwd() + '/foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # can even be a url: finds '.' and relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        wt, relpath = WorkingTree.open_containing(
                    urlutils.local_path_to_url(getcwd() + '/foo'))
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

    def test_basic_relpath(self):
        # for comprehensive relpath tests, see whitebox.py.
        tree = self.make_branch_and_tree('.')
        self.assertEqual('child',
                         tree.relpath(pathjoin(getcwd(), 'child')))

    def test_lock_locks_branch(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.assertEqual('r', tree.branch.peek_lock_mode())
        tree.unlock()
        self.assertEqual(None, tree.branch.peek_lock_mode())
        tree.lock_write()
        self.assertEqual('w', tree.branch.peek_lock_mode())
        tree.unlock()
        self.assertEqual(None, tree.branch.peek_lock_mode())
 
    def test_revert(self):
        """Test selected-file revert"""
        tree = self.make_branch_and_tree('.')

        self.build_tree(['hello.txt'])
        file('hello.txt', 'w').write('initial hello')

        self.assertRaises(PathsNotVersionedError,
                          tree.revert, ['hello.txt'])
        tree.add(['hello.txt'])
        tree.commit('create initial hello.txt')

        self.check_file_contents('hello.txt', 'initial hello')
        file('hello.txt', 'w').write('new hello')
        self.check_file_contents('hello.txt', 'new hello')

        # revert file modified since last revision
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')

        # reverting again does not clobber the backup
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')
        
        # backup files are numbered
        file('hello.txt', 'w').write('new hello2')
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')
        self.check_file_contents('hello.txt.~2~', 'new hello2')

    def test_revert_missing(self):
        # Revert a file that has been deleted since last commit
        tree = self.make_branch_and_tree('.')
        file('hello.txt', 'w').write('initial hello')
        tree.add('hello.txt')
        tree.commit('added hello.txt')
        os.unlink('hello.txt')
        tree.remove('hello.txt')
        tree.revert(['hello.txt'])
        self.failUnlessExists('hello.txt')

    def test_versioned_files_not_unknown(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt'])
        tree.add('hello.txt')
        self.assertEquals(list(tree.unknowns()),
                          [])

    def test_unknowns(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt.~1~'])
        self.build_tree_contents([('.bzrignore', '*.~*\n')])
        tree.add('.bzrignore')
        self.assertEquals(list(tree.unknowns()),
                          ['hello.txt'])

    def test_initialize(self):
        # initialize should create a working tree and branch in an existing dir
        t = self.make_branch_and_tree('.')
        b = branch.Branch.open('.')
        self.assertEqual(t.branch.base, b.base)
        t2 = WorkingTree.open('.')
        self.assertEqual(t.basedir, t2.basedir)
        self.assertEqual(b.base, t2.branch.base)
        # TODO maybe we should check the branch format? not sure if its
        # appropriate here.

    def test_rename_dirs(self):
        """Test renaming directories and the files within them."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['dir/', 'dir/sub/', 'dir/sub/file'])
        wt.add(['dir', 'dir/sub', 'dir/sub/file'])

        wt.commit('create initial state')

        revid = b.revision_history()[0]
        self.log('first revision_id is {%s}' % revid)
        
        inv = b.repository.get_revision_inventory(revid)
        self.log('contents of inventory: %r' % inv.entries())

        self.check_inventory_shape(inv,
                                   ['dir/', 'dir/sub/', 'dir/sub/file'])
        wt.rename_one('dir', 'newdir')

        wt.lock_read()
        self.check_inventory_shape(wt.inventory,
                                   ['newdir/', 'newdir/sub/', 'newdir/sub/file'])
        wt.unlock()
        wt.rename_one('newdir/sub', 'newdir/newsub')
        wt.lock_read()
        self.check_inventory_shape(wt.inventory,
                                   ['newdir/', 'newdir/newsub/',
                                    'newdir/newsub/file'])
        wt.unlock()

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" adds the parent as necessary, but simple working tree add
        doesn't do that.
        """
        from bzrlib.errors import NotVersionedError
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/',
                         'foo/hello'])
        self.assertRaises(NotVersionedError,
                          wt.add,
                          'foo/hello')

    def test_add_missing(self):
        # adding a msising file -> NoSuchFile
        wt = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchFile, wt.add, 'fpp')

    def test_remove_verbose(self):
        #FIXME the remove api should not print or otherwise depend on the
        # text UI - RBC 20060124
        wt = self.make_branch_and_tree('.')
        self.build_tree(['hello'])
        wt.add(['hello'])
        wt.commit(message='add hello')
        stdout = StringIO()
        stderr = StringIO()
        self.assertEqual(None, self.apply_redirected(None, stdout, stderr,
                                                     wt.remove,
                                                     ['hello'],
                                                     verbose=True))
        self.assertEqual('?       hello\n', stdout.getvalue())
        self.assertEqual('', stderr.getvalue())

    def test_clone_trivial(self):
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.bzrdir.clone('target')
        cloned = cloned_dir.open_workingtree()
        self.assertEqual(cloned.get_parent_ids(), wt.get_parent_ids())

    def test_last_revision(self):
        wt = self.make_branch_and_tree('source')
        self.assertEqual([], wt.get_parent_ids())
        wt.commit('A', allow_pointless=True, rev_id='A')
        parent_ids = wt.get_parent_ids()
        self.assertEqual(['A'], parent_ids)
        for parent_id in parent_ids:
            self.assertIsInstance(parent_id, str)

    def test_set_last_revision(self):
        wt = self.make_branch_and_tree('source')
        # set last-revision to one not in the history
        wt.set_last_revision('A')
        # set it back to None for an empty tree.
        wt.set_last_revision('null:')
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertEqual(['A'], wt.get_parent_ids())
        # None is aways in the branch
        wt.set_last_revision('null:')
        self.assertEqual([], wt.get_parent_ids())
        # and now we can set it to 'A'
        # because some formats mutate the branch to set it on the tree
        # we need to alter the branch to let this pass.
        try:
            wt.branch.set_revision_history(['A', 'B'])
        except errors.NoSuchRevision, e:
            self.assertEqual('B', e.revision)
            raise TestSkipped("Branch format does not permit arbitrary"
                              " history")
        wt.set_last_revision('A')
        self.assertEqual(['A'], wt.get_parent_ids())
        self.assertRaises(errors.ReservedId, wt.set_last_revision, 'A:')

    def test_set_last_revision_different_to_branch(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = branch.bzrdir.create_workingtree()
        wt.commit('A', allow_pointless=True, rev_id='A')
        wt.set_last_revision(None)
        self.assertEqual([], wt.get_parent_ids())
        self.assertEqual('A', wt.branch.last_revision())
        # and now we can set it back to 'A'
        wt.set_last_revision('A')
        self.assertEqual(['A'], wt.get_parent_ids())
        self.assertEqual('A', wt.branch.last_revision())

    def test_clone_and_commit_preserves_last_revision(self):
        """Doing a commit into a clone tree does not affect the source."""
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.bzrdir.clone('target')
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertNotEqual(cloned_dir.open_workingtree().get_parent_ids(),
                            wt.get_parent_ids())

    def test_clone_preserves_content(self):
        wt = self.make_branch_and_tree('source')
        self.build_tree(['added', 'deleted', 'notadded'],
                        transport=wt.bzrdir.transport.clone('..'))
        wt.add('deleted', 'deleted')
        wt.commit('add deleted')
        wt.remove('deleted')
        wt.add('added', 'added')
        cloned_dir = wt.bzrdir.clone('target')
        cloned = cloned_dir.open_workingtree()
        cloned_transport = cloned.bzrdir.transport.clone('..')
        self.assertFalse(cloned_transport.has('deleted'))
        self.assertTrue(cloned_transport.has('added'))
        self.assertFalse(cloned_transport.has('notadded'))
        self.assertEqual('added', cloned.path2id('added'))
        self.assertEqual(None, cloned.path2id('deleted'))
        self.assertEqual(None, cloned.path2id('notadded'))
        
    def test_basis_tree_returns_last_revision(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add('foo', 'foo-id')
        wt.commit('A', rev_id='A')
        wt.rename_one('foo', 'bar')
        wt.commit('B', rev_id='B')
        wt.set_parent_ids(['B'])
        tree = wt.basis_tree()
        tree.lock_read()
        self.failUnless(tree.has_filename('bar'))
        tree.unlock()
        wt.set_parent_ids(['A'])
        tree = wt.basis_tree()
        tree.lock_read()
        self.failUnless(tree.has_filename('foo'))
        tree.unlock()

    def test_clone_tree_revision(self):
        # make a tree with a last-revision,
        # and clone it with a different last-revision, this should switch
        # do it.
        #
        # also test that the content is merged
        # and conflicts recorded.
        # This should merge between the trees - local edits should be preserved
        # but other changes occured.
        # we test this by having one file that does
        # not change between two revisions, and another that does -
        # if the changed one is not changed, fail,
        # if the one that did not change has lost a local change, fail.
        # 
        raise TestSkipped('revision limiting is not implemented yet.')

    def test_initialize_with_revision_id(self):
        # a bzrdir can construct a working tree for itself @ a specific revision.
        source = self.make_branch_and_tree('source')
        source.commit('a', rev_id='a', allow_pointless=True)
        source.commit('b', rev_id='b', allow_pointless=True)
        self.build_tree(['new/'])
        made_control = self.bzrdir_format.initialize('new')
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        made_tree = self.workingtree_format.initialize(made_control, revision_id='a')
        self.assertEqual(['a'], made_tree.get_parent_ids())

    def test_update_sets_last_revision(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        main_branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            main_branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = main_branch.bzrdir.create_workingtree()
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        branch.BranchReferenceFormat().initialize(checkout, main_branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        wt.commit('A', rev_id='A')
        # and update old_tree
        self.assertEqual(0, old_tree.update())
        self.failUnlessExists('checkout/file')
        self.assertEqual(['A'], old_tree.get_parent_ids())

    def test_update_sets_root_id(self):
        """Ensure tree root is set properly by update.
        
        Since empty trees don't have root_ids, but workingtrees do,
        an update of a checkout of revision 0 to a new revision,  should set
        the root id.
        """
        wt = self.make_branch_and_tree('tree')
        main_branch = wt.branch
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = main_branch.create_checkout('checkout')
        # now commit to 'tree'
        wt.add('file')
        wt.commit('A', rev_id='A')
        # and update checkout 
        self.assertEqual(0, checkout.update())
        self.failUnlessExists('checkout/file')
        self.assertEqual(wt.get_root_id(), checkout.get_root_id())
        self.assertNotEqual(None, wt.get_root_id())

    def test_update_returns_conflict_count(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        main_branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            main_branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = main_branch.bzrdir.create_workingtree()
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        branch.BranchReferenceFormat().initialize(checkout, main_branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        wt.commit('A', rev_id='A')
        # and add a file file to the checkout
        self.build_tree(['checkout/file'])
        old_tree.add('file')
        # and update old_tree
        self.assertEqual(1, old_tree.update())
        self.assertEqual(['A'], old_tree.get_parent_ids())

    def test_merge_revert(self):
        from bzrlib.merge import merge_inner
        this = self.make_branch_and_tree('b1')
        open('b1/a', 'wb').write('a test\n')
        this.add('a')
        open('b1/b', 'wb').write('b test\n')
        this.add('b')
        this.commit(message='')
        base = this.bzrdir.clone('b2').open_workingtree()
        open('b2/a', 'wb').write('b test\n')
        other = this.bzrdir.clone('b3').open_workingtree()
        open('b3/a', 'wb').write('c test\n')
        open('b3/c', 'wb').write('c test\n')
        other.add('c')

        open('b1/b', 'wb').write('q test\n')
        open('b1/d', 'wb').write('d test\n')
        merge_inner(this.branch, other, base, this_tree=this)
        self.assertNotEqual(open('b1/a', 'rb').read(), 'a test\n')
        this.revert()
        self.assertEqual(open('b1/a', 'rb').read(), 'a test\n')
        self.assertIs(os.path.exists('b1/b.~1~'), True)
        self.assertIs(os.path.exists('b1/c'), False)
        self.assertIs(os.path.exists('b1/a.~1~'), False)
        self.assertIs(os.path.exists('b1/d'), True)

    def test_update_updates_bound_branch_no_local_commits(self):
        # doing an update in a tree updates the branch its bound to too.
        master_tree = self.make_branch_and_tree('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # legacy branches cannot bind
            return
        master_tree.commit('foo', rev_id='foo', allow_pointless=True)
        tree.update()
        self.assertEqual(['foo'], tree.get_parent_ids())
        self.assertEqual('foo', tree.branch.last_revision())

    def test_update_turns_local_commit_into_merge(self):
        # doing an update with a few local commits and no master commits
        # makes pending-merges. 
        # this is done so that 'bzr update; bzr revert' will always produce
        # an exact copy of the 'logical branch' - the referenced branch for
        # a checkout, and the master for a bound branch.
        # its possible that we should instead have 'bzr update' when there
        # is nothing new on the master leave the current commits intact and
        # alter 'revert' to revert to the master always. But for now, its
        # good.
        master_tree = self.make_branch_and_tree('master')
        master_tip = master_tree.commit('first master commit')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # legacy branches cannot bind
            return
        # sync with master
        tree.update()
        # work locally
        tree.commit('foo', rev_id='foo', allow_pointless=True, local=True)
        tree.commit('bar', rev_id='bar', allow_pointless=True, local=True)
        # sync with master prepatory to committing
        tree.update()
        # which should have pivoted the local tip into a merge
        self.assertEqual([master_tip, 'bar'], tree.get_parent_ids())
        # and the local branch history should match the masters now.
        self.assertEqual(master_tree.branch.revision_history(),
            tree.branch.revision_history())

    def test_merge_modified_detects_corruption(self):
        # FIXME: This doesn't really test that it works; also this is not
        # implementation-independent. mbp 20070226
        tree = self.make_branch_and_tree('master')
        tree._transport.put_bytes('merge-hashes', 'asdfasdf')
        self.assertRaises(errors.MergeModifiedFormatError, tree.merge_modified)

    def test_merge_modified(self):
        # merge_modified stores a map from file id to hash
        tree = self.make_branch_and_tree('tree')
        d = {'file-id': osutils.sha_string('hello')}
        self.build_tree_contents([('tree/somefile', 'hello')])
        tree.lock_write()
        try:
            tree.add(['somefile'], ['file-id'])
            tree.set_merge_modified(d)
            mm = tree.merge_modified()
            self.assertEquals(mm, d)
        finally:
            tree.unlock()
        mm = tree.merge_modified()
        self.assertEquals(mm, d)

    def test_conflicts(self):
        from bzrlib.tests.test_conflicts import example_conflicts
        tree = self.make_branch_and_tree('master')
        try:
            tree.set_conflicts(example_conflicts)
        except UnsupportedOperation:
            raise TestSkipped('set_conflicts not supported')
            
        tree2 = WorkingTree.open('master')
        self.assertEqual(tree2.conflicts(), example_conflicts)
        tree2._transport.put_bytes('conflicts', '')
        self.assertRaises(errors.ConflictFormatError,
                          tree2.conflicts)
        tree2._transport.put_bytes('conflicts', 'a')
        self.assertRaises(errors.ConflictFormatError,
                          tree2.conflicts)

    def make_merge_conflicts(self):
        from bzrlib.merge import merge_inner
        tree = self.make_branch_and_tree('mine')
        file('mine/bloo', 'wb').write('one')
        file('mine/blo', 'wb').write('on')
        tree.add(['bloo', 'blo'])
        tree.commit("blah", allow_pointless=False)
        base = tree.branch.repository.revision_tree(tree.last_revision())
        bzrdir.BzrDir.open("mine").sprout("other")
        file('other/bloo', 'wb').write('two')
        othertree = WorkingTree.open('other')
        othertree.commit('blah', allow_pointless=False)
        file('mine/bloo', 'wb').write('three')
        tree.commit("blah", allow_pointless=False)
        merge_inner(tree.branch, othertree, base, this_tree=tree)
        return tree

    def test_merge_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)

    def test_clear_merge_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        try:
            tree.set_conflicts(ConflictList())
        except UnsupportedOperation:
            raise TestSkipped('unsupported operation')
        self.assertEqual(tree.conflicts(), ConflictList())

    def test_add_conflicts(self):
        tree = self.make_branch_and_tree('tree')
        try:
            tree.add_conflicts([TextConflict('path_a')])
        except UnsupportedOperation:
            raise TestSkipped('unsupported operation')
        self.assertEqual(ConflictList([TextConflict('path_a')]),
                         tree.conflicts())
        tree.add_conflicts([TextConflict('path_a')])
        self.assertEqual(ConflictList([TextConflict('path_a')]), 
                         tree.conflicts())
        tree.add_conflicts([ContentsConflict('path_a')])
        self.assertEqual(ConflictList([ContentsConflict('path_a'), 
                                       TextConflict('path_a')]),
                         tree.conflicts())
        tree.add_conflicts([TextConflict('path_b')])
        self.assertEqual(ConflictList([ContentsConflict('path_a'), 
                                       TextConflict('path_a'),
                                       TextConflict('path_b')]),
                         tree.conflicts())

    def test_revert_clear_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert(["blo"])
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert(["bloo"])
        self.assertEqual(len(tree.conflicts()), 0)

    def test_revert_clear_conflicts2(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert()
        self.assertEqual(len(tree.conflicts()), 0)

    def test_format_description(self):
        tree = self.make_branch_and_tree('tree')
        text = tree._format.get_format_description()
        self.failUnless(len(text))

    def test_branch_attribute_is_not_settable(self):
        # the branch attribute is an aspect of the working tree, not a
        # configurable attribute
        tree = self.make_branch_and_tree('tree')
        def set_branch():
            tree.branch = tree.branch
        self.assertRaises(AttributeError, set_branch)

    def test_list_files_versioned_before_ignored(self):
        """A versioned file matching an ignore rule should not be ignored."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo.pyc'])
        # ensure that foo.pyc is ignored
        self.build_tree_contents([('.bzrignore', 'foo.pyc')])
        tree.add('foo.pyc', 'anid')
        tree.lock_read()
        files = sorted(list(tree.list_files()))
        tree.unlock()
        self.assertEqual((u'.bzrignore', '?', 'file', None), files[0][:-1])
        self.assertEqual((u'foo.pyc', 'V', 'file', 'anid'), files[1][:-1])
        self.assertEqual(2, len(files))

    def test_non_normalized_add_accessible(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise TestSkipped('Filesystem does not support unicode filenames')
        tree = self.make_branch_and_tree('.')
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            tree.add([u'a\u030a'])
            tree.lock_read()
            self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                    [(path, ie.kind) for path,ie in 
                                tree.inventory.iter_entries()])
            tree.unlock()
        finally:
            osutils.normalized_filename = orig

    def test_non_normalized_add_inaccessible(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise TestSkipped('Filesystem does not support unicode filenames')
        tree = self.make_branch_and_tree('.')
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            self.assertRaises(errors.InvalidNormalization,
                tree.add, [u'a\u030a'])
        finally:
            osutils.normalized_filename = orig

    def test__write_inventory(self):
        # The private interface _write_inventory is currently used by transform.
        tree = self.make_branch_and_tree('.')
        # if we write write an inventory then do a walkdirs we should get back
        # missing entries, and actual, and unknowns as appropriate.
        self.build_tree(['present', 'unknown'])
        inventory = Inventory(tree.get_root_id())
        inventory.add_path('missing', 'file', 'missing-id')
        inventory.add_path('present', 'file', 'present-id')
        # there is no point in being able to write an inventory to an unlocked
        # tree object - its a low level api not a convenience api.
        tree.lock_write()
        tree._write_inventory(inventory)
        tree.unlock()
        tree.lock_read()
        try:
            present_stat = os.lstat('present')
            unknown_stat = os.lstat('unknown')
            expected_results = [
                (('', tree.get_root_id()),
                 [('missing', 'missing', 'unknown', None, 'missing-id', 'file'),
                  ('present', 'present', 'file', present_stat, 'present-id', 'file'),
                  ('unknown', 'unknown', 'file', unknown_stat, None, None),
                 ]
                )]
            self.assertEqual(expected_results, list(tree.walkdirs()))
        finally:
            tree.unlock()

    def test_path2id(self):
        # smoke test for path2id
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        self.assertEqual('foo-id', tree.path2id('foo'))
        # the next assertion is for backwards compatability with WorkingTree3,
        # though its probably a bad idea, it makes things work. Perhaps
        # it should raise a deprecation warning?
        self.assertEqual('foo-id', tree.path2id('foo/'))

    def test_filter_unversioned_files(self):
        # smoke test for filter_unversioned_files
        tree = self.make_branch_and_tree('.')
        paths = ['here-and-versioned', 'here-and-not-versioned',
            'not-here-and-versioned', 'not-here-and-not-versioned']
        tree.add(['here-and-versioned', 'not-here-and-versioned'],
            kinds=['file', 'file'])
        self.build_tree(['here-and-versioned', 'here-and-not-versioned'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            set(['not-here-and-not-versioned', 'here-and-not-versioned']),
            tree.filter_unversioned_files(paths))

    def test_detect_real_kind(self):
        # working trees report the real kind of the file on disk, not the kind
        # they had when they were first added
        # create one file of every interesting type
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file', 'directory/'])
        names = ['file', 'directory']
        if has_symlinks():
            os.symlink('target', 'symlink')
            names.append('symlink')
        tree.add(names, [n + '-id' for n in names])
        if tree.supports_tree_reference():
            sub_tree = self.make_branch_and_tree('tree-reference')
            sub_tree.set_root_id('tree-reference-id')
            sub_tree.commit('message')
            names.append('tree-reference')
            tree.add_reference(sub_tree)
        # now when we first look, we should see everything with the same kind
        # with which they were initially added
        for n in names:
            actual_kind = tree.kind(n + '-id')
            self.assertEqual(n, actual_kind)
        # move them around so the names no longer correspond to the types
        os.rename(names[0], 'tmp')
        for i in range(1, len(names)):
            os.rename(names[i], names[i-1])
        os.rename('tmp', names[-1])
        # now look and expect to see the correct types again
        for i in range(len(names)):
            actual_kind = tree.kind(names[i-1] + '-id')
            expected_kind = names[i]
            self.assertEqual(expected_kind, actual_kind)

    def test_stored_kind_with_missing(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/a', 'tree/b/'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        os.unlink('tree/a')
        os.rmdir('tree/b')
        self.assertEqual('file', tree.stored_kind('a-id'))
        self.assertEqual('directory', tree.stored_kind('b-id'))

    def test_missing_file_sha1(self):
        """If a file is missing, its sha1 should be reported as None."""
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['file'])
        tree.add('file', 'file-id')
        tree.commit('file added')
        os.unlink('file')
        self.assertIs(None, tree.get_file_sha1('file-id'))

    def test_no_file_sha1(self):
        """If a file is not present, get_file_sha1 should raise NoSuchId"""
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.assertRaises(errors.NoSuchId, tree.get_file_sha1, 'file-id')
        self.build_tree(['file'])
        tree.add('file', 'file-id')
        tree.commit('foo')
        tree.remove('file')
        self.assertRaises(errors.NoSuchId, tree.get_file_sha1, 'file-id')

    def test_case_sensitive(self):
        """If filesystem is case-sensitive, tree should report this.

        We check case-sensitivity by creating a file with a lowercase name,
        then testing whether it exists with an uppercase name.
        """
        self.build_tree(['filename'])
        if os.path.exists('FILENAME'):
            case_sensitive = False
        else:
            case_sensitive = True
        tree = self.make_branch_and_tree('test')
        if tree.__class__ == WorkingTree2:
            raise TestSkipped('WorkingTree2 is not supported')
        self.assertEqual(case_sensitive, tree.case_sensitive)

    def test_all_file_ids_with_missing(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/a', 'tree/b'])
        tree.add(['a', 'b'], ['a-id', 'b-id'])
        os.unlink('tree/a')
        self.assertEqual(set(['a-id', 'b-id', tree.get_root_id()]),
                         tree.all_file_ids())

    def test_sprout_hardlink(self):
        real_os_link = getattr(os, 'link', None)
        if real_os_link is None:
            raise TestNotApplicable("This platform doesn't provide os.link")
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file'])
        source.add('file')
        source.commit('added file')
        def fake_link(source, target):
            raise OSError(errno.EPERM, 'Operation not permitted')
        os.link = fake_link
        try:
            # Hard-link support is optional, so supplying hardlink=True may
            # or may not raise an exception.  But if it does, it must be
            # HardLinkNotSupported
            try:
                source.bzrdir.sprout('target', accelerator_tree=source,
                                     hardlink=True)
            except errors.HardLinkNotSupported:
                pass
        finally:
            os.link = real_os_link


class TestIllegalPaths(TestCaseWithWorkingTree):

    def test_bad_fs_path(self):
        if osutils.normalizes_filenames():
            # You *can't* create an illegal filename on OSX.
            raise tests.TestNotApplicable('OSX normalizes filenames')
        self.requireFeature(tests.UTF8Filesystem)
        # We require a UTF8 filesystem, because otherwise we would need to get
        # tricky to figure out how to create an illegal filename.
        # \xb5 is an illegal path because it should be \xc2\xb5 for UTF-8
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/subdir/'])
        tree.add('subdir')

        f = open('tree/subdir/m\xb5', 'wb')
        try:
            f.write('trivial\n')
        finally:
            f.close()

        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)

        e = self.assertListRaises(errors.BadFilenameEncoding,
                                  tree.iter_changes, tree.basis_tree(),
                                                     want_unversioned=True)
        # We should display the relative path
        self.assertEqual('subdir/m\xb5', e.filename)
        self.assertEqual(osutils._fs_enc, e.fs_encoding)
