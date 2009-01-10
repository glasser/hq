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

import os
import re
import stat
from stat import (S_ISREG, S_ISDIR, S_ISLNK, ST_MODE, ST_SIZE,
                  S_ISCHR, S_ISBLK, S_ISFIFO, S_ISSOCK)
import sys
import time

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import codecs
from datetime import datetime
import errno
from ntpath import (abspath as _nt_abspath,
                    join as _nt_join,
                    normpath as _nt_normpath,
                    realpath as _nt_realpath,
                    splitdrive as _nt_splitdrive,
                    )
import posixpath
import shutil
from shutil import (
    rmtree,
    )
import tempfile
from tempfile import (
    mkdtemp,
    )
import unicodedata

from bzrlib import (
    cache_utf8,
    errors,
    win32utils,
    )
""")

# sha and md5 modules are deprecated in python2.6 but hashlib is available as
# of 2.5
if sys.version_info < (2, 5):
    import md5 as _mod_md5
    md5 = _mod_md5.new
    import sha as _mod_sha
    sha = _mod_sha.new
else:
    from hashlib import (
        md5,
        sha1 as sha,
        )


import bzrlib
from bzrlib import symbol_versioning


# On win32, O_BINARY is used to indicate the file should
# be opened in binary mode, rather than text mode.
# On other platforms, O_BINARY doesn't exist, because
# they always open in binary mode, so it is okay to
# OR with 0 on those platforms
O_BINARY = getattr(os, 'O_BINARY', 0)


def make_readonly(filename):
    """Make a filename read-only."""
    mod = os.lstat(filename).st_mode
    if not stat.S_ISLNK(mod):
        mod = mod & 0777555
        os.chmod(filename, mod)


def make_writable(filename):
    mod = os.lstat(filename).st_mode
    if not stat.S_ISLNK(mod):
        mod = mod | 0200
        os.chmod(filename, mod)


def minimum_path_selection(paths):
    """Return the smallset subset of paths which are outside paths.

    :param paths: A container (and hence not None) of paths.
    :return: A set of paths sufficient to include everything in paths via
        is_inside_any, drawn from the paths parameter.
    """
    search_paths = set()
    paths = set(paths)
    for path in paths:
        other_paths = paths.difference([path])
        if not is_inside_any(other_paths, path):
            # this is a top level path, we must check it.
            search_paths.add(path)
    return search_paths


_QUOTE_RE = None


def quotefn(f):
    """Return a quoted filename filename

    This previously used backslash quoting, but that works poorly on
    Windows."""
    # TODO: I'm not really sure this is the best format either.x
    global _QUOTE_RE
    if _QUOTE_RE is None:
        _QUOTE_RE = re.compile(r'([^a-zA-Z0-9.,:/\\_~-])')
        
    if _QUOTE_RE.search(f):
        return '"' + f + '"'
    else:
        return f


_directory_kind = 'directory'

def get_umask():
    """Return the current umask"""
    # Assume that people aren't messing with the umask while running
    # XXX: This is not thread safe, but there is no way to get the
    #      umask without setting it
    umask = os.umask(0)
    os.umask(umask)
    return umask


_kind_marker_map = {
    "file": "",
    _directory_kind: "/",
    "symlink": "@",
    'tree-reference': '+',
}


def kind_marker(kind):
    try:
        return _kind_marker_map[kind]
    except KeyError:
        raise errors.BzrError('invalid file kind %r' % kind)


lexists = getattr(os.path, 'lexists', None)
if lexists is None:
    def lexists(f):
        try:
            stat = getattr(os, 'lstat', os.stat)
            stat(f)
            return True
        except OSError, e:
            if e.errno == errno.ENOENT:
                return False;
            else:
                raise errors.BzrError("lstat/stat of (%r): %r" % (f, e))


def fancy_rename(old, new, rename_func, unlink_func):
    """A fancy rename, when you don't have atomic rename.
    
    :param old: The old path, to rename from
    :param new: The new path, to rename to
    :param rename_func: The potentially non-atomic rename function
    :param unlink_func: A way to delete the target file if the full rename succeeds
    """

    # sftp rename doesn't allow overwriting, so play tricks:
    base = os.path.basename(new)
    dirname = os.path.dirname(new)
    tmp_name = u'tmp.%s.%.9f.%d.%s' % (base, time.time(), os.getpid(), rand_chars(10))
    tmp_name = pathjoin(dirname, tmp_name)

    # Rename the file out of the way, but keep track if it didn't exist
    # We don't want to grab just any exception
    # something like EACCES should prevent us from continuing
    # The downside is that the rename_func has to throw an exception
    # with an errno = ENOENT, or NoSuchFile
    file_existed = False
    try:
        rename_func(new, tmp_name)
    except (errors.NoSuchFile,), e:
        pass
    except IOError, e:
        # RBC 20060103 abstraction leakage: the paramiko SFTP clients rename
        # function raises an IOError with errno is None when a rename fails.
        # This then gets caught here.
        if e.errno not in (None, errno.ENOENT, errno.ENOTDIR):
            raise
    except Exception, e:
        if (getattr(e, 'errno', None) is None
            or e.errno not in (errno.ENOENT, errno.ENOTDIR)):
            raise
    else:
        file_existed = True

    success = False
    try:
        try:
            # This may throw an exception, in which case success will
            # not be set.
            rename_func(old, new)
            success = True
        except (IOError, OSError), e:
            # source and target may be aliases of each other (e.g. on a
            # case-insensitive filesystem), so we may have accidentally renamed
            # source by when we tried to rename target
            if not (file_existed and e.errno in (None, errno.ENOENT)):
                raise
    finally:
        if file_existed:
            # If the file used to exist, rename it back into place
            # otherwise just delete it from the tmp location
            if success:
                unlink_func(tmp_name)
            else:
                rename_func(tmp_name, new)


# In Python 2.4.2 and older, os.path.abspath and os.path.realpath
# choke on a Unicode string containing a relative path if
# os.getcwd() returns a non-sys.getdefaultencoding()-encoded
# string.
_fs_enc = sys.getfilesystemencoding() or 'utf-8'
def _posix_abspath(path):
    # jam 20060426 rather than encoding to fsencoding
    # copy posixpath.abspath, but use os.getcwdu instead
    if not posixpath.isabs(path):
        path = posixpath.join(getcwd(), path)
    return posixpath.normpath(path)


def _posix_realpath(path):
    return posixpath.realpath(path.encode(_fs_enc)).decode(_fs_enc)


def _win32_fixdrive(path):
    """Force drive letters to be consistent.

    win32 is inconsistent whether it returns lower or upper case
    and even if it was consistent the user might type the other
    so we force it to uppercase
    running python.exe under cmd.exe return capital C:\\
    running win32 python inside a cygwin shell returns lowercase c:\\
    """
    drive, path = _nt_splitdrive(path)
    return drive.upper() + path


def _win32_abspath(path):
    # Real _nt_abspath doesn't have a problem with a unicode cwd
    return _win32_fixdrive(_nt_abspath(unicode(path)).replace('\\', '/'))


def _win98_abspath(path):
    """Return the absolute version of a path.
    Windows 98 safe implementation (python reimplementation
    of Win32 API function GetFullPathNameW)
    """
    # Corner cases:
    #   C:\path     => C:/path
    #   C:/path     => C:/path
    #   \\HOST\path => //HOST/path
    #   //HOST/path => //HOST/path
    #   path        => C:/cwd/path
    #   /path       => C:/path
    path = unicode(path)
    # check for absolute path
    drive = _nt_splitdrive(path)[0]
    if drive == '' and path[:2] not in('//','\\\\'):
        cwd = os.getcwdu()
        # we cannot simply os.path.join cwd and path
        # because os.path.join('C:','/path') produce '/path'
        # and this is incorrect
        if path[:1] in ('/','\\'):
            cwd = _nt_splitdrive(cwd)[0]
            path = path[1:]
        path = cwd + '\\' + path
    return _win32_fixdrive(_nt_normpath(path).replace('\\', '/'))


def _win32_realpath(path):
    # Real _nt_realpath doesn't have a problem with a unicode cwd
    return _win32_fixdrive(_nt_realpath(unicode(path)).replace('\\', '/'))


def _win32_pathjoin(*args):
    return _nt_join(*args).replace('\\', '/')


def _win32_normpath(path):
    return _win32_fixdrive(_nt_normpath(unicode(path)).replace('\\', '/'))


def _win32_getcwd():
    return _win32_fixdrive(os.getcwdu().replace('\\', '/'))


def _win32_mkdtemp(*args, **kwargs):
    return _win32_fixdrive(tempfile.mkdtemp(*args, **kwargs).replace('\\', '/'))


def _win32_rename(old, new):
    """We expect to be able to atomically replace 'new' with old.

    On win32, if new exists, it must be moved out of the way first,
    and then deleted. 
    """
    try:
        fancy_rename(old, new, rename_func=os.rename, unlink_func=os.unlink)
    except OSError, e:
        if e.errno in (errno.EPERM, errno.EACCES, errno.EBUSY, errno.EINVAL):
            # If we try to rename a non-existant file onto cwd, we get 
            # EPERM or EACCES instead of ENOENT, this will raise ENOENT 
            # if the old path doesn't exist, sometimes we get EACCES
            # On Linux, we seem to get EBUSY, on Mac we get EINVAL
            os.lstat(old)
        raise


def _mac_getcwd():
    return unicodedata.normalize('NFC', os.getcwdu())


# Default is to just use the python builtins, but these can be rebound on
# particular platforms.
abspath = _posix_abspath
realpath = _posix_realpath
pathjoin = os.path.join
normpath = os.path.normpath
getcwd = os.getcwdu
rename = os.rename
dirname = os.path.dirname
basename = os.path.basename
split = os.path.split
splitext = os.path.splitext
# These were already imported into local scope
# mkdtemp = tempfile.mkdtemp
# rmtree = shutil.rmtree

MIN_ABS_PATHLENGTH = 1


if sys.platform == 'win32':
    if win32utils.winver == 'Windows 98':
        abspath = _win98_abspath
    else:
        abspath = _win32_abspath
    realpath = _win32_realpath
    pathjoin = _win32_pathjoin
    normpath = _win32_normpath
    getcwd = _win32_getcwd
    mkdtemp = _win32_mkdtemp
    rename = _win32_rename

    MIN_ABS_PATHLENGTH = 3

    def _win32_delete_readonly(function, path, excinfo):
        """Error handler for shutil.rmtree function [for win32]
        Helps to remove files and dirs marked as read-only.
        """
        exception = excinfo[1]
        if function in (os.remove, os.rmdir) \
            and isinstance(exception, OSError) \
            and exception.errno == errno.EACCES:
            make_writable(path)
            function(path)
        else:
            raise

    def rmtree(path, ignore_errors=False, onerror=_win32_delete_readonly):
        """Replacer for shutil.rmtree: could remove readonly dirs/files"""
        return shutil.rmtree(path, ignore_errors, onerror)
elif sys.platform == 'darwin':
    getcwd = _mac_getcwd


def get_terminal_encoding():
    """Find the best encoding for printing to the screen.

    This attempts to check both sys.stdout and sys.stdin to see
    what encoding they are in, and if that fails it falls back to
    osutils.get_user_encoding().
    The problem is that on Windows, locale.getpreferredencoding()
    is not the same encoding as that used by the console:
    http://mail.python.org/pipermail/python-list/2003-May/162357.html

    On my standard US Windows XP, the preferred encoding is
    cp1252, but the console is cp437
    """
    from bzrlib.trace import mutter
    output_encoding = getattr(sys.stdout, 'encoding', None)
    if not output_encoding:
        input_encoding = getattr(sys.stdin, 'encoding', None)
        if not input_encoding:
            output_encoding = get_user_encoding()
            mutter('encoding stdout as osutils.get_user_encoding() %r',
                   output_encoding)
        else:
            output_encoding = input_encoding
            mutter('encoding stdout as sys.stdin encoding %r', output_encoding)
    else:
        mutter('encoding stdout as sys.stdout encoding %r', output_encoding)
    if output_encoding == 'cp0':
        # invalid encoding (cp0 means 'no codepage' on Windows)
        output_encoding = get_user_encoding()
        mutter('cp0 is invalid encoding.'
               ' encoding stdout as osutils.get_user_encoding() %r',
               output_encoding)
    # check encoding
    try:
        codecs.lookup(output_encoding)
    except LookupError:
        sys.stderr.write('bzr: warning:'
                         ' unknown terminal encoding %s.\n'
                         '  Using encoding %s instead.\n'
                         % (output_encoding, get_user_encoding())
                        )
        output_encoding = get_user_encoding()

    return output_encoding


def normalizepath(f):
    if getattr(os.path, 'realpath', None) is not None:
        F = realpath
    else:
        F = abspath
    [p,e] = os.path.split(f)
    if e == "" or e == "." or e == "..":
        return F(f)
    else:
        return pathjoin(F(p), e)


def isdir(f):
    """True if f is an accessible directory."""
    try:
        return S_ISDIR(os.lstat(f)[ST_MODE])
    except OSError:
        return False


def isfile(f):
    """True if f is a regular file."""
    try:
        return S_ISREG(os.lstat(f)[ST_MODE])
    except OSError:
        return False

def islink(f):
    """True if f is a symlink."""
    try:
        return S_ISLNK(os.lstat(f)[ST_MODE])
    except OSError:
        return False

def is_inside(dir, fname):
    """True if fname is inside dir.
    
    The parameters should typically be passed to osutils.normpath first, so
    that . and .. and repeated slashes are eliminated, and the separators
    are canonical for the platform.
    
    The empty string as a dir name is taken as top-of-tree and matches 
    everything.
    """
    # XXX: Most callers of this can actually do something smarter by 
    # looking at the inventory
    if dir == fname:
        return True
    
    if dir == '':
        return True

    if dir[-1] != '/':
        dir += '/'

    return fname.startswith(dir)


def is_inside_any(dir_list, fname):
    """True if fname is inside any of given dirs."""
    for dirname in dir_list:
        if is_inside(dirname, fname):
            return True
    return False


def is_inside_or_parent_of_any(dir_list, fname):
    """True if fname is a child or a parent of any of the given files."""
    for dirname in dir_list:
        if is_inside(dirname, fname) or is_inside(fname, dirname):
            return True
    return False


def pumpfile(from_file, to_file, read_length=-1, buff_size=32768):
    """Copy contents of one file to another.

    The read_length can either be -1 to read to end-of-file (EOF) or
    it can specify the maximum number of bytes to read.

    The buff_size represents the maximum size for each read operation
    performed on from_file.

    :return: The number of bytes copied.
    """
    length = 0
    if read_length >= 0:
        # read specified number of bytes

        while read_length > 0:
            num_bytes_to_read = min(read_length, buff_size)

            block = from_file.read(num_bytes_to_read)
            if not block:
                # EOF reached
                break
            to_file.write(block)

            actual_bytes_read = len(block)
            read_length -= actual_bytes_read
            length += actual_bytes_read
    else:
        # read to EOF
        while True:
            block = from_file.read(buff_size)
            if not block:
                # EOF reached
                break
            to_file.write(block)
            length += len(block)
    return length


def pump_string_file(bytes, file_handle, segment_size=None):
    """Write bytes to file_handle in many smaller writes.

    :param bytes: The string to write.
    :param file_handle: The file to write to.
    """
    # Write data in chunks rather than all at once, because very large
    # writes fail on some platforms (e.g. Windows with SMB  mounted
    # drives).
    if not segment_size:
        segment_size = 5242880 # 5MB
    segments = range(len(bytes) / segment_size + 1)
    write = file_handle.write
    for segment_index in segments:
        segment = buffer(bytes, segment_index * segment_size, segment_size)
        write(segment)


def file_iterator(input_file, readsize=32768):
    while True:
        b = input_file.read(readsize)
        if len(b) == 0:
            break
        yield b


def sha_file(f):
    """Calculate the hexdigest of an open file.

    The file cursor should be already at the start.
    """
    s = sha()
    BUFSIZE = 128<<10
    while True:
        b = f.read(BUFSIZE)
        if not b:
            break
        s.update(b)
    return s.hexdigest()


def sha_file_by_name(fname):
    """Calculate the SHA1 of a file by reading the full text"""
    s = sha()
    f = os.open(fname, os.O_RDONLY | O_BINARY)
    try:
        while True:
            b = os.read(f, 1<<16)
            if not b:
                return s.hexdigest()
            s.update(b)
    finally:
        os.close(f)


def sha_strings(strings, _factory=sha):
    """Return the sha-1 of concatenation of strings"""
    s = _factory()
    map(s.update, strings)
    return s.hexdigest()


def sha_string(f, _factory=sha):
    return _factory(f).hexdigest()


def fingerprint_file(f):
    b = f.read()
    return {'size': len(b),
            'sha1': sha(b).hexdigest()}


def compare_files(a, b):
    """Returns true if equal in contents"""
    BUFSIZE = 4096
    while True:
        ai = a.read(BUFSIZE)
        bi = b.read(BUFSIZE)
        if ai != bi:
            return False
        if ai == '':
            return True


def local_time_offset(t=None):
    """Return offset of local zone from GMT, either at present or at time t."""
    if t is None:
        t = time.time()
    offset = datetime.fromtimestamp(t) - datetime.utcfromtimestamp(t)
    return offset.days * 86400 + offset.seconds

weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
def format_date(t, offset=0, timezone='original', date_fmt=None,
                show_offset=True):
    """Return a formatted date string.

    :param t: Seconds since the epoch.
    :param offset: Timezone offset in seconds east of utc.
    :param timezone: How to display the time: 'utc', 'original' for the
         timezone specified by offset, or 'local' for the process's current
         timezone.
    :param date_fmt: strftime format.
    :param show_offset: Whether to append the timezone.
    """
    (date_fmt, tt, offset_str) = \
               _format_date(t, offset, timezone, date_fmt, show_offset)
    date_fmt = date_fmt.replace('%a', weekdays[tt[6]])
    date_str = time.strftime(date_fmt, tt)
    return date_str + offset_str

def format_local_date(t, offset=0, timezone='original', date_fmt=None,
                      show_offset=True):
    """Return an unicode date string formatted according to the current locale.

    :param t: Seconds since the epoch.
    :param offset: Timezone offset in seconds east of utc.
    :param timezone: How to display the time: 'utc', 'original' for the
         timezone specified by offset, or 'local' for the process's current
         timezone.
    :param date_fmt: strftime format.
    :param show_offset: Whether to append the timezone.
    """
    (date_fmt, tt, offset_str) = \
               _format_date(t, offset, timezone, date_fmt, show_offset)
    date_str = time.strftime(date_fmt, tt)
    if not isinstance(date_str, unicode):
        date_str = date_str.decode(bzrlib.user_encoding, 'replace')
    return date_str + offset_str

def _format_date(t, offset, timezone, date_fmt, show_offset):
    if timezone == 'utc':
        tt = time.gmtime(t)
        offset = 0
    elif timezone == 'original':
        if offset is None:
            offset = 0
        tt = time.gmtime(t + offset)
    elif timezone == 'local':
        tt = time.localtime(t)
        offset = local_time_offset(t)
    else:
        raise errors.UnsupportedTimezoneFormat(timezone)
    if date_fmt is None:
        date_fmt = "%a %Y-%m-%d %H:%M:%S"
    if show_offset:
        offset_str = ' %+03d%02d' % (offset / 3600, (offset / 60) % 60)
    else:
        offset_str = ''
    return (date_fmt, tt, offset_str)


def compact_date(when):
    return time.strftime('%Y%m%d%H%M%S', time.gmtime(when))
    

def format_delta(delta):
    """Get a nice looking string for a time delta.

    :param delta: The time difference in seconds, can be positive or negative.
        positive indicates time in the past, negative indicates time in the
        future. (usually time.time() - stored_time)
    :return: String formatted to show approximate resolution
    """
    delta = int(delta)
    if delta >= 0:
        direction = 'ago'
    else:
        direction = 'in the future'
        delta = -delta

    seconds = delta
    if seconds < 90: # print seconds up to 90 seconds
        if seconds == 1:
            return '%d second %s' % (seconds, direction,)
        else:
            return '%d seconds %s' % (seconds, direction)

    minutes = int(seconds / 60)
    seconds -= 60 * minutes
    if seconds == 1:
        plural_seconds = ''
    else:
        plural_seconds = 's'
    if minutes < 90: # print minutes, seconds up to 90 minutes
        if minutes == 1:
            return '%d minute, %d second%s %s' % (
                    minutes, seconds, plural_seconds, direction)
        else:
            return '%d minutes, %d second%s %s' % (
                    minutes, seconds, plural_seconds, direction)

    hours = int(minutes / 60)
    minutes -= 60 * hours
    if minutes == 1:
        plural_minutes = ''
    else:
        plural_minutes = 's'

    if hours == 1:
        return '%d hour, %d minute%s %s' % (hours, minutes,
                                            plural_minutes, direction)
    return '%d hours, %d minute%s %s' % (hours, minutes,
                                         plural_minutes, direction)

def filesize(f):
    """Return size of given open file."""
    return os.fstat(f.fileno())[ST_SIZE]


# Define rand_bytes based on platform.
try:
    # Python 2.4 and later have os.urandom,
    # but it doesn't work on some arches
    os.urandom(1)
    rand_bytes = os.urandom
except (NotImplementedError, AttributeError):
    # If python doesn't have os.urandom, or it doesn't work,
    # then try to first pull random data from /dev/urandom
    try:
        rand_bytes = file('/dev/urandom', 'rb').read
    # Otherwise, use this hack as a last resort
    except (IOError, OSError):
        # not well seeded, but better than nothing
        def rand_bytes(n):
            import random
            s = ''
            while n:
                s += chr(random.randint(0, 255))
                n -= 1
            return s


ALNUM = '0123456789abcdefghijklmnopqrstuvwxyz'
def rand_chars(num):
    """Return a random string of num alphanumeric characters
    
    The result only contains lowercase chars because it may be used on 
    case-insensitive filesystems.
    """
    s = ''
    for raw_byte in rand_bytes(num):
        s += ALNUM[ord(raw_byte) % 36]
    return s


## TODO: We could later have path objects that remember their list
## decomposition (might be too tricksy though.)

def splitpath(p):
    """Turn string into list of parts."""
    # split on either delimiter because people might use either on
    # Windows
    ps = re.split(r'[\\/]', p)

    rps = []
    for f in ps:
        if f == '..':
            raise errors.BzrError("sorry, %r not allowed in path" % f)
        elif (f == '.') or (f == ''):
            pass
        else:
            rps.append(f)
    return rps

def joinpath(p):
    for f in p:
        if (f == '..') or (f is None) or (f == ''):
            raise errors.BzrError("sorry, %r not allowed in path" % f)
    return pathjoin(*p)


def split_lines(s):
    """Split s into lines, but without removing the newline characters."""
    lines = s.split('\n')
    result = [line + '\n' for line in lines[:-1]]
    if lines[-1]:
        result.append(lines[-1])
    return result


def hardlinks_good():
    return sys.platform not in ('win32', 'cygwin', 'darwin')


def link_or_copy(src, dest):
    """Hardlink a file, or copy it if it can't be hardlinked."""
    if not hardlinks_good():
        shutil.copyfile(src, dest)
        return
    try:
        os.link(src, dest)
    except (OSError, IOError), e:
        if e.errno != errno.EXDEV:
            raise
        shutil.copyfile(src, dest)


# Look Before You Leap (LBYL) is appropriate here instead of Easier to Ask for
# Forgiveness than Permission (EAFP) because:
# - root can damage a solaris file system by using unlink,
# - unlink raises different exceptions on different OSes (linux: EISDIR, win32:
#   EACCES, OSX: EPERM) when invoked on a directory.
def delete_any(path):
    """Delete a file or directory."""
    if isdir(path): # Takes care of symlinks
        os.rmdir(path)
    else:
        os.unlink(path)


def has_symlinks():
    if getattr(os, 'symlink', None) is not None:
        return True
    else:
        return False


def has_hardlinks():
    if getattr(os, 'link', None) is not None:
        return True
    else:
        return False


def host_os_dereferences_symlinks():
    return (has_symlinks()
            and sys.platform not in ('cygwin', 'win32'))


def contains_whitespace(s):
    """True if there are any whitespace characters in s."""
    # string.whitespace can include '\xa0' in certain locales, because it is
    # considered "non-breaking-space" as part of ISO-8859-1. But it
    # 1) Isn't a breaking whitespace
    # 2) Isn't one of ' \t\r\n' which are characters we sometimes use as
    #    separators
    # 3) '\xa0' isn't unicode safe since it is >128.

    # This should *not* be a unicode set of characters in case the source
    # string is not a Unicode string. We can auto-up-cast the characters since
    # they are ascii, but we don't want to auto-up-cast the string in case it
    # is utf-8
    for ch in ' \t\n\r\v\f':
        if ch in s:
            return True
    else:
        return False


def contains_linebreaks(s):
    """True if there is any vertical whitespace in s."""
    for ch in '\f\n\r':
        if ch in s:
            return True
    else:
        return False


def relpath(base, path):
    """Return path relative to base, or raise exception.

    The path may be either an absolute path or a path relative to the
    current working directory.

    os.path.commonprefix (python2.4) has a bad bug that it works just
    on string prefixes, assuming that '/u' is a prefix of '/u2'.  This
    avoids that problem.
    """

    if len(base) < MIN_ABS_PATHLENGTH:
        # must have space for e.g. a drive letter
        raise ValueError('%r is too short to calculate a relative path'
            % (base,))

    rp = abspath(path)

    s = []
    head = rp
    while len(head) >= len(base):
        if head == base:
            break
        head, tail = os.path.split(head)
        if tail:
            s.insert(0, tail)
    else:
        raise errors.PathNotChild(rp, base)

    if s:
        return pathjoin(*s)
    else:
        return ''


def safe_unicode(unicode_or_utf8_string):
    """Coerce unicode_or_utf8_string into unicode.

    If it is unicode, it is returned.
    Otherwise it is decoded from utf-8. If a decoding error
    occurs, it is wrapped as a If the decoding fails, the exception is wrapped 
    as a BzrBadParameter exception.
    """
    if isinstance(unicode_or_utf8_string, unicode):
        return unicode_or_utf8_string
    try:
        return unicode_or_utf8_string.decode('utf8')
    except UnicodeDecodeError:
        raise errors.BzrBadParameterNotUnicode(unicode_or_utf8_string)


def safe_utf8(unicode_or_utf8_string):
    """Coerce unicode_or_utf8_string to a utf8 string.

    If it is a str, it is returned.
    If it is Unicode, it is encoded into a utf-8 string.
    """
    if isinstance(unicode_or_utf8_string, str):
        # TODO: jam 20070209 This is overkill, and probably has an impact on
        #       performance if we are dealing with lots of apis that want a
        #       utf-8 revision id
        try:
            # Make sure it is a valid utf-8 string
            unicode_or_utf8_string.decode('utf-8')
        except UnicodeDecodeError:
            raise errors.BzrBadParameterNotUnicode(unicode_or_utf8_string)
        return unicode_or_utf8_string
    return unicode_or_utf8_string.encode('utf-8')


_revision_id_warning = ('Unicode revision ids were deprecated in bzr 0.15.'
                        ' Revision id generators should be creating utf8'
                        ' revision ids.')


def safe_revision_id(unicode_or_utf8_string, warn=True):
    """Revision ids should now be utf8, but at one point they were unicode.

    :param unicode_or_utf8_string: A possibly Unicode revision_id. (can also be
        utf8 or None).
    :param warn: Functions that are sanitizing user data can set warn=False
    :return: None or a utf8 revision id.
    """
    if (unicode_or_utf8_string is None
        or unicode_or_utf8_string.__class__ == str):
        return unicode_or_utf8_string
    if warn:
        symbol_versioning.warn(_revision_id_warning, DeprecationWarning,
                               stacklevel=2)
    return cache_utf8.encode(unicode_or_utf8_string)


_file_id_warning = ('Unicode file ids were deprecated in bzr 0.15. File id'
                    ' generators should be creating utf8 file ids.')


def safe_file_id(unicode_or_utf8_string, warn=True):
    """File ids should now be utf8, but at one point they were unicode.

    This is the same as safe_utf8, except it uses the cached encode functions
    to save a little bit of performance.

    :param unicode_or_utf8_string: A possibly Unicode file_id. (can also be
        utf8 or None).
    :param warn: Functions that are sanitizing user data can set warn=False
    :return: None or a utf8 file id.
    """
    if (unicode_or_utf8_string is None
        or unicode_or_utf8_string.__class__ == str):
        return unicode_or_utf8_string
    if warn:
        symbol_versioning.warn(_file_id_warning, DeprecationWarning,
                               stacklevel=2)
    return cache_utf8.encode(unicode_or_utf8_string)


_platform_normalizes_filenames = False
if sys.platform == 'darwin':
    _platform_normalizes_filenames = True


def normalizes_filenames():
    """Return True if this platform normalizes unicode filenames.

    Mac OSX does, Windows/Linux do not.
    """
    return _platform_normalizes_filenames


def _accessible_normalized_filename(path):
    """Get the unicode normalized path, and if you can access the file.

    On platforms where the system normalizes filenames (Mac OSX),
    you can access a file by any path which will normalize correctly.
    On platforms where the system does not normalize filenames 
    (Windows, Linux), you have to access a file by its exact path.

    Internally, bzr only supports NFC normalization, since that is 
    the standard for XML documents.

    So return the normalized path, and a flag indicating if the file
    can be accessed by that path.
    """

    return unicodedata.normalize('NFC', unicode(path)), True


def _inaccessible_normalized_filename(path):
    __doc__ = _accessible_normalized_filename.__doc__

    normalized = unicodedata.normalize('NFC', unicode(path))
    return normalized, normalized == path


if _platform_normalizes_filenames:
    normalized_filename = _accessible_normalized_filename
else:
    normalized_filename = _inaccessible_normalized_filename


def terminal_width():
    """Return estimated terminal width."""
    if sys.platform == 'win32':
        return win32utils.get_console_size()[0]
    width = 0
    try:
        import struct, fcntl, termios
        s = struct.pack('HHHH', 0, 0, 0, 0)
        x = fcntl.ioctl(1, termios.TIOCGWINSZ, s)
        width = struct.unpack('HHHH', x)[1]
    except IOError:
        pass
    if width <= 0:
        try:
            width = int(os.environ['COLUMNS'])
        except:
            pass
    if width <= 0:
        width = 80

    return width


def supports_executable():
    return sys.platform != "win32"


def supports_posix_readonly():
    """Return True if 'readonly' has POSIX semantics, False otherwise.

    Notably, a win32 readonly file cannot be deleted, unlike POSIX where the
    directory controls creation/deletion, etc.

    And under win32, readonly means that the directory itself cannot be
    deleted.  The contents of a readonly directory can be changed, unlike POSIX
    where files in readonly directories cannot be added, deleted or renamed.
    """
    return sys.platform != "win32"


def set_or_unset_env(env_variable, value):
    """Modify the environment, setting or removing the env_variable.

    :param env_variable: The environment variable in question
    :param value: The value to set the environment to. If None, then
        the variable will be removed.
    :return: The original value of the environment variable.
    """
    orig_val = os.environ.get(env_variable)
    if value is None:
        if orig_val is not None:
            del os.environ[env_variable]
    else:
        if isinstance(value, unicode):
            value = value.encode(get_user_encoding())
        os.environ[env_variable] = value
    return orig_val


_validWin32PathRE = re.compile(r'^([A-Za-z]:[/\\])?[^:<>*"?\|]*$')


def check_legal_path(path):
    """Check whether the supplied path is legal.  
    This is only required on Windows, so we don't test on other platforms
    right now.
    """
    if sys.platform != "win32":
        return
    if _validWin32PathRE.match(path) is None:
        raise errors.IllegalPath(path)


_WIN32_ERROR_DIRECTORY = 267 # Similar to errno.ENOTDIR

def _is_error_enotdir(e):
    """Check if this exception represents ENOTDIR.

    Unfortunately, python is very inconsistent about the exception
    here. The cases are:
      1) Linux, Mac OSX all versions seem to set errno == ENOTDIR
      2) Windows, Python2.4, uses errno == ERROR_DIRECTORY (267)
         which is the windows error code.
      3) Windows, Python2.5 uses errno == EINVAL and
         winerror == ERROR_DIRECTORY

    :param e: An Exception object (expected to be OSError with an errno
        attribute, but we should be able to cope with anything)
    :return: True if this represents an ENOTDIR error. False otherwise.
    """
    en = getattr(e, 'errno', None)
    if (en == errno.ENOTDIR
        or (sys.platform == 'win32'
            and (en == _WIN32_ERROR_DIRECTORY
                 or (en == errno.EINVAL
                     and getattr(e, 'winerror', None) == _WIN32_ERROR_DIRECTORY)
        ))):
        return True
    return False


def walkdirs(top, prefix=""):
    """Yield data about all the directories in a tree.
    
    This yields all the data about the contents of a directory at a time.
    After each directory has been yielded, if the caller has mutated the list
    to exclude some directories, they are then not descended into.
    
    The data yielded is of the form:
    ((directory-relpath, directory-path-from-top),
    [(relpath, basename, kind, lstat, path-from-top), ...]),
     - directory-relpath is the relative path of the directory being returned
       with respect to top. prefix is prepended to this.
     - directory-path-from-root is the path including top for this directory. 
       It is suitable for use with os functions.
     - relpath is the relative path within the subtree being walked.
     - basename is the basename of the path
     - kind is the kind of the file now. If unknown then the file is not
       present within the tree - but it may be recorded as versioned. See
       versioned_kind.
     - lstat is the stat data *if* the file was statted.
     - planned, not implemented: 
       path_from_tree_root is the path from the root of the tree.

    :param prefix: Prefix the relpaths that are yielded with 'prefix'. This 
        allows one to walk a subtree but get paths that are relative to a tree
        rooted higher up.
    :return: an iterator over the dirs.
    """
    #TODO there is a bit of a smell where the results of the directory-
    # summary in this, and the path from the root, may not agree 
    # depending on top and prefix - i.e. ./foo and foo as a pair leads to
    # potentially confusing output. We should make this more robust - but
    # not at a speed cost. RBC 20060731
    _lstat = os.lstat
    _directory = _directory_kind
    _listdir = os.listdir
    _kind_from_mode = file_kind_from_stat_mode
    pending = [(safe_unicode(prefix), "", _directory, None, safe_unicode(top))]
    while pending:
        # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-toppath
        relroot, _, _, _, top = pending.pop()
        if relroot:
            relprefix = relroot + u'/'
        else:
            relprefix = ''
        top_slash = top + u'/'

        dirblock = []
        append = dirblock.append
        try:
            names = sorted(_listdir(top))
        except OSError, e:
            if not _is_error_enotdir(e):
                raise
        else:
            for name in names:
                abspath = top_slash + name
                statvalue = _lstat(abspath)
                kind = _kind_from_mode(statvalue.st_mode)
                append((relprefix + name, name, kind, statvalue, abspath))
        yield (relroot, top), dirblock

        # push the user specified dirs from dirblock
        pending.extend(d for d in reversed(dirblock) if d[2] == _directory)


class DirReader(object):
    """An interface for reading directories."""

    def top_prefix_to_starting_dir(self, top, prefix=""):
        """Converts top and prefix to a starting dir entry

        :param top: A utf8 path
        :param prefix: An optional utf8 path to prefix output relative paths
            with.
        :return: A tuple starting with prefix, and ending with the native
            encoding of top.
        """
        raise NotImplementedError(self.top_prefix_to_starting_dir)

    def read_dir(self, prefix, top):
        """Read a specific dir.

        :param prefix: A utf8 prefix to be preprended to the path basenames.
        :param top: A natively encoded path to read.
        :return: A list of the directories contents. Each item contains:
            (utf8_relpath, utf8_name, kind, lstatvalue, native_abspath)
        """
        raise NotImplementedError(self.read_dir)


_selected_dir_reader = None


def _walkdirs_utf8(top, prefix=""):
    """Yield data about all the directories in a tree.

    This yields the same information as walkdirs() only each entry is yielded
    in utf-8. On platforms which have a filesystem encoding of utf8 the paths
    are returned as exact byte-strings.

    :return: yields a tuple of (dir_info, [file_info])
        dir_info is (utf8_relpath, path-from-top)
        file_info is (utf8_relpath, utf8_name, kind, lstat, path-from-top)
        if top is an absolute path, path-from-top is also an absolute path.
        path-from-top might be unicode or utf8, but it is the correct path to
        pass to os functions to affect the file in question. (such as os.lstat)
    """
    global _selected_dir_reader
    if _selected_dir_reader is None:
        fs_encoding = _fs_enc.upper()
        if sys.platform == "win32" and win32utils.winver == 'Windows NT':
            # Win98 doesn't have unicode apis like FindFirstFileW
            # TODO: We possibly could support Win98 by falling back to the
            #       original FindFirstFile, and using TCHAR instead of WCHAR,
            #       but that gets a bit tricky, and requires custom compiling
            #       for win98 anyway.
            try:
                from bzrlib._walkdirs_win32 import Win32ReadDir
            except ImportError:
                _selected_dir_reader = UnicodeDirReader()
            else:
                _selected_dir_reader = Win32ReadDir()
        elif fs_encoding not in ('UTF-8', 'US-ASCII', 'ANSI_X3.4-1968'):
            # ANSI_X3.4-1968 is a form of ASCII
            _selected_dir_reader = UnicodeDirReader()
        else:
            try:
                from bzrlib._readdir_pyx import UTF8DirReader
            except ImportError:
                # No optimised code path
                _selected_dir_reader = UnicodeDirReader()
            else:
                _selected_dir_reader = UTF8DirReader()
    # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-toppath
    # But we don't actually uses 1-3 in pending, so set them to None
    pending = [[_selected_dir_reader.top_prefix_to_starting_dir(top, prefix)]]
    read_dir = _selected_dir_reader.read_dir
    _directory = _directory_kind
    while pending:
        relroot, _, _, _, top = pending[-1].pop()
        if not pending[-1]:
            pending.pop()
        dirblock = sorted(read_dir(relroot, top))
        yield (relroot, top), dirblock
        # push the user specified dirs from dirblock
        next = [d for d in reversed(dirblock) if d[2] == _directory]
        if next:
            pending.append(next)


class UnicodeDirReader(DirReader):
    """A dir reader for non-utf8 file systems, which transcodes."""

    __slots__ = ['_utf8_encode']

    def __init__(self):
        self._utf8_encode = codecs.getencoder('utf8')

    def top_prefix_to_starting_dir(self, top, prefix=""):
        """See DirReader.top_prefix_to_starting_dir."""
        return (safe_utf8(prefix), None, None, None, safe_unicode(top))

    def read_dir(self, prefix, top):
        """Read a single directory from a non-utf8 file system.

        top, and the abspath element in the output are unicode, all other paths
        are utf8. Local disk IO is done via unicode calls to listdir etc.

        This is currently the fallback code path when the filesystem encoding is
        not UTF-8. It may be better to implement an alternative so that we can
        safely handle paths that are not properly decodable in the current
        encoding.

        See DirReader.read_dir for details.
        """
        _utf8_encode = self._utf8_encode
        _lstat = os.lstat
        _listdir = os.listdir
        _kind_from_mode = file_kind_from_stat_mode

        if prefix:
            relprefix = prefix + '/'
        else:
            relprefix = ''
        top_slash = top + u'/'

        dirblock = []
        append = dirblock.append
        for name in sorted(_listdir(top)):
            try:
                name_utf8 = _utf8_encode(name)[0]
            except UnicodeDecodeError:
                raise errors.BadFilenameEncoding(
                    _utf8_encode(relprefix)[0] + name, _fs_enc)
            abspath = top_slash + name
            statvalue = _lstat(abspath)
            kind = _kind_from_mode(statvalue.st_mode)
            append((relprefix + name_utf8, name_utf8, kind, statvalue, abspath))
        return dirblock


def copy_tree(from_path, to_path, handlers={}):
    """Copy all of the entries in from_path into to_path.

    :param from_path: The base directory to copy. 
    :param to_path: The target directory. If it does not exist, it will
        be created.
    :param handlers: A dictionary of functions, which takes a source and
        destinations for files, directories, etc.
        It is keyed on the file kind, such as 'directory', 'symlink', or 'file'
        'file', 'directory', and 'symlink' should always exist.
        If they are missing, they will be replaced with 'os.mkdir()',
        'os.readlink() + os.symlink()', and 'shutil.copy2()', respectively.
    """
    # Now, just copy the existing cached tree to the new location
    # We use a cheap trick here.
    # Absolute paths are prefixed with the first parameter
    # relative paths are prefixed with the second.
    # So we can get both the source and target returned
    # without any extra work.

    def copy_dir(source, dest):
        os.mkdir(dest)

    def copy_link(source, dest):
        """Copy the contents of a symlink"""
        link_to = os.readlink(source)
        os.symlink(link_to, dest)

    real_handlers = {'file':shutil.copy2,
                     'symlink':copy_link,
                     'directory':copy_dir,
                    }
    real_handlers.update(handlers)

    if not os.path.exists(to_path):
        real_handlers['directory'](from_path, to_path)

    for dir_info, entries in walkdirs(from_path, prefix=to_path):
        for relpath, name, kind, st, abspath in entries:
            real_handlers[kind](abspath, relpath)


def path_prefix_key(path):
    """Generate a prefix-order path key for path.

    This can be used to sort paths in the same way that walkdirs does.
    """
    return (dirname(path) , path)


def compare_paths_prefix_order(path_a, path_b):
    """Compare path_a and path_b to generate the same order walkdirs uses."""
    key_a = path_prefix_key(path_a)
    key_b = path_prefix_key(path_b)
    return cmp(key_a, key_b)


_cached_user_encoding = None


def get_user_encoding(use_cache=True):
    """Find out what the preferred user encoding is.

    This is generally the encoding that is used for command line parameters
    and file contents. This may be different from the terminal encoding
    or the filesystem encoding.

    :param  use_cache:  Enable cache for detected encoding.
                        (This parameter is turned on by default,
                        and required only for selftesting)

    :return: A string defining the preferred user encoding
    """
    global _cached_user_encoding
    if _cached_user_encoding is not None and use_cache:
        return _cached_user_encoding

    if sys.platform == 'darwin':
        # python locale.getpreferredencoding() always return
        # 'mac-roman' on darwin. That's a lie.
        sys.platform = 'posix'
        try:
            if os.environ.get('LANG', None) is None:
                # If LANG is not set, we end up with 'ascii', which is bad
                # ('mac-roman' is more than ascii), so we set a default which
                # will give us UTF-8 (which appears to work in all cases on
                # OSX). Users are still free to override LANG of course, as
                # long as it give us something meaningful. This work-around
                # *may* not be needed with python 3k and/or OSX 10.5, but will
                # work with them too -- vila 20080908
                os.environ['LANG'] = 'en_US.UTF-8'
            import locale
        finally:
            sys.platform = 'darwin'
    else:
        import locale

    try:
        user_encoding = locale.getpreferredencoding()
    except locale.Error, e:
        sys.stderr.write('bzr: warning: %s\n'
                         '  Could not determine what text encoding to use.\n'
                         '  This error usually means your Python interpreter\n'
                         '  doesn\'t support the locale set by $LANG (%s)\n'
                         "  Continuing with ascii encoding.\n"
                         % (e, os.environ.get('LANG')))
        user_encoding = 'ascii'

    # Windows returns 'cp0' to indicate there is no code page. So we'll just
    # treat that as ASCII, and not support printing unicode characters to the
    # console.
    #
    # For python scripts run under vim, we get '', so also treat that as ASCII
    if user_encoding in (None, 'cp0', ''):
        user_encoding = 'ascii'
    else:
        # check encoding
        try:
            codecs.lookup(user_encoding)
        except LookupError:
            sys.stderr.write('bzr: warning:'
                             ' unknown encoding %s.'
                             ' Continuing with ascii encoding.\n'
                             % user_encoding
                            )
            user_encoding = 'ascii'

    if use_cache:
        _cached_user_encoding = user_encoding

    return user_encoding


def get_host_name():
    """Return the current unicode host name.

    This is meant to be used in place of socket.gethostname() because that
    behaves inconsistently on different platforms.
    """
    if sys.platform == "win32":
        import win32utils
        return win32utils.get_host_name()
    else:
        import socket
        return socket.gethostname().decode(get_user_encoding())


def recv_all(socket, bytes):
    """Receive an exact number of bytes.

    Regular Socket.recv() may return less than the requested number of bytes,
    dependning on what's in the OS buffer.  MSG_WAITALL is not available
    on all platforms, but this should work everywhere.  This will return
    less than the requested amount if the remote end closes.

    This isn't optimized and is intended mostly for use in testing.
    """
    b = ''
    while len(b) < bytes:
        new = socket.recv(bytes - len(b))
        if new == '':
            break # eof
        b += new
    return b


def send_all(socket, bytes):
    """Send all bytes on a socket.

    Regular socket.sendall() can give socket error 10053 on Windows.  This
    implementation sends no more than 64k at a time, which avoids this problem.
    """
    chunk_size = 2**16
    for pos in xrange(0, len(bytes), chunk_size):
        socket.sendall(bytes[pos:pos+chunk_size])


def dereference_path(path):
    """Determine the real path to a file.

    All parent elements are dereferenced.  But the file itself is not
    dereferenced.
    :param path: The original path.  May be absolute or relative.
    :return: the real path *to* the file
    """
    parent, base = os.path.split(path)
    # The pathjoin for '.' is a workaround for Python bug #1213894.
    # (initial path components aren't dereferenced)
    return pathjoin(realpath(pathjoin('.', parent)), base)


def supports_mapi():
    """Return True if we can use MAPI to launch a mail client."""
    return sys.platform == "win32"


def resource_string(package, resource_name):
    """Load a resource from a package and return it as a string.

    Note: Only packages that start with bzrlib are currently supported.

    This is designed to be a lightweight implementation of resource
    loading in a way which is API compatible with the same API from
    pkg_resources. See
    http://peak.telecommunity.com/DevCenter/PkgResources#basic-resource-access.
    If and when pkg_resources becomes a standard library, this routine
    can delegate to it.
    """
    # Check package name is within bzrlib
    if package == "bzrlib":
        resource_relpath = resource_name
    elif package.startswith("bzrlib."):
        package = package[len("bzrlib."):].replace('.', os.sep)
        resource_relpath = pathjoin(package, resource_name)
    else:
        raise errors.BzrError('resource package %s not in bzrlib' % package)

    # Map the resource to a file and read its contents
    base = dirname(bzrlib.__file__)
    if getattr(sys, 'frozen', None):    # bzr.exe
        base = abspath(pathjoin(base, '..', '..'))
    filename = pathjoin(base, resource_relpath)
    return open(filename, 'rU').read()


def file_kind_from_stat_mode_thunk(mode):
    global file_kind_from_stat_mode
    if file_kind_from_stat_mode is file_kind_from_stat_mode_thunk:
        try:
            from bzrlib._readdir_pyx import UTF8DirReader
            file_kind_from_stat_mode = UTF8DirReader().kind_from_mode
        except ImportError:
            from bzrlib._readdir_py import (
                _kind_from_mode as file_kind_from_stat_mode
                )
    return file_kind_from_stat_mode(mode)
file_kind_from_stat_mode = file_kind_from_stat_mode_thunk


def file_kind(f, _lstat=os.lstat):
    try:
        return file_kind_from_stat_mode(_lstat(f).st_mode)
    except OSError, e:
        if getattr(e, 'errno', None) in (errno.ENOENT, errno.ENOTDIR):
            raise errors.NoSuchFile(f)
        raise

if sys.platform == "win32":
    import msvcrt
    def getchar():
        return msvcrt.getch()
else:
    import tty
    import termios
    def getchar():
        fd = sys.stdin.fileno()
        settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        return ch
