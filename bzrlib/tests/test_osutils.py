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

"""Tests for the osutils wrapper."""

from cStringIO import StringIO
import errno
import os
import socket
import stat
import sys
import time

from bzrlib import (
    errors,
    osutils,
    tests,
    win32utils,
    )
from bzrlib.errors import BzrBadParameterNotUnicode, InvalidURL
from bzrlib.osutils import (
        is_inside_any,
        is_inside_or_parent_of_any,
        pathjoin,
        pumpfile,
        pump_string_file,
        )
from bzrlib.tests import (
        adapt_tests,
        Feature,
        probe_unicode_in_user_encoding,
        split_suite_by_re,
        StringIOWrapper,
        SymlinkFeature,
        TestCase,
        TestCaseInTempDir,
        TestScenarioApplier,
        TestSkipped,
        )
from bzrlib.tests.file_utils import (
    FakeReadFile,
    )
from bzrlib.tests.test__walkdirs_win32 import Win32ReadDirFeature


class _UTF8DirReaderFeature(Feature):

    def _probe(self):
        try:
            from bzrlib import _readdir_pyx
            self.reader = _readdir_pyx.UTF8DirReader
            return True
        except ImportError:
            return False

    def feature_name(self):
        return 'bzrlib._readdir_pyx'

UTF8DirReaderFeature = _UTF8DirReaderFeature()


class TestOSUtils(TestCaseInTempDir):

    def test_contains_whitespace(self):
        self.failUnless(osutils.contains_whitespace(u' '))
        self.failUnless(osutils.contains_whitespace(u'hello there'))
        self.failUnless(osutils.contains_whitespace(u'hellothere\n'))
        self.failUnless(osutils.contains_whitespace(u'hello\nthere'))
        self.failUnless(osutils.contains_whitespace(u'hello\rthere'))
        self.failUnless(osutils.contains_whitespace(u'hello\tthere'))

        # \xa0 is "Non-breaking-space" which on some python locales thinks it
        # is whitespace, but we do not.
        self.failIf(osutils.contains_whitespace(u''))
        self.failIf(osutils.contains_whitespace(u'hellothere'))
        self.failIf(osutils.contains_whitespace(u'hello\xa0there'))

    def test_fancy_rename(self):
        # This should work everywhere
        def rename(a, b):
            osutils.fancy_rename(a, b,
                    rename_func=os.rename,
                    unlink_func=os.unlink)

        open('a', 'wb').write('something in a\n')
        rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    def test_rename(self):
        # Rename should be semi-atomic on all platforms
        open('a', 'wb').write('something in a\n')
        osutils.rename('a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')
        self.check_file_contents('b', 'something in a\n')

        open('a', 'wb').write('new something in a\n')
        osutils.rename('b', 'a')

        self.check_file_contents('a', 'something in a\n')

    # TODO: test fancy_rename using a MemoryTransport

    def test_rename_change_case(self):
        # on Windows we should be able to change filename case by rename
        self.build_tree(['a', 'b/'])
        osutils.rename('a', 'A')
        osutils.rename('b', 'B')
        # we can't use failUnlessExists on case-insensitive filesystem
        # so try to check shape of the tree
        shape = sorted(os.listdir('.'))
        self.assertEquals(['A', 'B'], shape)

    def test_01_rand_chars_empty(self):
        result = osutils.rand_chars(0)
        self.assertEqual(result, '')

    def test_02_rand_chars_100(self):
        result = osutils.rand_chars(100)
        self.assertEqual(len(result), 100)
        self.assertEqual(type(result), str)
        self.assertContainsRe(result, r'^[a-z0-9]{100}$')

    def test_is_inside(self):
        is_inside = osutils.is_inside
        self.assertTrue(is_inside('src', 'src/foo.c'))
        self.assertFalse(is_inside('src', 'srccontrol'))
        self.assertTrue(is_inside('src', 'src/a/a/a/foo.c'))
        self.assertTrue(is_inside('foo.c', 'foo.c'))
        self.assertFalse(is_inside('foo.c', ''))
        self.assertTrue(is_inside('', 'foo.c'))

    def test_is_inside_any(self):
        SRC_FOO_C = pathjoin('src', 'foo.c')
        for dirs, fn in [(['src', 'doc'], SRC_FOO_C),
                         (['src'], SRC_FOO_C),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_any(dirs, fn))
        for dirs, fn in [(['src'], 'srccontrol'),
                         (['src'], 'srccontrol/foo')]:
            self.assertFalse(is_inside_any(dirs, fn))

    def test_is_inside_or_parent_of_any(self):
        for dirs, fn in [(['src', 'doc'], 'src/foo.c'),
                         (['src'], 'src/foo.c'),
                         (['src/bar.c'], 'src'),
                         (['src/bar.c', 'bla/foo.c'], 'src'),
                         (['src'], 'src'),
                         ]:
            self.assert_(is_inside_or_parent_of_any(dirs, fn))
            
        for dirs, fn in [(['src'], 'srccontrol'),
                         (['srccontrol/foo.c'], 'src'),
                         (['src'], 'srccontrol/foo')]:
            self.assertFalse(is_inside_or_parent_of_any(dirs, fn))

    def test_rmtree(self):
        # Check to remove tree with read-only files/dirs
        os.mkdir('dir')
        f = file('dir/file', 'w')
        f.write('spam')
        f.close()
        # would like to also try making the directory readonly, but at the
        # moment python shutil.rmtree doesn't handle that properly - it would
        # need to chmod the directory before removing things inside it - deferred
        # for now -- mbp 20060505
        # osutils.make_readonly('dir')
        osutils.make_readonly('dir/file')

        osutils.rmtree('dir')

        self.failIfExists('dir/file')
        self.failIfExists('dir')

    def test_file_kind(self):
        self.build_tree(['file', 'dir/'])
        self.assertEquals('file', osutils.file_kind('file'))
        self.assertEquals('directory', osutils.file_kind('dir/'))
        if osutils.has_symlinks():
            os.symlink('symlink', 'symlink')
            self.assertEquals('symlink', osutils.file_kind('symlink'))
        
        # TODO: jam 20060529 Test a block device
        try:
            os.lstat('/dev/null')
        except OSError, e:
            if e.errno not in (errno.ENOENT,):
                raise
        else:
            self.assertEquals('chardev', osutils.file_kind('/dev/null'))

        mkfifo = getattr(os, 'mkfifo', None)
        if mkfifo:
            mkfifo('fifo')
            try:
                self.assertEquals('fifo', osutils.file_kind('fifo'))
            finally:
                os.remove('fifo')

        AF_UNIX = getattr(socket, 'AF_UNIX', None)
        if AF_UNIX:
            s = socket.socket(AF_UNIX)
            s.bind('socket')
            try:
                self.assertEquals('socket', osutils.file_kind('socket'))
            finally:
                os.remove('socket')

    def test_kind_marker(self):
        self.assertEqual(osutils.kind_marker('file'), '')
        self.assertEqual(osutils.kind_marker('directory'), '/')
        self.assertEqual(osutils.kind_marker('symlink'), '@')
        self.assertEqual(osutils.kind_marker('tree-reference'), '+')

    def test_get_umask(self):
        if sys.platform == 'win32':
            # umask always returns '0', no way to set it
            self.assertEqual(0, osutils.get_umask())
            return

        orig_umask = osutils.get_umask()
        try:
            os.umask(0222)
            self.assertEqual(0222, osutils.get_umask())
            os.umask(0022)
            self.assertEqual(0022, osutils.get_umask())
            os.umask(0002)
            self.assertEqual(0002, osutils.get_umask())
            os.umask(0027)
            self.assertEqual(0027, osutils.get_umask())
        finally:
            os.umask(orig_umask)

    def assertFormatedDelta(self, expected, seconds):
        """Assert osutils.format_delta formats as expected"""
        actual = osutils.format_delta(seconds)
        self.assertEqual(expected, actual)

    def test_format_delta(self):
        self.assertFormatedDelta('0 seconds ago', 0)
        self.assertFormatedDelta('1 second ago', 1)
        self.assertFormatedDelta('10 seconds ago', 10)
        self.assertFormatedDelta('59 seconds ago', 59)
        self.assertFormatedDelta('89 seconds ago', 89)
        self.assertFormatedDelta('1 minute, 30 seconds ago', 90)
        self.assertFormatedDelta('3 minutes, 0 seconds ago', 180)
        self.assertFormatedDelta('3 minutes, 1 second ago', 181)
        self.assertFormatedDelta('10 minutes, 15 seconds ago', 615)
        self.assertFormatedDelta('30 minutes, 59 seconds ago', 1859)
        self.assertFormatedDelta('31 minutes, 0 seconds ago', 1860)
        self.assertFormatedDelta('60 minutes, 0 seconds ago', 3600)
        self.assertFormatedDelta('89 minutes, 59 seconds ago', 5399)
        self.assertFormatedDelta('1 hour, 30 minutes ago', 5400)
        self.assertFormatedDelta('2 hours, 30 minutes ago', 9017)
        self.assertFormatedDelta('10 hours, 0 minutes ago', 36000)
        self.assertFormatedDelta('24 hours, 0 minutes ago', 86400)
        self.assertFormatedDelta('35 hours, 59 minutes ago', 129599)
        self.assertFormatedDelta('36 hours, 0 minutes ago', 129600)
        self.assertFormatedDelta('36 hours, 0 minutes ago', 129601)
        self.assertFormatedDelta('36 hours, 1 minute ago', 129660)
        self.assertFormatedDelta('36 hours, 1 minute ago', 129661)
        self.assertFormatedDelta('84 hours, 10 minutes ago', 303002)

        # We handle when time steps the wrong direction because computers
        # don't have synchronized clocks.
        self.assertFormatedDelta('84 hours, 10 minutes in the future', -303002)
        self.assertFormatedDelta('1 second in the future', -1)
        self.assertFormatedDelta('2 seconds in the future', -2)

    def test_format_date(self):
        self.assertRaises(errors.UnsupportedTimezoneFormat,
            osutils.format_date, 0, timezone='foo')
        self.assertIsInstance(osutils.format_date(0), str)
        self.assertIsInstance(osutils.format_local_date(0), unicode)
        # Testing for the actual value of the local weekday without
        # duplicating the code from format_date is difficult.
        # Instead blackbox.test_locale should check for localized
        # dates once they do occur in output strings.

    def test_dereference_path(self):
        self.requireFeature(SymlinkFeature)
        cwd = osutils.realpath('.')
        os.mkdir('bar')
        bar_path = osutils.pathjoin(cwd, 'bar')
        # Using './' to avoid bug #1213894 (first path component not
        # dereferenced) in Python 2.4.1 and earlier
        self.assertEqual(bar_path, osutils.realpath('./bar'))
        os.symlink('bar', 'foo')
        self.assertEqual(bar_path, osutils.realpath('./foo'))
        
        # Does not dereference terminal symlinks
        foo_path = osutils.pathjoin(cwd, 'foo')
        self.assertEqual(foo_path, osutils.dereference_path('./foo'))

        # Dereferences parent symlinks
        os.mkdir('bar/baz')
        baz_path = osutils.pathjoin(bar_path, 'baz')
        self.assertEqual(baz_path, osutils.dereference_path('./foo/baz'))

        # Dereferences parent symlinks that are the first path element
        self.assertEqual(baz_path, osutils.dereference_path('foo/baz'))

        # Dereferences parent symlinks in absolute paths
        foo_baz_path = osutils.pathjoin(foo_path, 'baz')
        self.assertEqual(baz_path, osutils.dereference_path(foo_baz_path))

    def test_changing_access(self):
        f = file('file', 'w')
        f.write('monkey')
        f.close()

        # Make a file readonly
        osutils.make_readonly('file')
        mode = os.lstat('file').st_mode
        self.assertEqual(mode, mode & 0777555)

        # Make a file writable
        osutils.make_writable('file')
        mode = os.lstat('file').st_mode
        self.assertEqual(mode, mode | 0200)

        if osutils.has_symlinks():
            # should not error when handed a symlink
            os.symlink('nonexistent', 'dangling')
            osutils.make_readonly('dangling')
            osutils.make_writable('dangling')

    def test_kind_marker(self):
        self.assertEqual("", osutils.kind_marker("file"))
        self.assertEqual("/", osutils.kind_marker(osutils._directory_kind))
        self.assertEqual("@", osutils.kind_marker("symlink"))
        self.assertRaises(errors.BzrError, osutils.kind_marker, "unknown")

    def test_host_os_dereferences_symlinks(self):
        osutils.host_os_dereferences_symlinks()


class TestPumpFile(TestCase):
    """Test pumpfile method."""
    def setUp(self):
        # create a test datablock
        self.block_size = 512
        pattern = '0123456789ABCDEF'
        self.test_data = pattern * (3 * self.block_size / len(pattern))
        self.test_data_len = len(self.test_data)

    def test_bracket_block_size(self):
        """Read data in blocks with the requested read size bracketing the
        block size."""
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        from_file = FakeReadFile(self.test_data)
        to_file = StringIO()

        # read (max / 2) bytes and verify read size wasn't affected
        num_bytes_to_read = self.block_size / 2
        pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), num_bytes_to_read)
        self.assertEqual(from_file.get_read_count(), 1)

        # read (max) bytes and verify read size wasn't affected
        num_bytes_to_read = self.block_size
        from_file.reset_read_count()
        pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), num_bytes_to_read)
        self.assertEqual(from_file.get_read_count(), 1)

        # read (max + 1) bytes and verify read size was limited
        num_bytes_to_read = self.block_size + 1
        from_file.reset_read_count()
        pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 2)

        # finish reading the rest of the data
        num_bytes_to_read = self.test_data_len - to_file.tell()
        pumpfile(from_file, to_file, num_bytes_to_read, self.block_size)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_specified_size(self):
        """Request a transfer larger than the maximum block size and verify
        that the maximum read doesn't exceed the block_size."""
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        # retrieve data in blocks
        from_file = FakeReadFile(self.test_data)
        to_file = StringIO()
        pumpfile(from_file, to_file, self.test_data_len, self.block_size)

        # verify read size was equal to the maximum read size
        self.assertTrue(from_file.get_max_read_size() > 0)
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 3)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_to_eof(self):
        """Read to end-of-file and verify that the reads are not larger than
        the maximum read size."""
        # make sure test data is larger than max read size
        self.assertTrue(self.test_data_len > self.block_size)

        # retrieve data to EOF
        from_file = FakeReadFile(self.test_data)
        to_file = StringIO()
        pumpfile(from_file, to_file, -1, self.block_size)

        # verify read size was equal to the maximum read size
        self.assertEqual(from_file.get_max_read_size(), self.block_size)
        self.assertEqual(from_file.get_read_count(), 4)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))

    def test_defaults(self):
        """Verifies that the default arguments will read to EOF -- this
        test verifies that any existing usages of pumpfile will not be broken
        with this new version."""
        # retrieve data using default (old) pumpfile method
        from_file = FakeReadFile(self.test_data)
        to_file = StringIO()
        pumpfile(from_file, to_file)

        # report error if the data wasn't equal (we only report the size due
        # to the length of the data)
        response_data = to_file.getvalue()
        if response_data != self.test_data:
            message = "Data not equal.  Expected %d bytes, received %d."
            self.fail(message % (len(response_data), self.test_data_len))


class TestPumpStringFile(TestCase):

    def test_empty(self):
        output = StringIO()
        pump_string_file("", output)
        self.assertEqual("", output.getvalue())

    def test_more_than_segment_size(self):
        output = StringIO()
        pump_string_file("123456789", output, 2)
        self.assertEqual("123456789", output.getvalue())

    def test_segment_size(self):
        output = StringIO()
        pump_string_file("12", output, 2)
        self.assertEqual("12", output.getvalue())

    def test_segment_size_multiple(self):
        output = StringIO()
        pump_string_file("1234", output, 2)
        self.assertEqual("1234", output.getvalue())


class TestSafeUnicode(TestCase):

    def test_from_ascii_string(self):
        self.assertEqual(u'foobar', osutils.safe_unicode('foobar'))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual(u'bargam', osutils.safe_unicode(u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual(u'bargam\xae', osutils.safe_unicode(u'bargam\xae'))

    def test_from_utf8_string(self):
        self.assertEqual(u'foo\xae', osutils.safe_unicode('foo\xc2\xae'))

    def test_bad_utf8_string(self):
        self.assertRaises(BzrBadParameterNotUnicode,
                          osutils.safe_unicode,
                          '\xbb\xbb')


class TestSafeUtf8(TestCase):

    def test_from_ascii_string(self):
        f = 'foobar'
        self.assertEqual('foobar', osutils.safe_utf8(f))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual('bargam', osutils.safe_utf8(u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual('bargam\xc2\xae', osutils.safe_utf8(u'bargam\xae'))

    def test_from_utf8_string(self):
        self.assertEqual('foo\xc2\xae', osutils.safe_utf8('foo\xc2\xae'))

    def test_bad_utf8_string(self):
        self.assertRaises(BzrBadParameterNotUnicode,
                          osutils.safe_utf8, '\xbb\xbb')


class TestSafeRevisionId(TestCase):

    def test_from_ascii_string(self):
        # this shouldn't give a warning because it's getting an ascii string
        self.assertEqual('foobar', osutils.safe_revision_id('foobar'))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual('bargam',
                         osutils.safe_revision_id(u'bargam', warn=False))

    def test_from_unicode_deprecated(self):
        self.assertEqual('bargam',
            self.callDeprecated([osutils._revision_id_warning],
                                osutils.safe_revision_id, u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual('bargam\xc2\xae',
                         osutils.safe_revision_id(u'bargam\xae', warn=False))

    def test_from_utf8_string(self):
        self.assertEqual('foo\xc2\xae',
                         osutils.safe_revision_id('foo\xc2\xae'))

    def test_none(self):
        """Currently, None is a valid revision_id"""
        self.assertEqual(None, osutils.safe_revision_id(None))


class TestSafeFileId(TestCase):

    def test_from_ascii_string(self):
        self.assertEqual('foobar', osutils.safe_file_id('foobar'))

    def test_from_unicode_string_ascii_contents(self):
        self.assertEqual('bargam', osutils.safe_file_id(u'bargam', warn=False))

    def test_from_unicode_deprecated(self):
        self.assertEqual('bargam',
            self.callDeprecated([osutils._file_id_warning],
                                osutils.safe_file_id, u'bargam'))

    def test_from_unicode_string_unicode_contents(self):
        self.assertEqual('bargam\xc2\xae',
                         osutils.safe_file_id(u'bargam\xae', warn=False))

    def test_from_utf8_string(self):
        self.assertEqual('foo\xc2\xae',
                         osutils.safe_file_id('foo\xc2\xae'))

    def test_none(self):
        """Currently, None is a valid revision_id"""
        self.assertEqual(None, osutils.safe_file_id(None))


class TestWin32Funcs(TestCase):
    """Test that the _win32 versions of os utilities return appropriate paths."""

    def test_abspath(self):
        self.assertEqual('C:/foo', osutils._win32_abspath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_abspath('C:/foo'))
        self.assertEqual('//HOST/path', osutils._win32_abspath(r'\\HOST\path'))
        self.assertEqual('//HOST/path', osutils._win32_abspath('//HOST/path'))

    def test_realpath(self):
        self.assertEqual('C:/foo', osutils._win32_realpath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_realpath('C:/foo'))

    def test_pathjoin(self):
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path', 'to', 'foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path\\to', 'C:\\foo'))
        self.assertEqual('C:/foo', osutils._win32_pathjoin('path/to', 'C:/foo'))
        self.assertEqual('path/to/foo', osutils._win32_pathjoin('path/to/', 'foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:/path/to/', '/foo'))
        self.assertEqual('/foo', osutils._win32_pathjoin('C:\\path\\to\\', '\\foo'))

    def test_normpath(self):
        self.assertEqual('path/to/foo', osutils._win32_normpath(r'path\\from\..\to\.\foo'))
        self.assertEqual('path/to/foo', osutils._win32_normpath('path//from/../to/./foo'))

    def test_getcwd(self):
        cwd = osutils._win32_getcwd()
        os_cwd = os.getcwdu()
        self.assertEqual(os_cwd[1:].replace('\\', '/'), cwd[1:])
        # win32 is inconsistent whether it returns lower or upper case
        # and even if it was consistent the user might type the other
        # so we force it to uppercase
        # running python.exe under cmd.exe return capital C:\\
        # running win32 python inside a cygwin shell returns lowercase
        self.assertEqual(os_cwd[0].upper(), cwd[0])

    def test_fixdrive(self):
        self.assertEqual('H:/foo', osutils._win32_fixdrive('h:/foo'))
        self.assertEqual('H:/foo', osutils._win32_fixdrive('H:/foo'))
        self.assertEqual('C:\\foo', osutils._win32_fixdrive('c:\\foo'))

    def test_win98_abspath(self):
        # absolute path
        self.assertEqual('C:/foo', osutils._win98_abspath('C:\\foo'))
        self.assertEqual('C:/foo', osutils._win98_abspath('C:/foo'))
        # UNC path
        self.assertEqual('//HOST/path', osutils._win98_abspath(r'\\HOST\path'))
        self.assertEqual('//HOST/path', osutils._win98_abspath('//HOST/path'))
        # relative path
        cwd = osutils.getcwd().rstrip('/')
        drive = osutils._nt_splitdrive(cwd)[0]
        self.assertEqual(cwd+'/path', osutils._win98_abspath('path'))
        self.assertEqual(drive+'/path', osutils._win98_abspath('/path'))
        # unicode path
        u = u'\u1234'
        self.assertEqual(cwd+'/'+u, osutils._win98_abspath(u))


class TestWin32FuncsDirs(TestCaseInTempDir):
    """Test win32 functions that create files."""
    
    def test_getcwd(self):
        if win32utils.winver == 'Windows 98':
            raise TestSkipped('Windows 98 cannot handle unicode filenames')
        # Make sure getcwd can handle unicode filenames
        try:
            os.mkdir(u'mu-\xb5')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'mu-\xb5')
        # TODO: jam 20060427 This will probably fail on Mac OSX because
        #       it will change the normalization of B\xe5gfors
        #       Consider using a different unicode character, or make
        #       osutils.getcwd() renormalize the path.
        self.assertEndsWith(osutils._win32_getcwd(), u'mu-\xb5')

    def test_minimum_path_selection(self):
        self.assertEqual(set(),
            osutils.minimum_path_selection([]))
        self.assertEqual(set(['a', 'b']),
            osutils.minimum_path_selection(['a', 'b']))
        self.assertEqual(set(['a/', 'b']),
            osutils.minimum_path_selection(['a/', 'b']))
        self.assertEqual(set(['a/', 'b']),
            osutils.minimum_path_selection(['a/c', 'a/', 'b']))

    def test_mkdtemp(self):
        tmpdir = osutils._win32_mkdtemp(dir='.')
        self.assertFalse('\\' in tmpdir)

    def test_rename(self):
        a = open('a', 'wb')
        a.write('foo\n')
        a.close()
        b = open('b', 'wb')
        b.write('baz\n')
        b.close()

        osutils._win32_rename('b', 'a')
        self.failUnlessExists('a')
        self.failIfExists('b')
        self.assertFileEqual('baz\n', 'a')

    def test_rename_missing_file(self):
        a = open('a', 'wb')
        a.write('foo\n')
        a.close()

        try:
            osutils._win32_rename('b', 'a')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)
        self.assertFileEqual('foo\n', 'a')

    def test_rename_missing_dir(self):
        os.mkdir('a')
        try:
            osutils._win32_rename('b', 'a')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)

    def test_rename_current_dir(self):
        os.mkdir('a')
        os.chdir('a')
        # You can't rename the working directory
        # doing rename non-existant . usually
        # just raises ENOENT, since non-existant
        # doesn't exist.
        try:
            osutils._win32_rename('b', '.')
        except (IOError, OSError), e:
            self.assertEqual(errno.ENOENT, e.errno)

    def test_splitpath(self):
        def check(expected, path):
            self.assertEqual(expected, osutils.splitpath(path))

        check(['a'], 'a')
        check(['a', 'b'], 'a/b')
        check(['a', 'b'], 'a/./b')
        check(['a', '.b'], 'a/.b')
        check(['a', '.b'], 'a\\.b')

        self.assertRaises(errors.BzrError, osutils.splitpath, 'a/../b')


class TestMacFuncsDirs(TestCaseInTempDir):
    """Test mac special functions that require directories."""

    def test_getcwd(self):
        # On Mac, this will actually create Ba\u030agfors
        # but chdir will still work, because it accepts both paths
        try:
            os.mkdir(u'B\xe5gfors')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'B\xe5gfors')
        self.assertEndsWith(osutils._mac_getcwd(), u'B\xe5gfors')

    def test_getcwd_nonnorm(self):
        # Test that _mac_getcwd() will normalize this path
        try:
            os.mkdir(u'Ba\u030agfors')
        except UnicodeError:
            raise TestSkipped("Unable to create Unicode filename")

        os.chdir(u'Ba\u030agfors')
        self.assertEndsWith(osutils._mac_getcwd(), u'B\xe5gfors')


class TestSplitLines(TestCase):

    def test_split_unicode(self):
        self.assertEqual([u'foo\n', u'bar\xae'],
                         osutils.split_lines(u'foo\nbar\xae'))
        self.assertEqual([u'foo\n', u'bar\xae\n'],
                         osutils.split_lines(u'foo\nbar\xae\n'))

    def test_split_with_carriage_returns(self):
        self.assertEqual(['foo\rbar\n'],
                         osutils.split_lines('foo\rbar\n'))


class TestWalkDirs(TestCaseInTempDir):

    def test_walkdirs(self):
        tree = [
            '.bzr',
            '0file',
            '1dir/',
            '1dir/0file',
            '1dir/1dir/',
            '2file'
            ]
        self.build_tree(tree)
        expected_dirblocks = [
                (('', '.'),
                 [('0file', '0file', 'file'),
                  ('1dir', '1dir', 'directory'),
                  ('2file', '2file', 'file'),
                 ]
                ),
                (('1dir', './1dir'),
                 [('1dir/0file', '0file', 'file'),
                  ('1dir/1dir', '1dir', 'directory'),
                 ]
                ),
                (('1dir/1dir', './1dir/1dir'),
                 [
                 ]
                ),
            ]
        result = []
        found_bzrdir = False
        for dirdetail, dirblock in osutils.walkdirs('.'):
            if len(dirblock) and dirblock[0][1] == '.bzr':
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            result.append((dirdetail, dirblock))

        self.assertTrue(found_bzrdir)
        self.assertEqual(expected_dirblocks,
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])
        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs('./1dir', '1dir'):
            result.append(dirblock)
        self.assertEqual(expected_dirblocks[1:],
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])

    def test__walkdirs_utf8(self):
        tree = [
            '.bzr',
            '0file',
            '1dir/',
            '1dir/0file',
            '1dir/1dir/',
            '2file'
            ]
        self.build_tree(tree)
        expected_dirblocks = [
                (('', '.'),
                 [('0file', '0file', 'file'),
                  ('1dir', '1dir', 'directory'),
                  ('2file', '2file', 'file'),
                 ]
                ),
                (('1dir', './1dir'),
                 [('1dir/0file', '0file', 'file'),
                  ('1dir/1dir', '1dir', 'directory'),
                 ]
                ),
                (('1dir/1dir', './1dir/1dir'),
                 [
                 ]
                ),
            ]
        result = []
        found_bzrdir = False
        for dirdetail, dirblock in osutils._walkdirs_utf8('.'):
            if len(dirblock) and dirblock[0][1] == '.bzr':
                # this tests the filtering of selected paths
                found_bzrdir = True
                del dirblock[0]
            result.append((dirdetail, dirblock))

        self.assertTrue(found_bzrdir)
        self.assertEqual(expected_dirblocks,
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])
        # you can search a subdir only, with a supplied prefix.
        result = []
        for dirblock in osutils.walkdirs('./1dir', '1dir'):
            result.append(dirblock)
        self.assertEqual(expected_dirblocks[1:],
            [(dirinfo, [line[0:3] for line in block]) for dirinfo, block in result])

    def _filter_out_stat(self, result):
        """Filter out the stat value from the walkdirs result"""
        for dirdetail, dirblock in result:
            new_dirblock = []
            for info in dirblock:
                # Ignore info[3] which is the stat
                new_dirblock.append((info[0], info[1], info[2], info[4]))
            dirblock[:] = new_dirblock

    def _save_platform_info(self):
        cur_winver = win32utils.winver
        cur_fs_enc = osutils._fs_enc
        cur_dir_reader = osutils._selected_dir_reader
        def restore():
            win32utils.winver = cur_winver
            osutils._fs_enc = cur_fs_enc
            osutils._selected_dir_reader = cur_dir_reader
        self.addCleanup(restore)

    def assertReadFSDirIs(self, expected):
        """Assert the right implementation for _walkdirs_utf8 is chosen."""
        # Force it to redetect
        osutils._selected_dir_reader = None
        # Nothing to list, but should still trigger the selection logic
        self.assertEqual([(('', '.'), [])], list(osutils._walkdirs_utf8('.')))
        self.assertIsInstance(osutils._selected_dir_reader, expected)

    def test_force_walkdirs_utf8_fs_utf8(self):
        self.requireFeature(UTF8DirReaderFeature)
        self._save_platform_info()
        win32utils.winver = None # Avoid the win32 detection code
        osutils._fs_enc = 'UTF-8'
        self.assertReadFSDirIs(UTF8DirReaderFeature.reader)

    def test_force_walkdirs_utf8_fs_ascii(self):
        self.requireFeature(UTF8DirReaderFeature)
        self._save_platform_info()
        win32utils.winver = None # Avoid the win32 detection code
        osutils._fs_enc = 'US-ASCII'
        self.assertReadFSDirIs(UTF8DirReaderFeature.reader)

    def test_force_walkdirs_utf8_fs_ANSI(self):
        self.requireFeature(UTF8DirReaderFeature)
        self._save_platform_info()
        win32utils.winver = None # Avoid the win32 detection code
        osutils._fs_enc = 'ANSI_X3.4-1968'
        self.assertReadFSDirIs(UTF8DirReaderFeature.reader)

    def test_force_walkdirs_utf8_fs_latin1(self):
        self._save_platform_info()
        win32utils.winver = None # Avoid the win32 detection code
        osutils._fs_enc = 'latin1'
        self.assertReadFSDirIs(osutils.UnicodeDirReader)

    def test_force_walkdirs_utf8_nt(self):
        # Disabled because the thunk of the whole walkdirs api is disabled.
        self.requireFeature(Win32ReadDirFeature)
        self._save_platform_info()
        win32utils.winver = 'Windows NT'
        from bzrlib._walkdirs_win32 import Win32ReadDir
        self.assertReadFSDirIs(Win32ReadDir)

    def test_force_walkdirs_utf8_98(self):
        self.requireFeature(Win32ReadDirFeature)
        self._save_platform_info()
        win32utils.winver = 'Windows 98'
        self.assertReadFSDirIs(osutils.UnicodeDirReader)

    def test_unicode_walkdirs(self):
        """Walkdirs should always return unicode paths."""
        name0 = u'0file-\xb6'
        name1 = u'1dir-\u062c\u0648'
        name2 = u'2file-\u0633'
        tree = [
            name0,
            name1 + '/',
            name1 + '/' + name0,
            name1 + '/' + name1 + '/',
            name2,
            ]
        try:
            self.build_tree(tree)
        except UnicodeError:
            raise TestSkipped('Could not represent Unicode chars'
                              ' in current encoding.')
        expected_dirblocks = [
                ((u'', u'.'),
                 [(name0, name0, 'file', './' + name0),
                  (name1, name1, 'directory', './' + name1),
                  (name2, name2, 'file', './' + name2),
                 ]
                ),
                ((name1, './' + name1),
                 [(name1 + '/' + name0, name0, 'file', './' + name1
                                                        + '/' + name0),
                  (name1 + '/' + name1, name1, 'directory', './' + name1
                                                            + '/' + name1),
                 ]
                ),
                ((name1 + '/' + name1, './' + name1 + '/' + name1),
                 [
                 ]
                ),
            ]
        result = list(osutils.walkdirs('.'))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks, result)
        result = list(osutils.walkdirs(u'./'+name1, name1))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks[1:], result)

    def test_unicode__walkdirs_utf8(self):
        """Walkdirs_utf8 should always return utf8 paths.

        The abspath portion might be in unicode or utf-8
        """
        name0 = u'0file-\xb6'
        name1 = u'1dir-\u062c\u0648'
        name2 = u'2file-\u0633'
        tree = [
            name0,
            name1 + '/',
            name1 + '/' + name0,
            name1 + '/' + name1 + '/',
            name2,
            ]
        try:
            self.build_tree(tree)
        except UnicodeError:
            raise TestSkipped('Could not represent Unicode chars'
                              ' in current encoding.')
        name0 = name0.encode('utf8')
        name1 = name1.encode('utf8')
        name2 = name2.encode('utf8')

        expected_dirblocks = [
                (('', '.'),
                 [(name0, name0, 'file', './' + name0),
                  (name1, name1, 'directory', './' + name1),
                  (name2, name2, 'file', './' + name2),
                 ]
                ),
                ((name1, './' + name1),
                 [(name1 + '/' + name0, name0, 'file', './' + name1
                                                        + '/' + name0),
                  (name1 + '/' + name1, name1, 'directory', './' + name1
                                                            + '/' + name1),
                 ]
                ),
                ((name1 + '/' + name1, './' + name1 + '/' + name1),
                 [
                 ]
                ),
            ]
        result = []
        # For ease in testing, if walkdirs_utf8 returns Unicode, assert that
        # all abspaths are Unicode, and encode them back into utf8.
        for dirdetail, dirblock in osutils._walkdirs_utf8('.'):
            self.assertIsInstance(dirdetail[0], str)
            if isinstance(dirdetail[1], unicode):
                dirdetail = (dirdetail[0], dirdetail[1].encode('utf8'))
                dirblock = [list(info) for info in dirblock]
                for info in dirblock:
                    self.assertIsInstance(info[4], unicode)
                    info[4] = info[4].encode('utf8')
            new_dirblock = []
            for info in dirblock:
                self.assertIsInstance(info[0], str)
                self.assertIsInstance(info[1], str)
                self.assertIsInstance(info[4], str)
                # Remove the stat information
                new_dirblock.append((info[0], info[1], info[2], info[4]))
            result.append((dirdetail, new_dirblock))
        self.assertEqual(expected_dirblocks, result)

    def test__walkdirs_utf8_with_unicode_fs(self):
        """UnicodeDirReader should be a safe fallback everywhere

        The abspath portion should be in unicode
        """
        # Use the unicode reader. TODO: split into driver-and-driven unit
        # tests.
        self._save_platform_info()
        osutils._selected_dir_reader = osutils.UnicodeDirReader()
        name0u = u'0file-\xb6'
        name1u = u'1dir-\u062c\u0648'
        name2u = u'2file-\u0633'
        tree = [
            name0u,
            name1u + '/',
            name1u + '/' + name0u,
            name1u + '/' + name1u + '/',
            name2u,
            ]
        try:
            self.build_tree(tree)
        except UnicodeError:
            raise TestSkipped('Could not represent Unicode chars'
                              ' in current encoding.')
        name0 = name0u.encode('utf8')
        name1 = name1u.encode('utf8')
        name2 = name2u.encode('utf8')

        # All of the abspaths should be in unicode, all of the relative paths
        # should be in utf8
        expected_dirblocks = [
                (('', '.'),
                 [(name0, name0, 'file', './' + name0u),
                  (name1, name1, 'directory', './' + name1u),
                  (name2, name2, 'file', './' + name2u),
                 ]
                ),
                ((name1, './' + name1u),
                 [(name1 + '/' + name0, name0, 'file', './' + name1u
                                                        + '/' + name0u),
                  (name1 + '/' + name1, name1, 'directory', './' + name1u
                                                            + '/' + name1u),
                 ]
                ),
                ((name1 + '/' + name1, './' + name1u + '/' + name1u),
                 [
                 ]
                ),
            ]
        result = list(osutils._walkdirs_utf8('.'))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks, result)

    def test__walkdirs_utf8_win32readdir(self):
        self.requireFeature(Win32ReadDirFeature)
        self.requireFeature(tests.UnicodeFilenameFeature)
        from bzrlib._walkdirs_win32 import Win32ReadDir
        self._save_platform_info()
        osutils._selected_dir_reader = Win32ReadDir()
        name0u = u'0file-\xb6'
        name1u = u'1dir-\u062c\u0648'
        name2u = u'2file-\u0633'
        tree = [
            name0u,
            name1u + '/',
            name1u + '/' + name0u,
            name1u + '/' + name1u + '/',
            name2u,
            ]
        self.build_tree(tree)
        name0 = name0u.encode('utf8')
        name1 = name1u.encode('utf8')
        name2 = name2u.encode('utf8')

        # All of the abspaths should be in unicode, all of the relative paths
        # should be in utf8
        expected_dirblocks = [
                (('', '.'),
                 [(name0, name0, 'file', './' + name0u),
                  (name1, name1, 'directory', './' + name1u),
                  (name2, name2, 'file', './' + name2u),
                 ]
                ),
                ((name1, './' + name1u),
                 [(name1 + '/' + name0, name0, 'file', './' + name1u
                                                        + '/' + name0u),
                  (name1 + '/' + name1, name1, 'directory', './' + name1u
                                                            + '/' + name1u),
                 ]
                ),
                ((name1 + '/' + name1, './' + name1u + '/' + name1u),
                 [
                 ]
                ),
            ]
        result = list(osutils._walkdirs_utf8(u'.'))
        self._filter_out_stat(result)
        self.assertEqual(expected_dirblocks, result)

    def assertStatIsCorrect(self, path, win32stat):
        os_stat = os.stat(path)
        self.assertEqual(os_stat.st_size, win32stat.st_size)
        self.assertAlmostEqual(os_stat.st_mtime, win32stat.st_mtime, places=4)
        self.assertAlmostEqual(os_stat.st_ctime, win32stat.st_ctime, places=4)
        self.assertAlmostEqual(os_stat.st_atime, win32stat.st_atime, places=4)
        self.assertEqual(os_stat.st_dev, win32stat.st_dev)
        self.assertEqual(os_stat.st_ino, win32stat.st_ino)
        self.assertEqual(os_stat.st_mode, win32stat.st_mode)

    def test__walkdirs_utf_win32_find_file_stat_file(self):
        """make sure our Stat values are valid"""
        self.requireFeature(Win32ReadDirFeature)
        self.requireFeature(tests.UnicodeFilenameFeature)
        from bzrlib._walkdirs_win32 import Win32ReadDir
        name0u = u'0file-\xb6'
        name0 = name0u.encode('utf8')
        self.build_tree([name0u])
        # I hate to sleep() here, but I'm trying to make the ctime different
        # from the mtime
        time.sleep(2)
        f = open(name0u, 'ab')
        try:
            f.write('just a small update')
        finally:
            f.close()

        result = Win32ReadDir().read_dir('', u'.')
        entry = result[0]
        self.assertEqual((name0, name0, 'file'), entry[:3])
        self.assertEqual(u'./' + name0u, entry[4])
        self.assertStatIsCorrect(entry[4], entry[3])
        self.assertNotEqual(entry[3].st_mtime, entry[3].st_ctime)

    def test__walkdirs_utf_win32_find_file_stat_directory(self):
        """make sure our Stat values are valid"""
        self.requireFeature(Win32ReadDirFeature)
        self.requireFeature(tests.UnicodeFilenameFeature)
        from bzrlib._walkdirs_win32 import Win32ReadDir
        name0u = u'0dir-\u062c\u0648'
        name0 = name0u.encode('utf8')
        self.build_tree([name0u + '/'])

        result = Win32ReadDir().read_dir('', u'.')
        entry = result[0]
        self.assertEqual((name0, name0, 'directory'), entry[:3])
        self.assertEqual(u'./' + name0u, entry[4])
        self.assertStatIsCorrect(entry[4], entry[3])

    def assertPathCompare(self, path_less, path_greater):
        """check that path_less and path_greater compare correctly."""
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_less, path_less))
        self.assertEqual(0, osutils.compare_paths_prefix_order(
            path_greater, path_greater))
        self.assertEqual(-1, osutils.compare_paths_prefix_order(
            path_less, path_greater))
        self.assertEqual(1, osutils.compare_paths_prefix_order(
            path_greater, path_less))

    def test_compare_paths_prefix_order(self):
        # root before all else
        self.assertPathCompare("/", "/a")
        # alpha within a dir
        self.assertPathCompare("/a", "/b")
        self.assertPathCompare("/b", "/z")
        # high dirs before lower.
        self.assertPathCompare("/z", "/a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("/a/b/c", "/d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("/a/z", "/z/z")
        self.assertPathCompare("/a/c/z", "/a/d/e")

        # this should also be consistent for no leading / paths
        # root before all else
        self.assertPathCompare("", "a")
        # alpha within a dir
        self.assertPathCompare("a", "b")
        self.assertPathCompare("b", "z")
        # high dirs before lower.
        self.assertPathCompare("z", "a/a")
        # except if the deeper dir should be output first
        self.assertPathCompare("a/b/c", "d/g")
        # lexical betwen dirs of the same height
        self.assertPathCompare("a/z", "z/z")
        self.assertPathCompare("a/c/z", "a/d/e")

    def test_path_prefix_sorting(self):
        """Doing a sort on path prefix should match our sample data."""
        original_paths = [
            'a',
            'a/b',
            'a/b/c',
            'b',
            'b/c',
            'd',
            'd/e',
            'd/e/f',
            'd/f',
            'd/g',
            'g',
            ]

        dir_sorted_paths = [
            'a',
            'b',
            'd',
            'g',
            'a/b',
            'a/b/c',
            'b/c',
            'd/e',
            'd/f',
            'd/g',
            'd/e/f',
            ]

        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, key=osutils.path_prefix_key))
        # using the comparison routine shoudl work too:
        self.assertEqual(
            dir_sorted_paths,
            sorted(original_paths, cmp=osutils.compare_paths_prefix_order))


class TestCopyTree(TestCaseInTempDir):
    
    def test_copy_basic_tree(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        osutils.copy_tree('source', 'target')
        self.assertEqual(['a', 'b'], sorted(os.listdir('target')))
        self.assertEqual(['c'], os.listdir('target/b'))

    def test_copy_tree_target_exists(self):
        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c',
                         'target/'])
        osutils.copy_tree('source', 'target')
        self.assertEqual(['a', 'b'], sorted(os.listdir('target')))
        self.assertEqual(['c'], os.listdir('target/b'))

    def test_copy_tree_symlinks(self):
        self.requireFeature(SymlinkFeature)
        self.build_tree(['source/'])
        os.symlink('a/generic/path', 'source/lnk')
        osutils.copy_tree('source', 'target')
        self.assertEqual(['lnk'], os.listdir('target'))
        self.assertEqual('a/generic/path', os.readlink('target/lnk'))

    def test_copy_tree_handlers(self):
        processed_files = []
        processed_links = []
        def file_handler(from_path, to_path):
            processed_files.append(('f', from_path, to_path))
        def dir_handler(from_path, to_path):
            processed_files.append(('d', from_path, to_path))
        def link_handler(from_path, to_path):
            processed_links.append((from_path, to_path))
        handlers = {'file':file_handler,
                    'directory':dir_handler,
                    'symlink':link_handler,
                   }

        self.build_tree(['source/', 'source/a', 'source/b/', 'source/b/c'])
        if osutils.has_symlinks():
            os.symlink('a/generic/path', 'source/lnk')
        osutils.copy_tree('source', 'target', handlers=handlers)

        self.assertEqual([('d', 'source', 'target'),
                          ('f', 'source/a', 'target/a'),
                          ('d', 'source/b', 'target/b'),
                          ('f', 'source/b/c', 'target/b/c'),
                         ], processed_files)
        self.failIfExists('target')
        if osutils.has_symlinks():
            self.assertEqual([('source/lnk', 'target/lnk')], processed_links)


#class TestTerminalEncoding has been moved to test_osutils_encodings.py
# [bialix] 2006/12/26


class TestSetUnsetEnv(TestCase):
    """Test updating the environment"""

    def setUp(self):
        super(TestSetUnsetEnv, self).setUp()

        self.assertEqual(None, os.environ.get('BZR_TEST_ENV_VAR'),
                         'Environment was not cleaned up properly.'
                         ' Variable BZR_TEST_ENV_VAR should not exist.')
        def cleanup():
            if 'BZR_TEST_ENV_VAR' in os.environ:
                del os.environ['BZR_TEST_ENV_VAR']

        self.addCleanup(cleanup)

    def test_set(self):
        """Test that we can set an env variable"""
        old = osutils.set_or_unset_env('BZR_TEST_ENV_VAR', 'foo')
        self.assertEqual(None, old)
        self.assertEqual('foo', os.environ.get('BZR_TEST_ENV_VAR'))

    def test_double_set(self):
        """Test that we get the old value out"""
        osutils.set_or_unset_env('BZR_TEST_ENV_VAR', 'foo')
        old = osutils.set_or_unset_env('BZR_TEST_ENV_VAR', 'bar')
        self.assertEqual('foo', old)
        self.assertEqual('bar', os.environ.get('BZR_TEST_ENV_VAR'))

    def test_unicode(self):
        """Environment can only contain plain strings
        
        So Unicode strings must be encoded.
        """
        uni_val, env_val = probe_unicode_in_user_encoding()
        if uni_val is None:
            raise TestSkipped('Cannot find a unicode character that works in'
                              ' encoding %s' % (osutils.get_user_encoding(),))

        old = osutils.set_or_unset_env('BZR_TEST_ENV_VAR', uni_val)
        self.assertEqual(env_val, os.environ.get('BZR_TEST_ENV_VAR'))

    def test_unset(self):
        """Test that passing None will remove the env var"""
        osutils.set_or_unset_env('BZR_TEST_ENV_VAR', 'foo')
        old = osutils.set_or_unset_env('BZR_TEST_ENV_VAR', None)
        self.assertEqual('foo', old)
        self.assertEqual(None, os.environ.get('BZR_TEST_ENV_VAR'))
        self.failIf('BZR_TEST_ENV_VAR' in os.environ)


class TestLocalTimeOffset(TestCase):

    def test_local_time_offset(self):
        """Test that local_time_offset() returns a sane value."""
        offset = osutils.local_time_offset()
        self.assertTrue(isinstance(offset, int))
        # Test that the offset is no more than a eighteen hours in
        # either direction.
        # Time zone handling is system specific, so it is difficult to
        # do more specific tests, but a value outside of this range is
        # probably wrong.
        eighteen_hours = 18 * 3600
        self.assertTrue(-eighteen_hours < offset < eighteen_hours)

    def test_local_time_offset_with_timestamp(self):
        """Test that local_time_offset() works with a timestamp."""
        offset = osutils.local_time_offset(1000000000.1234567)
        self.assertTrue(isinstance(offset, int))
        eighteen_hours = 18 * 3600
        self.assertTrue(-eighteen_hours < offset < eighteen_hours)


class TestShaFileByName(TestCaseInTempDir):

    def test_sha_empty(self):
        self.build_tree_contents([('foo', '')])
        expected_sha = osutils.sha_string('')
        self.assertEqual(expected_sha, osutils.sha_file_by_name('foo'))

    def test_sha_mixed_endings(self):
        text = 'test\r\nwith\nall\rpossible line endings\r\n'
        self.build_tree_contents([('foo', text)])
        expected_sha = osutils.sha_string(text)
        self.assertEqual(expected_sha, osutils.sha_file_by_name('foo'))


_debug_text = \
r'''# Copyright (C) 2005, 2006 Canonical Ltd
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


# NOTE: If update these, please also update the help for global-options in
#       bzrlib/help_topics/__init__.py

debug_flags = set()
"""Set of flags that enable different debug behaviour.

These are set with eg ``-Dlock`` on the bzr command line.

Options include:
 
 * auth - show authentication sections used
 * error - show stack traces for all top level exceptions
 * evil - capture call sites that do expensive or badly-scaling operations.
 * fetch - trace history copying between repositories
 * graph - trace graph traversal information
 * hashcache - log every time a working file is read to determine its hash
 * hooks - trace hook execution
 * hpss - trace smart protocol requests and responses
 * http - trace http connections, requests and responses
 * index - trace major index operations
 * knit - trace knit operations
 * lock - trace when lockdir locks are taken or released
 * merge - emit information for debugging merges
 * pack - emit information about pack operations

"""
'''


class TestResourceLoading(TestCaseInTempDir):

    def test_resource_string(self):
        # test resource in bzrlib
        text = osutils.resource_string('bzrlib', 'debug.py')
        self.assertEquals(_debug_text, text)
        # test resource under bzrlib
        text = osutils.resource_string('bzrlib.ui', 'text.py')
        self.assertContainsRe(text, "class TextUIFactory")
        # test unsupported package
        self.assertRaises(errors.BzrError, osutils.resource_string, 'zzzz',
            'yyy.xx')
        # test unknown resource
        self.assertRaises(IOError, osutils.resource_string, 'bzrlib', 'yyy.xx')
