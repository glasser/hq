# Copyright (C) 2005 Canonical Ltd
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


"""Tests of simple versioning operations"""

# TODO: test trying to commit within a directory that is not yet added


import os

from bzrlib.tests import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.trace import mutter
from bzrlib.osutils import pathjoin
from bzrlib.workingtree import WorkingTree


class TestVersioning(TestCaseInTempDir):

    def test_mkdir(self):
        """Basic 'bzr mkdir' operation"""

        self.run_bzr('init')
        self.run_bzr('mkdir foo')
        self.assert_(os.path.isdir('foo'))

        self.run_bzr('mkdir foo', retcode=3)

        wt = WorkingTree.open('.')

        delta = wt.changes_from(wt.basis_tree())

        self.log('delta.added = %r' % delta.added)

        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'foo')
        self.failIf(delta.modified)

    def test_mkdir_in_subdir(self):
        """'bzr mkdir' operation in subdirectory"""

        self.run_bzr('init')
        self.run_bzr('mkdir dir')
        self.assert_(os.path.isdir('dir'))

        os.chdir('dir')
        self.log('Run mkdir in subdir')
        self.run_bzr('mkdir subdir')
        self.assert_(os.path.isdir('subdir'))
        os.chdir('..')

        wt = WorkingTree.open('.')

        delta = wt.changes_from(wt.basis_tree())

        self.log('delta.added = %r' % delta.added)

        self.assertEquals(len(delta.added), 2)
        self.assertEquals(delta.added[0][0], 'dir')
        self.assertEquals(delta.added[1][0], pathjoin('dir','subdir'))
        self.failIf(delta.modified)

    def test_mkdir_w_nested_trees(self):
        """'bzr mkdir' with nested trees"""

        self.run_bzr('init')
        os.mkdir('a')
        os.chdir('a')
        self.run_bzr('init')
        os.mkdir('b')
        os.chdir('b')
        self.run_bzr('init')
        os.chdir('../..')

        self.run_bzr('mkdir dir a/dir a/b/dir')
        self.failUnless(os.path.isdir('dir'))
        self.failUnless(os.path.isdir('a/dir'))
        self.failUnless(os.path.isdir('a/b/dir'))

        wt = WorkingTree.open('.')
        wt_a = WorkingTree.open('a')
        wt_b = WorkingTree.open('a/b')

        delta = wt.changes_from(wt.basis_tree())
        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'dir')
        self.failIf(delta.modified)

        delta = wt_a.changes_from(wt_a.basis_tree())
        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'dir')
        self.failIf(delta.modified)

        delta = wt_b.changes_from(wt_b.basis_tree())
        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'dir')
        self.failIf(delta.modified)

    def check_branch(self):
        """After all the above changes, run the check and upgrade commands.

        The upgrade should be a no-op."""
        b = Branch.open(u'.')
        mutter('branch has %d revisions', b.revno())

        mutter('check branch...')
        from bzrlib.check import check
        check(b, False)


class SubdirCommit(TestCaseInTempDir):

    def test_subdir_commit(self):
        """Test committing a subdirectory, and committing within a directory."""
        run_bzr = self.run_bzr
        eq = self.assertEqual

        self.build_tree(['a/', 'b/'])

        run_bzr('init')
        b = Branch.open(u'.')

        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('old contents')

        run_bzr('add')
        run_bzr(['commit', '-m', 'first revision'])

        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('new contents')

        mutter('start selective subdir commit')
        run_bzr(['commit', 'a', '-m', 'commit a only'])

        old = b.repository.revision_tree(b.get_rev_id(1))
        new = b.repository.revision_tree(b.get_rev_id(2))
        new.lock_read()

        eq(new.get_file_by_path('b/two').read(), 'old contents')
        eq(new.get_file_by_path('top').read(), 'old contents')
        eq(new.get_file_by_path('a/one').read(), 'new contents')
        new.unlock()

        os.chdir('a')
        # commit from here should do nothing
        run_bzr(['commit', '.', '-m', 'commit subdir only', '--unchanged'])
        v3 = b.repository.revision_tree(b.get_rev_id(3))
        v3.lock_read()
        eq(v3.get_file_by_path('b/two').read(), 'old contents')
        eq(v3.get_file_by_path('top').read(), 'old contents')
        eq(v3.get_file_by_path('a/one').read(), 'new contents')
        v3.unlock()

        # commit in subdirectory commits whole tree
        run_bzr(['commit', '-m', 'commit whole tree from subdir'])
        v4 = b.repository.revision_tree(b.get_rev_id(4))
        v4.lock_read()
        eq(v4.get_file_by_path('b/two').read(), 'new contents')
        eq(v4.get_file_by_path('top').read(), 'new contents')
        v4.unlock()

        # TODO: factor out some kind of assert_tree_state() method


if __name__ == '__main__':
    import unittest
    unittest.main()
