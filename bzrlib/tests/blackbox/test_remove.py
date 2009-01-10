# Copyright (C) 2005, 2006 Canonical Ltd
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
import sys

from bzrlib.tests import SymlinkFeature, TestSkipped
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree
from bzrlib import osutils

_id='-id'
a='a'
b='b/'
c='b/c'
d='d/'
files=(a, b, c, d)


class TestRemove(ExternalBase):

    def _make_tree_and_add(self, paths):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        try:
            self.build_tree(paths)
            for path in paths:
                file_id=str(path).replace('/', '_') + _id
                tree.add(path, file_id)
        finally:
            tree.unlock()
        return tree

    def assertFilesDeleted(self, files):
        for f in files:
            id=f+_id
            self.assertNotInWorkingTree(f)
            self.failIfExists(f)

    def assertFilesUnversioned(self, files):
        for f in files:
            self.assertNotInWorkingTree(f)
            self.failUnlessExists(f)

    def changeFile(self, file_name):
        f = file(file_name, 'ab')
        f.write("\nsome other new content!")
        f.close()

    def run_bzr_remove_changed_files(self, error_regexes, files_to_remove):
        error_regexes.extend(["Can't safely remove modified or unknown files:",
            'Use --keep to not delete them,'
            ' or --force to delete them regardless.'
            ])
        self.run_bzr_error(error_regexes,
            ['remove'] + list(files_to_remove))
        #see if we can force it now
        self.run_bzr(['remove', '--force'] + list(files_to_remove))

    def test_remove_new_no_files_specified(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr_error(["bzr: ERROR: No matching files."], 'remove --new')
        self.run_bzr_error(["bzr: ERROR: No matching files."], 'remove --new .')

    def test_remove_no_files_specified(self):
        tree = self._make_tree_and_add(['foo'])
        out, err = self.run_bzr(['rm'])
        self.assertEqual('', err)
        self.assertEqual('', out)
        self.assertInWorkingTree('foo', tree=tree)
        self.failUnlessExists('foo')

    def test_remove_no_files_specified_missing_dir_and_contents(self):
        tree = self._make_tree_and_add(
            ['foo', 'dir/', 'dir/missing/', 'dir/missing/child'])
        self.get_transport('.').delete_tree('dir/missing')
        out, err = self.run_bzr(['rm'])
        self.assertEqual('', out)
        self.assertEqual(
            'removed dir/missing/child\n'
            'removed dir/missing\n',
            err)
        # non-missing paths not touched:
        self.assertInWorkingTree('foo', tree=tree)
        self.failUnlessExists('foo')
        self.assertInWorkingTree('dir', tree=tree)
        self.failUnlessExists('dir')
        # missing files unversioned
        self.assertNotInWorkingTree('dir/missing', tree=tree)
        self.assertNotInWorkingTree('dir/missing/child', tree=tree)

    def test_remove_no_files_specified_already_deleted(self):
        tree = self._make_tree_and_add(['foo', 'bar'])
        tree.commit('save foo and bar')
        os.unlink('bar')
        self.run_bzr(['rm'])
        self.assertEqual(None, tree.path2id('bar'))
        # Running rm with a deleted file does not error.
        out, err = self.run_bzr(['rm'])
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_remove_no_files_specified_missing_file(self):
        tree = self._make_tree_and_add(['foo', 'bar'])
        os.unlink('bar')
        out, err = self.run_bzr(['rm'])
        self.assertEqual('', out)
        self.assertEqual('removed bar\n', err)
        # non-missing files not touched:
        self.assertInWorkingTree('foo', tree=tree)
        self.failUnlessExists('foo')
        # missing files unversioned
        self.assertNotInWorkingTree('bar', tree=tree)

    def test_remove_no_files_specified_missing_link(self):
        self.requireFeature(SymlinkFeature)
        tree = self._make_tree_and_add(['foo'])
        os.symlink('foo', 'linkname')
        tree.add(['linkname'])
        os.unlink('linkname')
        out, err = self.run_bzr(['rm'])
        self.assertEqual('', out)
        self.assertEqual('removed linkname\n', err)
        # non-missing files not touched:
        self.assertInWorkingTree('foo', tree=tree)
        self.failUnlessExists('foo')
        # missing files unversioned
        self.assertNotInWorkingTree('linkname', tree=tree)

    def test_rm_one_file(self):
        tree = self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr('rm a', error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_one_file(self):
        tree = self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        self.run_bzr('remove a', error_regexes=["deleted a"])
        self.assertFilesDeleted([a])

    def test_remove_keep_one_file(self):
        tree = self._make_tree_and_add([a])
        self.run_bzr('remove --keep a', error_regexes=["removed a"])
        self.assertFilesUnversioned([a])

    def test_remove_one_deleted_file(self):
        tree = self._make_tree_and_add([a])
        self.run_bzr("commit -m 'added a'")
        os.unlink(a)
        self.assertInWorkingTree(a)
        self.run_bzr('remove a')
        self.assertNotInWorkingTree(a)

    def test_remove_invalid_files(self):
        self.build_tree(files)
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['remove', '.', 'xyz', 'abc/def'])

    def test_remove_unversioned_files(self):
        self.build_tree(files)
        tree = self.make_branch_and_tree('.')
        self.run_bzr_remove_changed_files(
            ['unknown:[.\s]*d/[.\s]*b/c[.\s]*b/[.\s]*a'], files)

    def test_remove_changed_files(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.changeFile(a)
        self.changeFile(c)
        self.run_bzr_remove_changed_files(['modified:[.\s]*a[.\s]*b/c'], files)

    def test_remove_changed_ignored_files(self):
        tree = self._make_tree_and_add(['a'])
        self.run_bzr(['ignore', 'a'])
        self.run_bzr_remove_changed_files(['added:[.\s]*a'], ['a'])

    def test_remove_changed_files_from_child_dir(self):
        if sys.platform == 'win32':
            raise TestSkipped("Windows unable to remove '.' directory")
        tree = self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.changeFile(a)
        self.changeFile(c)
        os.chdir('b')
        self.run_bzr_remove_changed_files(['modified:[.\s]*a[.\s]*b/c'],
            ['../a', 'c', '.', '../d'])
        os.chdir('..')
        self.assertNotInWorkingTree(files)
        self.failIfExists(files)

    def test_remove_keep_unversioned_files(self):
        self.build_tree(files)
        tree = self.make_branch_and_tree('.')
        self.run_bzr('remove --keep a', error_regexes=["a is not versioned."])
        self.assertFilesUnversioned(files)

    def test_remove_force_unversioned_files(self):
        self.build_tree(files)
        tree = self.make_branch_and_tree('.')
        self.run_bzr(['remove', '--force'] + list(files),
                     error_regexes=["deleted a", "deleted b",
                                    "deleted b/c", "deleted d"])
        self.assertFilesDeleted(files)

    def test_remove_deleted_files(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        my_files=[f for f in files]
        my_files.sort(reverse=True)
        for f in my_files:
            osutils.delete_any(f)
        self.assertInWorkingTree(files)
        self.failIfExists(files)
        self.run_bzr('remove ' + ' '.join(files))
        self.assertNotInWorkingTree(a)
        self.failIfExists(files)

    def test_remove_non_existing_files(self):
        tree = self._make_tree_and_add([])
        self.run_bzr(['remove', 'b'])

    def test_remove_keep_non_existing_files(self):
        tree = self._make_tree_and_add([])
        self.run_bzr('remove --keep b', error_regexes=["b is not versioned."])

    def test_remove_files(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr('remove a b b/c d',
                     error_regexes=["deleted a", "deleted b", "deleted b/c",
                     "deleted d"])
        self.assertFilesDeleted(files)

    def test_remove_keep_files(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr("commit -m 'added files'")
        self.run_bzr('remove --keep a b b/c d',
                     error_regexes=["removed a", "removed b", "removed b/c",
                     "removed d"])
        self.assertFilesUnversioned(files)

    def test_remove_with_new(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr('remove --new --keep',
                     error_regexes=["removed a", "removed b", "removed b/c"])
        self.assertFilesUnversioned(files)

    def test_remove_with_new_in_dir1(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr('remove --new --keep b b/c',
                     error_regexes=["removed b", "removed b/c"])
        tree = WorkingTree.open('.')
        self.assertInWorkingTree(a)
        self.assertEqual(tree.path2id(a), a + _id)
        self.assertFilesUnversioned([b,c])

    def test_remove_with_new_in_dir2(self):
        tree = self._make_tree_and_add(files)
        self.run_bzr('remove --new --keep .',
                     error_regexes=["removed a", "removed b", "removed b/c"])
        tree = WorkingTree.open('.')
        self.assertFilesUnversioned(files)
