# Copyright (C) 2006, 2007, 2008 Canonical Ltd
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


"""Tree implementation tests for bzr.

These test the conformance of all the tree variations to the expected API.
Specific tests for individual variations are in other places such as:
 - tests/test_tree.py
 - tests/test_revision.py
 - tests/test_workingtree.py
 - tests/workingtree_implementations/*.py.
"""

from bzrlib import (
    errors,
    osutils,
    progress,
    tests,
    transform,
    )
from bzrlib.transport import get_transport
from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestCaseWithTransport,
                          TestSkipped,
                          )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.tests.workingtree_implementations import (
    WorkingTreeTestProviderAdapter,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.revisiontree import RevisionTree
from bzrlib.transform import TransformPreview
from bzrlib.workingtree import (
    WorkingTreeFormat,
    WorkingTreeFormat3,
    _legacy_formats,
    )
from bzrlib.workingtree_4 import (
    DirStateRevisionTree,
    WorkingTreeFormat4,
    )


def return_parameter(testcase, something):
    """A trivial thunk to return its input."""
    return something


def revision_tree_from_workingtree(testcase, tree):
    """Create a revision tree from a working tree."""
    revid = tree.commit('save tree', allow_pointless=True, recursive=None)
    return tree.branch.repository.revision_tree(revid)


def _dirstate_tree_from_workingtree(testcase, tree):
    revid = tree.commit('save tree', allow_pointless=True, recursive=None)
    return tree.basis_tree()


def preview_tree_pre(testcase, tree):
    tt = TransformPreview(tree)
    testcase.addCleanup(tt.finalize)
    preview_tree = tt.get_preview_tree()
    preview_tree.set_parent_ids(tree.get_parent_ids())
    return preview_tree


def preview_tree_post(testcase, tree):
    basis = tree.basis_tree()
    tt = TransformPreview(basis)
    testcase.addCleanup(tt.finalize)
    pp = progress.ProgressPhase('', 1, progress.DummyProgress())
    tree.lock_read()
    testcase.addCleanup(tree.unlock)
    transform._prepare_revert_transform(basis, tree, tt, None, False, pp,
                                        basis, {})
    preview_tree = tt.get_preview_tree()
    preview_tree.set_parent_ids(tree.get_parent_ids())
    return preview_tree


class TestTreeImplementationSupport(TestCaseWithTransport):

    def test_revision_tree_from_workingtree(self):
        tree = self.make_branch_and_tree('.')
        tree = revision_tree_from_workingtree(self, tree)
        self.assertIsInstance(tree, RevisionTree)


class TestCaseWithTree(TestCaseWithBzrDir):

    def make_branch_and_tree(self, relpath):
        made_control = self.make_bzrdir(relpath, format=
            self.workingtree_format._matchingbzrdir)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)

    def workingtree_to_test_tree(self, tree):
        return self._workingtree_to_test_tree(self, tree)

    def _convert_tree(self, tree, converter=None):
        """helper to convert using the converter or a supplied one."""
        # convert that to the final shape
        if converter is None:
            converter = self.workingtree_to_test_tree
        return converter(tree)

    def get_tree_no_parents_no_content(self, empty_tree, converter=None):
        """Make a tree with no parents and no contents from empty_tree.
        
        :param empty_tree: A working tree with no content and no parents to
            modify.
        """
        empty_tree.set_root_id('empty-root-id')
        return self._convert_tree(empty_tree, converter)

    def _make_abc_tree(self, tree):
        """setup an abc content tree."""
        files = ['a', 'b/', 'b/c']
        self.build_tree(files, line_endings='binary',
                        transport=tree.bzrdir.root_transport)
        tree.set_root_id('root-id')
        tree.add(files, ['a-id', 'b-id', 'c-id'])

    def get_tree_no_parents_abc_content(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents."""
        self._make_abc_tree(tree)
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_2(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents.
        
        This variation changes the content of 'a' to foobar\n.
        """
        self._make_abc_tree(tree)
        f = open(tree.basedir + '/a', 'wb')
        try:
            f.write('foobar\n')
        finally:
            f.close()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_3(self, tree, converter=None):
        """return a test tree with a, b/, b/c contents.
        
        This variation changes the executable flag of b/c to True.
        """
        self._make_abc_tree(tree)
        tt = transform.TreeTransform(tree)
        trans_id = tt.trans_id_tree_path('b/c')
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_4(self, tree, converter=None):
        """return a test tree with d, b/, b/c contents.
        
        This variation renames a to d.
        """
        self._make_abc_tree(tree)
        tree.rename_one('a', 'd')
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_5(self, tree, converter=None):
        """return a test tree with d, b/, b/c contents.
        
        This variation renames a to d and alters its content to 'bar\n'.
        """
        self._make_abc_tree(tree)
        tree.rename_one('a', 'd')
        f = open(tree.basedir + '/d', 'wb')
        try:
            f.write('bar\n')
        finally:
            f.close()
        return self._convert_tree(tree, converter)

    def get_tree_no_parents_abc_content_6(self, tree, converter=None):
        """return a test tree with a, b/, e contents.
        
        This variation renames b/c to e, and makes it executable.
        """
        self._make_abc_tree(tree)
        tt = transform.TreeTransform(tree)
        trans_id = tt.trans_id_tree_path('b/c')
        parent_trans_id = tt.trans_id_tree_path('')
        tt.adjust_path('e', parent_trans_id, trans_id)
        tt.set_executability(True, trans_id)
        tt.apply()
        return self._convert_tree(tree, converter)

    def get_tree_with_subdirs_and_all_content_types(self):
        """Return a test tree with subdirs and all content types.
        See get_tree_with_subdirs_and_all_supported_content_types for details.
        """
        return self.get_tree_with_subdirs_and_all_supported_content_types(True)

    def get_tree_with_subdirs_and_all_supported_content_types(self, symlinks):
        """Return a test tree with subdirs and all supported content types.
        Some content types may not be created on some platforms
        (like symlinks on native win32)

        :param  symlinks:   control is symlink should be created in the tree.
                            Note: if you wish to automatically set this
                            parameters depending on underlying system,
                            please use value returned
                            by bzrlib.osutils.has_symlinks() function.

        The returned tree has the following inventory:
            [('', inventory.ROOT_ID),
             ('0file', '2file'),
             ('1top-dir', '1top-dir'),
             (u'2utf\u1234file', u'0utf\u1234file'),
             ('symlink', 'symlink'),            # only if symlinks arg is True
             ('1top-dir/0file-in-1topdir', '1file-in-1topdir'),
             ('1top-dir/1dir-in-1topdir', '0dir-in-1topdir')]
        where each component has the type of its name -
        i.e. '1file..' is afile.

        note that the order of the paths and fileids is deliberately 
        mismatched to ensure that the result order is path based.
        """
        tree = self.make_branch_and_tree('.')
        paths = ['0file',
            '1top-dir/',
            u'2utf\u1234file',
            '1top-dir/0file-in-1topdir',
            '1top-dir/1dir-in-1topdir/'
            ]
        ids = [
            '2file',
            '1top-dir',
            u'0utf\u1234file'.encode('utf8'),
            '1file-in-1topdir',
            '0dir-in-1topdir'
            ]
        try:
            self.build_tree(paths)
        except UnicodeError:
            raise TestSkipped(
                'This platform does not support unicode file paths.')
        tree.add(paths, ids)
        tt = transform.TreeTransform(tree)
        if symlinks:
            root_transaction_id = tt.trans_id_tree_path('')
            tt.new_symlink('symlink',
                root_transaction_id, 'link-target', 'symlink')
        tt.apply()
        return self.workingtree_to_test_tree(tree)

    def get_tree_with_utf8(self, tree):
        """Generate a tree with a utf8 revision and unicode paths."""
        self._create_tree_with_utf8(tree)
        return self.workingtree_to_test_tree(tree)

    def _create_tree_with_utf8(self, tree):
        """Generate a tree with a utf8 revision and unicode paths."""
        # We avoid combining characters in file names here, normalization
        # checks (as performed by some file systems (OSX) are outside the scope
        # of these tests).  We use the euro sign \N{Euro Sign} or \u20ac in
        # unicode strings or '\xe2\x82\ac' (its utf-8 encoding) in raw strings.
        paths = [u'',
                 u'fo\N{Euro Sign}o',
                 u'ba\N{Euro Sign}r/',
                 u'ba\N{Euro Sign}r/ba\N{Euro Sign}z',
                ]
        # bzr itself does not create unicode file ids, but we want them for
        # testing.
        file_ids = ['TREE_ROOT',
                    'fo\xe2\x82\xaco-id',
                    'ba\xe2\x82\xacr-id',
                    'ba\xe2\x82\xacz-id',
                   ]
        try:
            self.build_tree(paths[1:])
        except UnicodeError:
            raise tests.TestSkipped('filesystem does not support unicode.')
        if tree.get_root_id() is None:
            # Some trees do not have a root yet.
            tree.add(paths, file_ids)
        else:
            # Some trees will already have a root
            tree.set_root_id(file_ids[0])
            tree.add(paths[1:], file_ids[1:])
        try:
            tree.commit(u'in\xedtial', rev_id=u'r\xe9v-1'.encode('utf8'))
        except errors.NonAsciiRevisionId:
            raise tests.TestSkipped('non-ascii revision ids not supported')

    def get_tree_with_merged_utf8(self, tree):
        """Generate a tree with utf8 ancestors."""
        self._create_tree_with_utf8(tree)
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        self.build_tree([u'tree2/ba\N{Euro Sign}r/qu\N{Euro Sign}x'])
        tree2.add([u'ba\N{Euro Sign}r/qu\N{Euro Sign}x'],
                  [u'qu\N{Euro Sign}x-id'.encode('utf-8')])
        tree2.commit(u'to m\xe9rge', rev_id=u'r\xe9v-2'.encode('utf8'))

        tree.merge_from_branch(tree2.branch)
        tree.commit(u'm\xe9rge', rev_id=u'r\xe9v-3'.encode('utf8'))
        return self.workingtree_to_test_tree(tree)


class TreeTestProviderAdapter(WorkingTreeTestProviderAdapter):
    """Generate test suites for each Tree implementation in bzrlib.

    Currently this covers all working tree formats, and RevisionTree and
    DirStateRevisionTree by committing a working tree to create the revision
    tree.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        """Create a TreeTestProviderAdapter.

        :param formats: [workingtree_format]
        """
        super(TreeTestProviderAdapter, self).__init__(transport_server,
            transport_readonly_server, formats)
        # now adjust the scenarios and add the non-working-tree tree scenarios.
        for scenario in self.scenarios:
            # for working tree adapted tests, preserve the tree
            scenario[1]["_workingtree_to_test_tree"] = return_parameter
        # add RevisionTree scenario
        self.scenarios.append(self.create_tree_scenario(RevisionTree.__name__,
                              revision_tree_from_workingtree,))

        # also test WorkingTree4's RevisionTree implementation which is
        # specialised.
        self.scenarios.append(self.create_tree_scenario(
            DirStateRevisionTree.__name__, _dirstate_tree_from_workingtree,
            WorkingTreeFormat4()))
        self.scenarios.append(self.create_tree_scenario('PreviewTree',
            preview_tree_pre))
        self.scenarios.append(self.create_tree_scenario('PreviewTreePost',
            preview_tree_post))

    def create_tree_scenario(self, name, converter, workingtree_format=None):
        """Create a scenario for the specified converter

        :param name: The name to append to tests using this converter
        :param converter: A function that converts a workingtree into the
            desired format.
        :param workingtree_format: The particular workingtree format to
            convert from.
        :return: a (name, options) tuple, where options is a dict of values
            to be used as members of the TestCase.
        """
        if workingtree_format is None:
            workingtree_format = WorkingTreeFormat._default_format
        scenario_options = WorkingTreeTestProviderAdapter.create_scenario(self,
            workingtree_format)[1]
        scenario_options["_workingtree_to_test_tree"] = converter
        return name, scenario_options


def load_tests(basic_tests, module, loader):
    result = loader.suiteClass()
    # add the tests for this module
    result.addTests(basic_tests)

    test_tree_implementations = [
        'bzrlib.tests.tree_implementations.test_annotate_iter',
        'bzrlib.tests.tree_implementations.test_get_file_mtime',
        'bzrlib.tests.tree_implementations.test_get_root_id',
        'bzrlib.tests.tree_implementations.test_get_symlink_target',
        'bzrlib.tests.tree_implementations.test_inv',
        'bzrlib.tests.tree_implementations.test_iter_search_rules',
        'bzrlib.tests.tree_implementations.test_list_files',
        'bzrlib.tests.tree_implementations.test_path_content_summary',
        'bzrlib.tests.tree_implementations.test_revision_tree',
        'bzrlib.tests.tree_implementations.test_test_trees',
        'bzrlib.tests.tree_implementations.test_tree',
        'bzrlib.tests.tree_implementations.test_walkdirs',
        ]

    adapter = TreeTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        WorkingTreeFormat._formats.values() + _legacy_formats)

    # add the tests for the sub modules
    adapt_modules(test_tree_implementations, adapter, loader, result)
    return result
