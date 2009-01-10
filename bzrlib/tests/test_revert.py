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

import os

from bzrlib import merge, tests, transform, workingtree


class TestRevert(tests.TestCaseWithTransport):
    """Ensure that revert behaves as expected"""

    def test_revert_merged_dir(self):
        """Reverting a merge that adds a directory deletes the directory"""
        source_tree = self.make_branch_and_tree('source')
        source_tree.commit('empty tree')
        target_tree = source_tree.bzrdir.sprout('target').open_workingtree()
        self.build_tree(['source/dir/', 'source/dir/contents'])
        source_tree.add(['dir', 'dir/contents'], ['dir-id', 'contents-id'])
        source_tree.commit('added dir')
        target_tree.lock_write()
        self.addCleanup(target_tree.unlock)
        merge.merge_inner(target_tree.branch, source_tree.basis_tree(), 
                          target_tree.basis_tree(), this_tree=target_tree)
        self.failUnlessExists('target/dir')
        self.failUnlessExists('target/dir/contents')
        target_tree.revert()
        self.failIfExists('target/dir/contents')
        self.failIfExists('target/dir')

    def test_revert_new(self):
        """Only locally-changed new files should be preserved when reverting

        When a file isn't present in revert's target tree:
        If a file hasn't been committed, revert should unversion it, but not
        delete it.
        If a file has local changes, revert should unversion it, but not
        delete it.
        If a file has no changes from the last commit, revert should delete it.
        If a file has changes due to a merge, revert should delete it.
        """
        tree = self.make_branch_and_tree('tree')
        tree.commit('empty tree')
        merge_target = tree.bzrdir.sprout('merge_target').open_workingtree()
        self.build_tree(['tree/new_file'])

        # newly-added files should not be deleted
        tree.add('new_file')
        basis_tree = tree.branch.repository.revision_tree(tree.last_revision())
        tree.revert()
        self.failUnlessExists('tree/new_file')

        # unchanged files should be deleted
        tree.add('new_file')
        tree.commit('add new_file')
        tree.revert(old_tree=basis_tree)
        self.failIfExists('tree/new_file')
        
        # files should be deleted if their changes came from merges
        merge_target.merge_from_branch(tree.branch)
        self.failUnlessExists('merge_target/new_file')
        merge_target.revert()
        self.failIfExists('merge_target/new_file')

        # files should not be deleted if changed after a merge
        merge_target.merge_from_branch(tree.branch)
        self.failUnlessExists('merge_target/new_file')
        self.build_tree_contents([('merge_target/new_file', 'new_contents')])
        merge_target.revert()
        self.failUnlessExists('merge_target/new_file')

    def tree_with_executable(self):
        tree = self.make_branch_and_tree('tree')
        tt = transform.TreeTransform(tree)
        tt.new_file('newfile', tt.root, 'helooo!', 'newfile-id', True)
        tt.apply()
        tree.lock_write()
        try:
            self.assertTrue(tree.is_executable('newfile-id'))
            tree.commit('added newfile')
        finally:
            tree.unlock()
        return tree

    def test_preserve_execute(self):
        tree = self.tree_with_executable()
        tt = transform.TreeTransform(tree)
        newfile = tt.trans_id_tree_file_id('newfile-id')
        tt.delete_contents(newfile)
        tt.create_file('Woooorld!', newfile)
        tt.apply()
        tree = workingtree.WorkingTree.open('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.assertTrue(tree.is_executable('newfile-id'))
        transform.revert(tree, tree.basis_tree(), None, backups=True)
        self.assertEqual('helooo!', tree.get_file('newfile-id').read())
        self.assertTrue(tree.is_executable('newfile-id'))

    def test_revert_executable(self):
        tree = self.tree_with_executable()
        tt = transform.TreeTransform(tree)
        newfile = tt.trans_id_tree_file_id('newfile-id')
        tt.set_executability(False, newfile)
        tt.apply()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        transform.revert(tree, tree.basis_tree(), None)
        self.assertTrue(tree.is_executable('newfile-id'))

    def test_revert_deletes_files_from_revert(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add('file')
        tree.commit('added file', rev_id='rev1')
        os.unlink('file')
        tree.commit('removed file')
        self.failIfExists('file')
        tree.revert(old_tree=tree.branch.repository.revision_tree('rev1'))
        self.failUnlessExists('file')
        tree.revert()
        self.failIfExists('file')
        self.assertEqual({}, tree.merge_modified())

    def test_empty_deprecated(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        tree.add('file')
        self.callDeprecated(['Using [] to revert all files is deprecated'
            ' as of bzr 0.91.  Please use None (the default) instead.'],
            tree.revert, [])
        self.assertIs(None, tree.path2id('file'))

    def test_revert_file_in_deleted_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/file1', 'dir/file2'])
        tree.add(['dir', 'dir/file1', 'dir/file2'],
                 ['dir-id', 'file1-id', 'file2-id'])
        tree.commit("Added files")
        os.unlink('dir/file1')
        os.unlink('dir/file2')
        os.rmdir('dir')
        tree.remove(['dir/', 'dir/file1', 'dir/file2'])
        tree.revert(['dir/file1'])
        self.failUnlessExists('dir/file1')
        self.failIfExists('dir/file2')
        self.assertEqual('dir-id', tree.path2id('dir'))
