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

"""Implementation of Transport that uses memory for its storage.

The contents of the transport will be lost when the object is discarded,
so this is primarily useful for testing.
"""

import os
import errno
import re
from stat import S_IFREG, S_IFDIR
from cStringIO import StringIO
import warnings

from bzrlib.errors import (
    FileExists,
    LockError,
    InProcessTransport,
    NoSuchFile,
    TransportError,
    )
from bzrlib.trace import mutter
from bzrlib.transport import (
    AppendBasedFileStream,
    _file_streams,
    LateReadError,
    register_transport,
    Server,
    Transport,
    )
import bzrlib.urlutils as urlutils



class MemoryStat(object):

    def __init__(self, size, is_dir, perms):
        self.st_size = size
        if not is_dir:
            if perms is None:
                perms = 0644
            self.st_mode = S_IFREG | perms
        else:
            if perms is None:
                perms = 0755
            self.st_mode = S_IFDIR | perms


class MemoryTransport(Transport):
    """This is an in memory file system for transient data storage."""

    def __init__(self, url=""):
        """Set the 'base' path where files will be stored."""
        if url == "":
            url = "memory:///"
        if url[-1] != '/':
            url = url + '/'
        super(MemoryTransport, self).__init__(url)
        split = url.find(':') + 3
        self._scheme = url[:split]
        self._cwd = url[split:]
        # dictionaries from absolute path to file mode
        self._dirs = {'/':None}
        self._files = {}
        self._locks = {}

    def clone(self, offset=None):
        """See Transport.clone()."""
        path = self._combine_paths(self._cwd, offset)
        if len(path) == 0 or path[-1] != '/':
            path += '/'
        url = self._scheme + path
        result = MemoryTransport(url)
        result._dirs = self._dirs
        result._files = self._files
        result._locks = self._locks
        return result

    def abspath(self, relpath):
        """See Transport.abspath()."""
        # while a little slow, this is sufficiently fast to not matter in our
        # current environment - XXX RBC 20060404 move the clone '..' handling
        # into here and call abspath from clone
        temp_t = self.clone(relpath)
        if temp_t.base.count('/') == 3:
            return temp_t.base
        else:
            return temp_t.base[:-1]

    def append_file(self, relpath, f, mode=None):
        """See Transport.append_file()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        orig_content, orig_mode = self._files.get(_abspath, ("", None))
        if mode is None:
            mode = orig_mode
        self._files[_abspath] = (orig_content + f.read(), mode)
        return len(orig_content)

    def _check_parent(self, _abspath):
        dir = os.path.dirname(_abspath)
        if dir != '/':
            if not dir in self._dirs:
                raise NoSuchFile(_abspath)

    def has(self, relpath):
        """See Transport.has()."""
        _abspath = self._abspath(relpath)
        return (_abspath in self._files) or (_abspath in self._dirs)

    def delete(self, relpath):
        """See Transport.delete()."""
        _abspath = self._abspath(relpath)
        if not _abspath in self._files:
            raise NoSuchFile(relpath)
        del self._files[_abspath]

    def external_url(self):
        """See bzrlib.transport.Transport.external_url."""
        # MemoryTransport's are only accessible in-process
        # so we raise here
        raise InProcessTransport(self)

    def get(self, relpath):
        """See Transport.get()."""
        _abspath = self._abspath(relpath)
        if not _abspath in self._files:
            if _abspath in self._dirs:
                return LateReadError(relpath)
            else:
                raise NoSuchFile(relpath)
        return StringIO(self._files[_abspath][0])

    def put_file(self, relpath, f, mode=None):
        """See Transport.put_file()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        bytes = f.read()
        if type(bytes) is not str:
            # Although not strictly correct, we raise UnicodeEncodeError to be
            # compatible with other transports.
            raise UnicodeEncodeError(
                'undefined', bytes, 0, 1,
                'put_file must be given a file of bytes, not unicode.')
        self._files[_abspath] = (bytes, mode)
        return len(bytes)

    def mkdir(self, relpath, mode=None):
        """See Transport.mkdir()."""
        _abspath = self._abspath(relpath)
        self._check_parent(_abspath)
        if _abspath in self._dirs:
            raise FileExists(relpath)
        self._dirs[_abspath]=mode

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        self.put_bytes(relpath, "", mode)
        result = AppendBasedFileStream(self, relpath)
        _file_streams[self.abspath(relpath)] = result
        return result

    def listable(self):
        """See Transport.listable."""
        return True

    def iter_files_recursive(self):
        for file in self._files:
            if file.startswith(self._cwd):
                yield urlutils.escape(file[len(self._cwd):])
    
    def list_dir(self, relpath):
        """See Transport.list_dir()."""
        _abspath = self._abspath(relpath)
        if _abspath != '/' and _abspath not in self._dirs:
            raise NoSuchFile(relpath)
        result = []

        if not _abspath.endswith('/'):
            _abspath += '/'

        for path_group in self._files, self._dirs:
            for path in path_group:
                if path.startswith(_abspath):
                    trailing = path[len(_abspath):]
                    if trailing and '/' not in trailing:
                        result.append(trailing)
        return map(urlutils.escape, result)

    def rename(self, rel_from, rel_to):
        """Rename a file or directory; fail if the destination exists"""
        abs_from = self._abspath(rel_from)
        abs_to = self._abspath(rel_to)
        def replace(x):
            if x == abs_from:
                x = abs_to
            elif x.startswith(abs_from + '/'):
                x = abs_to + x[len(abs_from):]
            return x
        def do_renames(container):
            for path in container:
                new_path = replace(path)
                if new_path != path:
                    if new_path in container:
                        raise FileExists(new_path)
                    container[new_path] = container[path]
                    del container[path]
        do_renames(self._files)
        do_renames(self._dirs)
    
    def rmdir(self, relpath):
        """See Transport.rmdir."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            self._translate_error(IOError(errno.ENOTDIR, relpath), relpath)
        for path in self._files:
            if path.startswith(_abspath + '/'):
                self._translate_error(IOError(errno.ENOTEMPTY, relpath),
                                      relpath)
        for path in self._dirs:
            if path.startswith(_abspath + '/') and path != _abspath:
                self._translate_error(IOError(errno.ENOTEMPTY, relpath), relpath)
        if not _abspath in self._dirs:
            raise NoSuchFile(relpath)
        del self._dirs[_abspath]

    def stat(self, relpath):
        """See Transport.stat()."""
        _abspath = self._abspath(relpath)
        if _abspath in self._files:
            return MemoryStat(len(self._files[_abspath][0]), False, 
                              self._files[_abspath][1])
        elif _abspath in self._dirs:
            return MemoryStat(0, True, self._dirs[_abspath])
        else:
            raise NoSuchFile(_abspath)

    def lock_read(self, relpath):
        """See Transport.lock_read()."""
        return _MemoryLock(self._abspath(relpath), self)

    def lock_write(self, relpath):
        """See Transport.lock_write()."""
        return _MemoryLock(self._abspath(relpath), self)

    def _abspath(self, relpath):
        """Generate an internal absolute path."""
        relpath = urlutils.unescape(relpath)
        if relpath[:1] == '/':
            return relpath
        cwd_parts = self._cwd.split('/')
        rel_parts = relpath.split('/')
        r = []
        for i in cwd_parts + rel_parts:
            if i == '..':
                if not r:
                    raise ValueError("illegal relpath %r under %r"
                        % (relpath, self._cwd))
                r = r[:-1]
            elif i == '.' or i == '':
                pass
            else:
                r.append(i)
        return '/' + '/'.join(r)


class _MemoryLock(object):
    """This makes a lock."""

    def __init__(self, path, transport):
        self.path = path
        self.transport = transport
        if self.path in self.transport._locks:
            raise LockError('File %r already locked' % (self.path,))
        self.transport._locks[self.path] = self

    def __del__(self):
        # Should this warn, or actually try to cleanup?
        if self.transport:
            warnings.warn("MemoryLock %r not explicitly unlocked" % (self.path,))
            self.unlock()

    def unlock(self):
        del self.transport._locks[self.path]
        self.transport = None


class MemoryServer(Server):
    """Server for the MemoryTransport for testing with."""

    def setUp(self):
        """See bzrlib.transport.Server.setUp."""
        self._dirs = {'/':None}
        self._files = {}
        self._locks = {}
        self._scheme = "memory+%s:///" % id(self)
        def memory_factory(url):
            result = MemoryTransport(url)
            result._dirs = self._dirs
            result._files = self._files
            result._locks = self._locks
            return result
        register_transport(self._scheme, memory_factory)

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        # unregister this server

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self._scheme


def get_test_permutations():
    """Return the permutations to be used in testing."""
    return [(MemoryTransport, MemoryServer),
            ]
