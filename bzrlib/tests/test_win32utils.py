# Copyright (C) 2007 Canonical Ltd
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

from bzrlib import osutils
from bzrlib.tests import TestCase, TestCaseInTempDir, TestSkipped, Feature
from bzrlib.win32utils import glob_expand, get_app_path
from bzrlib import win32utils


# Features
# --------

class _NeedsGlobExpansionFeature(Feature):

    def _probe(self):
        return sys.platform == 'win32'

    def feature_name(self):
        return 'Internally performed glob expansion'

NeedsGlobExpansionFeature = _NeedsGlobExpansionFeature()


class _RequiredModuleFeature(Feature):

    def __init__(self, mod_name):
        self.mod_name = mod_name
        super(_RequiredModuleFeature, self).__init__()

    def _probe(self):
        try:
            __import__(self.mod_name)
            return True
        except ImportError:
            return False

    def feature_name(self):
        return self.mod_name

Win32RegistryFeature = _RequiredModuleFeature('_winreg')
CtypesFeature = _RequiredModuleFeature('ctypes')
Win32comShellFeature = _RequiredModuleFeature('win32com.shell')


# Tests
# -----

class TestNeedsGlobExpansionFeature(TestCase):
    
    def test_available(self):
        self.assertEqual(sys.platform == 'win32', 
                         NeedsGlobExpansionFeature.available())
        
    def test_str(self):
        self.assertTrue("performed" in str(NeedsGlobExpansionFeature))


class TestWin32UtilsGlobExpand(TestCaseInTempDir):

    _test_needs_features = [NeedsGlobExpansionFeature]
   
    def test_empty_tree(self):
        self.build_tree([])
        self._run_testset([
            [['a'], ['a']],
            [['?'], ['?']],
            [['*'], ['*']],
            [['a', 'a'], ['a', 'a']]])
        
    def test_tree_ascii(self):
        """Checks the glob expansion and path separation char
        normalization"""
        self.build_tree(['a', 'a1', 'a2', 'a11', 'a.1',
                         'b', 'b1', 'b2', 'b3',
                         'c/', 'c/c1', 'c/c2', 
                         'd/', 'd/d1', 'd/d2', 'd/e/', 'd/e/e1'])
        self._run_testset([
            # no wildcards
            [[u'a'], [u'a']],
            [[u'a', u'a' ], [u'a', u'a']],
            [[u'A'], [u'A']],
                
            [[u'd'], [u'd']],
            [[u'd/'], [u'd/']],
            [[u'd\\'], [u'd/']],
            
            # wildcards
            [[u'a*'], [u'a', u'a1', u'a2', u'a11', u'a.1']],
            [[u'?'], [u'a', u'b', u'c', u'd']],
            [[u'a?'], [u'a1', u'a2']],
            [[u'a??'], [u'a11', u'a.1']],
            [[u'b[1-2]'], [u'b1', u'b2']],
            [[u'A?'], [u'a1', u'a2']],
               
            [[u'd/*'], [u'd/d1', u'd/d2', u'd/e']],
            [[u'd\\*'], [u'd/d1', u'd/d2', u'd/e']],
            [[u'?\\*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*\\*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*/'], [u'c/', u'd/']],
            [[u'*\\'], [u'c/', u'd/']]])
        
    def test_tree_unicode(self):
        """Checks behaviour with non-ascii filenames"""
        self.build_tree([u'\u1234', u'\u1234\u1234', u'\u1235/', u'\u1235/\u1235'])
        self._run_testset([
            # no wildcards
            [[u'\u1234'], [u'\u1234']],
            [[u'\u1235'], [u'\u1235']],
         
            [[u'\u1235/'], [u'\u1235/']],
            [[u'\u1235/\u1235'], [u'\u1235/\u1235']],
            
            # wildcards
            [[u'?'], [u'\u1234', u'\u1235']],
            [[u'*'], [u'\u1234', u'\u1234\u1234', u'\u1235']],
            [[u'\u1234*'], [u'\u1234', u'\u1234\u1234']],
            
            [[u'\u1235/?'], [u'\u1235/\u1235']],
            [[u'\u1235/*'], [u'\u1235/\u1235']],
            [[u'\u1235\\?'], [u'\u1235/\u1235']],
            [[u'\u1235\\*'], [u'\u1235/\u1235']],
            [[u'?/'], [u'\u1235/']],
            [[u'*/'], [u'\u1235/']],
            [[u'?\\'], [u'\u1235/']],
            [[u'*\\'], [u'\u1235/']],
            [[u'?/?'], [u'\u1235/\u1235']],
            [[u'*/*'], [u'\u1235/\u1235']],
            [[u'?\\?'], [u'\u1235/\u1235']],
            [[u'*\\*'], [u'\u1235/\u1235']]])

    def _run_testset(self, testset):
        for pattern, expected in testset:
            result = glob_expand(pattern)
            expected.sort()
            result.sort()
            self.assertEqual(expected, result, 'pattern %s' % pattern)


class TestAppPaths(TestCase):

    _test_needs_features = [Win32RegistryFeature]

    def test_iexplore(self):
        # typical windows users should have IE installed
        for a in ('iexplore', 'iexplore.exe'):
            p = get_app_path(a)
            d, b = os.path.split(p)
            self.assertEquals('iexplore.exe', b.lower())
            self.assertNotEquals('', d)

    def test_not_existing(self):
        p = get_app_path('not-existing')
        self.assertEquals('not-existing', p)


class TestLocationsCtypes(TestCase):

    _test_needs_features = [CtypesFeature]

    def assertPathsEqual(self, p1, p2):
        # TODO: The env var values in particular might return the "short"
        # version (ie, "C:\DOCUME~1\...").  Its even possible the returned
        # values will differ only by case - handle these situations as we
        # come across them.
        self.assertEquals(p1, p2)

    def test_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_appdata_location()
        self._captureVar("APPDATA", None)
        self.assertPathsEqual(first, win32utils.get_appdata_location())
 
    def test_appdata_matches_environment(self):
        # Typically the APPDATA environment variable will match
        # get_appdata_location
        # XXX - See bug 262874, which asserts the correct encoding is 'mbcs',
        encoding = osutils.get_user_encoding()
        env_val = os.environ.get("APPDATA", None)
        if not env_val:
            raise TestSkipped("No APPDATA environment variable exists")
        self.assertPathsEqual(win32utils.get_appdata_location(),
                              env_val.decode(encoding))

    def test_local_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_local_appdata_location()
        self._captureVar("LOCALAPPDATA", None)
        self.assertPathsEqual(first, win32utils.get_local_appdata_location())

    def test_local_appdata_matches_environment(self):
        # LOCALAPPDATA typically only exists on Vista, so we only attempt to
        # compare when it exists.
        lad = win32utils.get_local_appdata_location()
        env = os.environ.get("LOCALAPPDATA")
        if env:
            # XXX - See bug 262874, which asserts the correct encoding is 'mbcs'
            encoding = osutils.get_user_encoding()
            self.assertPathsEqual(lad, env.decode(encoding))


class TestLocationsPywin32(TestLocationsCtypes):

    _test_needs_features = [Win32comShellFeature]

    def setUp(self):
        super(TestLocationsPywin32, self).setUp()
        # We perform the exact same tests after disabling the use of ctypes.
        # This causes the implementation to fall back to pywin32.
        self.old_ctypes = win32utils.has_ctypes
        win32utils.has_ctypes = False
        self.addCleanup(self.restoreCtypes)

    def restoreCtypes(self):
        win32utils.has_ctypes = self.old_ctypes
