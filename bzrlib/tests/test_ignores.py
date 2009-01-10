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

"""Tests for handling of ignore files"""

from cStringIO import StringIO

from bzrlib import config, errors, ignores
from bzrlib.tests import TestCase, TestCaseInTempDir, TestCaseWithTransport


class TestParseIgnoreFile(TestCase):

    def test_parse_fancy(self):
        ignored = ignores.parse_ignore_file(StringIO(
                './rootdir\n'
                'randomfile*\n'
                'path/from/ro?t\n'
                'unicode\xc2\xb5\n' # u'\xb5'.encode('utf8')
                'dos\r\n'
                '\n' # empty line
                '#comment\n'
                ' xx \n' # whitespace
                ))
        self.assertEqual(set(['./rootdir',
                          'randomfile*',
                          'path/from/ro?t',
                          u'unicode\xb5',
                          'dos',
                          ' xx ',
                         ]), ignored)

    def test_parse_empty(self):
        ignored = ignores.parse_ignore_file(StringIO(''))
        self.assertEqual(set([]), ignored)


class TestUserIgnores(TestCaseInTempDir):
    
    def test_create_if_missing(self):
        # $HOME should be set to '.'
        ignore_path = config.user_ignore_config_filename()
        self.failIfExists(ignore_path)
        user_ignores = ignores.get_user_ignores()
        self.assertEqual(set(ignores.USER_DEFAULTS), user_ignores)

        self.failUnlessExists(ignore_path)
        f = open(ignore_path, 'rb')
        try:
            entries = ignores.parse_ignore_file(f)
        finally:
            f.close()
        self.assertEqual(set(ignores.USER_DEFAULTS), entries)

    def test_use_existing(self):
        patterns = ['*.o', '*.py[co]', u'\xe5*']
        ignores._set_user_ignores(patterns)

        user_ignores = ignores.get_user_ignores()
        self.assertEqual(set(patterns), user_ignores)

    def test_use_empty(self):
        ignores._set_user_ignores([])
        ignore_path = config.user_ignore_config_filename()
        self.check_file_contents(ignore_path, '')

        self.assertEqual(set([]), ignores.get_user_ignores())

    def test_set(self):
        patterns = ['*.py[co]', '*.py[oc]']
        ignores._set_user_ignores(patterns)

        self.assertEqual(set(patterns), ignores.get_user_ignores())

        patterns = ['vim', '*.swp']
        ignores._set_user_ignores(patterns)
        self.assertEqual(set(patterns), ignores.get_user_ignores())

    def test_add(self):
        """Test that adding will not duplicate ignores"""
        # Create an empty file
        ignores._set_user_ignores([])

        patterns = ['foo', './bar', u'b\xe5z']
        added = ignores.add_unique_user_ignores(patterns)
        self.assertEqual(patterns, added)
        self.assertEqual(set(patterns), ignores.get_user_ignores())

    def test_add_directory(self):
        """Test that adding a directory will strip any trailing slash"""
        # Create an empty file
        ignores._set_user_ignores([])

        in_patterns = ['foo/', 'bar/', 'baz\\']
        added = ignores.add_unique_user_ignores(in_patterns)
        out_patterns = [ x.rstrip('/\\') for x in in_patterns ]
        self.assertEqual(out_patterns, added)
        self.assertEqual(set(out_patterns), ignores.get_user_ignores())

    def test_add_unique(self):
        """Test that adding will not duplicate ignores"""
        ignores._set_user_ignores(
            ['foo', './bar', u'b\xe5z', 'dir1/', 'dir3\\'])

        added = ignores.add_unique_user_ignores(
            ['xxx', './bar', 'xxx', 'dir1/', 'dir2/', 'dir3\\'])
        self.assertEqual(['xxx', 'dir2'], added)
        self.assertEqual(set(['foo', './bar', u'b\xe5z', 
                              'xxx', 'dir1', 'dir2', 'dir3']),
                         ignores.get_user_ignores())


class TestRuntimeIgnores(TestCase):

    def setUp(self):
        TestCase.setUp(self)

        orig = ignores._runtime_ignores
        def restore():
            ignores._runtime_ignores = orig
        self.addCleanup(restore)
        # For the purposes of these tests, we must have no
        # runtime ignores
        ignores._runtime_ignores = set()

    def test_add(self):
        """Test that we can add an entry to the list."""
        self.assertEqual(set(), ignores.get_runtime_ignores())

        ignores.add_runtime_ignores(['foo'])
        self.assertEqual(set(['foo']), ignores.get_runtime_ignores())

    def test_add_duplicate(self):
        """Adding the same ignore twice shouldn't add a new entry."""
        ignores.add_runtime_ignores(['foo', 'bar'])
        self.assertEqual(set(['foo', 'bar']), ignores.get_runtime_ignores())

        ignores.add_runtime_ignores(['bar'])
        self.assertEqual(set(['foo', 'bar']), ignores.get_runtime_ignores())


class TestTreeIgnores(TestCaseWithTransport):

    def test_new_file(self):
        tree = self.make_branch_and_tree(".")
        ignores.tree_ignores_add_patterns(tree, ["myentry"])
        self.assertTrue(tree.has_filename(".bzrignore"))
        self.assertEquals("myentry\n", 
                          open(".bzrignore", 'r').read())

    def test_add_to_existing(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([('.bzrignore', "myentry1\n")]) 
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry2", "foo"])
        self.assertEquals("myentry1\nmyentry2\nfoo\n", 
                          open(".bzrignore", 'r').read())

    def test_adds_ending_newline(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([('.bzrignore', "myentry1")]) 
        tree.add([".bzrignore"])
        ignores.tree_ignores_add_patterns(tree, ["myentry2"])
        self.assertEquals("myentry1\nmyentry2\n", 
                          open(".bzrignore", 'r').read())

