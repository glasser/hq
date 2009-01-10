# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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


"""Black-box tests for bzr export.
"""

from StringIO import StringIO
import os
import stat
import sys
import tarfile
import zipfile

from bzrlib.export import (
    zip_exporter,
    )
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestExport(ExternalBase):

    def test_tar_export(self):
        tree = self.make_branch_and_tree('tar')
        self.build_tree(['tar/a'])
        tree.add('a')
        self.build_tree_contents([('tar/.bzrrules', '')])
        tree.add('.bzrrules')
        self.build_tree(['tar/.bzr-adir/', 'tar/.bzr-adir/afile'])
        tree.add(['.bzr-adir/', '.bzr-adir/afile'])

        os.chdir('tar')
        self.run_bzr('ignore something')
        tree.commit('1')

        self.failUnless(tree.has_filename('.bzrignore'))
        self.failUnless(tree.has_filename('.bzrrules'))
        self.failUnless(tree.has_filename('.bzr-adir'))
        self.failUnless(tree.has_filename('.bzr-adir/afile'))
        self.run_bzr('export test.tar.gz')
        ball = tarfile.open('test.tar.gz')
        # Make sure the tarball contains 'a', but does not contain
        # '.bzrignore'.
        self.assertEqual(['test/a'], sorted(ball.getnames()))

        if sys.version_info < (2, 5, 2) and sys.platform == 'darwin':
            raise tests.KnownFailure('python %r has a tar related bug, upgrade'
                                     % sys.version_info)
        out, err = self.run_bzr('export --format=tgz --root=test -')
        ball = tarfile.open('', fileobj=StringIO(out))
        self.assertEqual(['test/a'], sorted(ball.getnames()))

    def test_tar_export_unicode(self):
        tree = self.make_branch_and_tree('tar')
        fname = u'\xe5.txt'
        try:
            self.build_tree(['tar/' + fname])
        except UnicodeError:
            raise TestSkipped('Unable to represent path %r' % (fname,))
        tree.add([fname])
        tree.commit('first')

        os.chdir('tar')
        self.run_bzr('export test.tar')
        ball = tarfile.open('test.tar')
        # all paths are prefixed with the base name of the tarball
        self.assertEqual(['test/' + fname.encode('utf8')],
                         sorted(ball.getnames()))

    def test_zip_export(self):
        tree = self.make_branch_and_tree('zip')
        self.build_tree(['zip/a'])
        tree.add('a')
        self.build_tree_contents([('zip/.bzrrules', '')])
        tree.add('.bzrrules')
        self.build_tree(['zip/.bzr-adir/', 'zip/.bzr-adir/afile'])
        tree.add(['.bzr-adir/', '.bzr-adir/afile'])

        os.chdir('zip')
        self.run_bzr('ignore something')
        tree.commit('1')

        self.failUnless(tree.has_filename('.bzrignore'))
        self.failUnless(tree.has_filename('.bzrrules'))
        self.failUnless(tree.has_filename('.bzr-adir'))
        self.failUnless(tree.has_filename('.bzr-adir/afile'))
        self.run_bzr('export test.zip')

        zfile = zipfile.ZipFile('test.zip')
        # Make sure the zipfile contains 'a', but does not contain
        # '.bzrignore'.
        self.assertEqual(['test/a'], sorted(zfile.namelist()))

    def test_zip_export_unicode(self):
        tree = self.make_branch_and_tree('zip')
        fname = u'\xe5.txt'
        try:
            self.build_tree(['zip/' + fname])
        except UnicodeError:
            raise TestSkipped('Unable to represent path %r' % (fname,))
        tree.add([fname])
        tree.commit('first')

        os.chdir('zip')
        self.run_bzr('export test.zip')
        zfile = zipfile.ZipFile('test.zip')
        # all paths are prefixed with the base name of the zipfile
        self.assertEqual(['test/' + fname.encode('utf8')],
                         sorted(zfile.namelist()))

    def test_zip_export_directories(self):
        tree = self.make_branch_and_tree('zip')
        self.build_tree(['zip/a', 'zip/b/', 'zip/b/c', 'zip/d/'])
        tree.add(['a', 'b', 'b/c', 'd'])
        tree.commit('init')

        os.chdir('zip')
        self.run_bzr('export test.zip')
        zfile = zipfile.ZipFile('test.zip')
        names = sorted(zfile.namelist())

        # even on win32, zipfile.ZipFile changes all names to use
        # forward slashes
        self.assertEqual(['test/a', 'test/b/', 'test/b/c', 'test/d/'], names)

        file_attr = stat.S_IFREG
        dir_attr = stat.S_IFDIR | zip_exporter.ZIP_DIRECTORY_BIT

        a_info = zfile.getinfo(names[0])
        self.assertEqual(file_attr, a_info.external_attr)

        b_info = zfile.getinfo(names[1])
        self.assertEqual(dir_attr, b_info.external_attr)

        c_info = zfile.getinfo(names[2])
        self.assertEqual(file_attr, c_info.external_attr)

        d_info = zfile.getinfo(names[3])
        self.assertEqual(dir_attr, d_info.external_attr)

    def test_dir_export(self):
        tree = self.make_branch_and_tree('dir')
        self.build_tree(['dir/a'])
        tree.add('a')
        self.build_tree_contents([('dir/.bzrrules', '')])
        tree.add('.bzrrules')
        self.build_tree(['dir/.bzr-adir/', 'dir/.bzr-adir/afile'])
        tree.add(['.bzr-adir/', '.bzr-adir/afile'])

        os.chdir('dir')
        self.run_bzr('ignore something')
        tree.commit('1')

        self.failUnless(tree.has_filename('.bzrignore'))
        self.failUnless(tree.has_filename('.bzrrules'))
        self.failUnless(tree.has_filename('.bzr-adir'))
        self.failUnless(tree.has_filename('.bzr-adir/afile'))
        self.run_bzr('export direxport')

        files = sorted(os.listdir('direxport'))
        # Make sure the exported directory contains 'a', but does not contain
        # '.bzrignore'.
        self.assertEqual(['a'], files)

    def example_branch(self):
        """Create a branch a 'branch' containing hello and goodbye."""
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/hello', 'foo')])
        tree.add('hello')
        tree.commit('setup')

        self.build_tree_contents([('branch/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit('setup')
        return tree
        
    def test_basic_directory_export(self):
        self.example_branch()
        os.chdir('branch')

        # Directory exports
        self.run_bzr('export ../latest')
        self.assertEqual(['goodbye', 'hello'], sorted(os.listdir('../latest')))
        self.check_file_contents('../latest/goodbye', 'baz')
        self.run_bzr('export ../first -r 1')
        self.assertEqual(['hello'], sorted(os.listdir('../first')))
        self.check_file_contents('../first/hello', 'foo')

        # Even with .gz and .bz2 it is still a directory
        self.run_bzr('export ../first.gz -r 1')
        self.check_file_contents('../first.gz/hello', 'foo')
        self.run_bzr('export ../first.bz2 -r 1')
        self.check_file_contents('../first.bz2/hello', 'foo')

    def test_basic_tarfile_export(self):
        self.example_branch()
        os.chdir('branch')

        self.run_bzr('export ../first.tar -r 1')
        self.failUnless(os.path.isfile('../first.tar'))
        tf = tarfile.open('../first.tar')
        try:
            self.assertEqual(['first/hello'], sorted(tf.getnames()))
            self.assertEqual('foo', tf.extractfile('first/hello').read())
        finally:
            tf.close()

        self.run_bzr('export ../first.tar.gz -r 1')
        self.failUnless(os.path.isfile('../first.tar.gz'))
        self.run_bzr('export ../first.tbz2 -r 1')
        self.failUnless(os.path.isfile('../first.tbz2'))
        self.run_bzr('export ../first.tar.bz2 -r 1')
        self.failUnless(os.path.isfile('../first.tar.bz2'))
        self.run_bzr('export ../first.tar.tbz2 -r 1')
        self.failUnless(os.path.isfile('../first.tar.tbz2'))

        tf = tarfile.open('../first.tar.tbz2', 'r:bz2')
        try:
            self.assertEqual(['first.tar/hello'], sorted(tf.getnames()))
            self.assertEqual('foo', tf.extractfile('first.tar/hello').read())
        finally:
            tf.close()
        self.run_bzr('export ../first2.tar -r 1 --root pizza')
        tf = tarfile.open('../first2.tar')
        try:
            self.assertEqual(['pizza/hello'], sorted(tf.getnames()))
            self.assertEqual('foo', tf.extractfile('pizza/hello').read())
        finally:
            tf.close()

    def test_basic_zipfile_export(self):
        self.example_branch()
        os.chdir('branch')

        self.run_bzr('export ../first.zip -r 1')
        self.failUnlessExists('../first.zip')
        zf = zipfile.ZipFile('../first.zip')
        try:
            self.assertEqual(['first/hello'], sorted(zf.namelist()))
            self.assertEqual('foo', zf.read('first/hello'))
        finally:
            zf.close()

        self.run_bzr('export ../first2.zip -r 1 --root pizza')
        zf = zipfile.ZipFile('../first2.zip')
        try:
            self.assertEqual(['pizza/hello'], sorted(zf.namelist()))
            self.assertEqual('foo', zf.read('pizza/hello'))
        finally:
            zf.close()
        
        self.run_bzr('export ../first-zip --format=zip -r 1')
        zf = zipfile.ZipFile('../first-zip')
        try:
            self.assertEqual(['first-zip/hello'], sorted(zf.namelist()))
            self.assertEqual('foo', zf.read('first-zip/hello'))
        finally:
            zf.close()

    def test_export_from_outside_branch(self):
        self.example_branch()

        # Use directory exports to test stating the branch location
        self.run_bzr('export latest branch')
        self.assertEqual(['goodbye', 'hello'], sorted(os.listdir('latest')))
        self.check_file_contents('latest/goodbye', 'baz')
        self.run_bzr('export first -r 1 branch')
        self.assertEqual(['hello'], sorted(os.listdir('first')))
        self.check_file_contents('first/hello', 'foo')

    def test_export_partial_tree(self):
        tree = self.example_branch()
        self.build_tree(['branch/subdir/', 'branch/subdir/foo.txt'])
        tree.smart_add(['branch'])
        tree.commit('more setup')
        out, err = self.run_bzr('export exported branch/subdir')
        self.assertEqual(['foo.txt'], os.listdir('exported'))
