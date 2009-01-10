# Copyright (C) 2005, 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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
import os

from bzrlib import (
    bzrdir,
    conflicts,
    errors,
    workingtree,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.lockdir import LockDir
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.transport import get_transport
from bzrlib.workingtree import (
    TreeEntry,
    TreeDirectory,
    TreeFile,
    TreeLink,
    )


class TestTreeDirectory(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestDefaultFormat(TestCaseWithTransport):

    def test_get_set_default_format(self):
        old_format = workingtree.WorkingTreeFormat.get_default_format()
        # default is 3
        self.assertTrue(isinstance(old_format, workingtree.WorkingTreeFormat3))
        workingtree.WorkingTreeFormat.set_default_format(SampleTreeFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('.')
            dir.create_repository()
            dir.create_branch()
            result = dir.create_workingtree()
            self.assertEqual(result, 'A tree')
        finally:
            workingtree.WorkingTreeFormat.set_default_format(old_format)
        self.assertEqual(old_format, workingtree.WorkingTreeFormat.get_default_format())

    def test_open(self):
        tree = self.make_branch_and_tree('.')
        open_direct = workingtree.WorkingTree.open('.')
        self.assertEqual(tree.basedir, open_direct.basedir)
        open_no_args = workingtree.WorkingTree.open()
        self.assertEqual(tree.basedir, open_no_args.basedir)

    def test_open_containing(self):
        tree = self.make_branch_and_tree('.')
        open_direct, relpath = workingtree.WorkingTree.open_containing('.')
        self.assertEqual(tree.basedir, open_direct.basedir)
        self.assertEqual('', relpath)
        open_no_args, relpath = workingtree.WorkingTree.open_containing()
        self.assertEqual(tree.basedir, open_no_args.basedir)
        self.assertEqual('', relpath)
        open_subdir, relpath = workingtree.WorkingTree.open_containing('subdir')
        self.assertEqual(tree.basedir, open_subdir.basedir)
        self.assertEqual('subdir', relpath)


class SampleTreeFormat(workingtree.WorkingTreeFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Sample tree format."

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """Sample branches cannot be created."""
        t = a_bzrdir.get_workingtree_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A tree'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened tree."


class TestWorkingTreeFormat(TestCaseWithTransport):
    """Tests for the WorkingTreeFormat facility."""

    def test_find_format(self):
        # is the right format object found for a working tree?
        # create a branch with a few known format objects.
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            dir.create_branch()
            format.initialize(dir)
            t = get_transport(url)
            found_format = workingtree.WorkingTreeFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(workingtree.WorkingTreeFormat3(), "bar")
        
    def test_find_format_no_tree(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        SampleTreeFormat().initialize(dir)
        self.assertRaises(errors.UnknownFormatError,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleTreeFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        # make a branch
        format.initialize(dir)
        # register a format for it.
        workingtree.WorkingTreeFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(errors.UnsupportedFormatError, workingtree.WorkingTree.open, '.')
        # but open_downlevel will work
        self.assertEqual(format.open(dir), workingtree.WorkingTree.open_downlevel('.'))
        # unregister the format
        workingtree.WorkingTreeFormat.unregister_format(format)


class TestWorkingTreeFormat3(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat3."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        # we want:
        # format 'Bazaar-NG Working Tree format 3'
        # inventory = blank inventory
        # pending-merges = ''
        # stat-cache = ??
        # no inventory.basis yet
        t = control.get_workingtree_transport(None)
        self.assertEqualDiff('Bazaar-NG Working Tree format 3',
                             t.get('format').read())
        self.assertEqualDiff(t.get('inventory').read(), 
                              '<inventory format="5">\n'
                              '</inventory>\n',
                             )
        self.assertEqualDiff('### bzr hashcache v5\n',
                             t.get('stat-cache').read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        # TODO RBC 20060210 do a commit, check the inventory.basis is created 
        # correctly and last-revision file becomes present.

    def test_uses_lockdir(self):
        """WorkingTreeFormat3 uses its own LockDir:
            
            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        t = self.get_transport()
        url = self.get_url()
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        repo = dir.create_repository()
        branch = dir.create_branch()
        try:
            tree = workingtree.WorkingTreeFormat3().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEquals(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEquals(our_lock.peek(), None)

    def test_missing_pending_merges(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        tree._transport.delete("pending-merges")
        self.assertEqual([], tree.get_parent_ids())


class TestFormat2WorkingTree(TestCaseWithTransport):
    """Tests that are specific to format 2 trees."""

    def create_format2_tree(self, url):
        return self.make_branch_and_tree(
            url, format=bzrdir.BzrDirFormat6())

    def test_conflicts(self):
        # test backwards compatability
        tree = self.create_format2_tree('.')
        self.assertRaises(errors.UnsupportedOperation, tree.set_conflicts,
                          None)
        file('lala.BASE', 'wb').write('labase')
        expected = conflicts.ContentsConflict('lala')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala', 'wb').write('la')
        tree.add('lala', 'lala-id')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala.THIS', 'wb').write('lathis')
        file('lala.OTHER', 'wb').write('laother')
        # When "text conflict"s happen, stem, THIS and OTHER are text
        expected = conflicts.TextConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        os.unlink('lala.OTHER')
        os.mkdir('lala.OTHER')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])


class InstrumentedTree(object):
    """A instrumented tree to check the needs_tree_write_lock decorator."""

    def __init__(self):
        self._locks = []

    def lock_tree_write(self):
        self._locks.append('t')

    @needs_tree_write_lock
    def method_with_tree_write_lock(self, *args, **kwargs):
        """A lock_tree_write decorated method that returns its arguments."""
        return args, kwargs

    @needs_tree_write_lock
    def method_that_raises(self):
        """This method causes an exception when called with parameters.
        
        This allows the decorator code to be checked - it should still call
        unlock.
        """

    def unlock(self):
        self._locks.append('u')


class TestInstrumentedTree(TestCase):

    def test_needs_tree_write_lock(self):
        """@needs_tree_write_lock should be semantically transparent."""
        tree = InstrumentedTree()
        self.assertEqual(
            'method_with_tree_write_lock',
            tree.method_with_tree_write_lock.__name__)
        self.assertEqual(
            "A lock_tree_write decorated method that returns its arguments.",
            tree.method_with_tree_write_lock.__doc__)
        args = (1, 2, 3)
        kwargs = {'a':'b'}
        result = tree.method_with_tree_write_lock(1,2,3, a='b')
        self.assertEqual((args, kwargs), result)
        self.assertEqual(['t', 'u'], tree._locks)
        self.assertRaises(TypeError, tree.method_that_raises, 'foo')
        self.assertEqual(['t', 'u', 't', 'u'], tree._locks)


class TestRevert(TestCaseWithTransport):

    def test_revert_conflicts_recursive(self):
        this_tree = self.make_branch_and_tree('this-tree')
        self.build_tree_contents([('this-tree/foo/',),
                                  ('this-tree/foo/bar', 'bar')])
        this_tree.add(['foo', 'foo/bar'])
        this_tree.commit('created foo/bar')
        other_tree = this_tree.bzrdir.sprout('other-tree').open_workingtree()
        self.build_tree_contents([('other-tree/foo/bar', 'baz')])
        other_tree.commit('changed bar')
        self.build_tree_contents([('this-tree/foo/bar', 'qux')])
        this_tree.commit('changed qux')
        this_tree.merge_from_branch(other_tree.branch)
        self.assertEqual(1, len(this_tree.conflicts()))
        this_tree.revert(['foo'])
        self.assertEqual(0, len(this_tree.conflicts()))


class TestAutoResolve(TestCaseWithTransport):

    def test_auto_resolve(self):
        base = self.make_branch_and_tree('base')
        self.build_tree_contents([('base/hello', 'Hello')])
        base.add('hello', 'hello_id')
        base.commit('Hello')
        other = base.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/hello', 'hELLO')])
        other.commit('Case switch')
        this = base.bzrdir.sprout('this').open_workingtree()
        self.failUnlessExists('this/hello')
        self.build_tree_contents([('this/hello', 'Hello World')])
        this.commit('Add World')
        this.merge_from_branch(other.branch)
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         this.conflicts())
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '<<<<<<<')])
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '=======')])
        this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         this.conflicts())
        self.build_tree_contents([('this/hello', '\n>>>>>>>')])
        remaining, resolved = this.auto_resolve()
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         this.conflicts())
        self.assertEqual([], resolved)
        self.build_tree_contents([('this/hello', 'hELLO wORLD')])
        remaining, resolved = this.auto_resolve()
        self.assertEqual([], this.conflicts())
        self.assertEqual([conflicts.TextConflict('hello', None, 'hello_id')],
                         resolved)
        self.failIfExists('this/hello.BASE')

    def test_auto_resolve_dir(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello/'])
        tree.add('hello', 'hello-id')
        file_conflict = conflicts.TextConflict('file', None, 'hello-id')
        tree.set_conflicts(conflicts.ConflictList([file_conflict]))
        tree.auto_resolve()


class TestFindTrees(TestCaseWithTransport):

    def test_find_trees(self):
        self.make_branch_and_tree('foo')
        self.make_branch_and_tree('foo/bar')
        # Sticking a tree inside a control dir is heinous, so let's skip it
        self.make_branch_and_tree('foo/.bzr/baz')
        self.make_branch('qux')
        trees = workingtree.WorkingTree.find_trees('.')
        self.assertEqual(2, len(list(trees)))
