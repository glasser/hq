# Copyright (C) 2004, 2005 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import stat
import socket
import warnings

from bzrlib import (
    errors,
    osutils,
    symbol_versioning,
    )
""")

# not forksafe - but we dont fork.
_pid = os.getpid()
_hostname = None


class AtomicFile(object):
    """A file that does an atomic-rename to move into place.

    This also causes hardlinks to break when it's written out.

    Open this as for a regular file, then use commit() to move into
    place or abort() to cancel.
    """

    __slots__ = ['tmpfilename', 'realfilename', '_fd']

    def __init__(self, filename, mode='wb', new_mode=None):
        global _hostname

        self._fd = None

        if _hostname is None:
            _hostname = osutils.get_host_name()

        self.tmpfilename = '%s.%d.%s.tmp' % (filename, _pid, _hostname)

        self.realfilename = filename
        
        flags = os.O_EXCL | os.O_CREAT | os.O_WRONLY
        if mode == 'wb':
            flags |= osutils.O_BINARY
        elif mode != 'wt':
            raise ValueError("invalid AtomicFile mode %r" % mode)

        if new_mode is not None:
            local_mode = new_mode
        else:
            local_mode = 0666
        
        # Use a low level fd operation to avoid chmodding later.
        # This may not succeed, but it should help most of the time
        self._fd = os.open(self.tmpfilename, flags, local_mode)

        if new_mode is not None:
            # Because of umask issues, we may need to chmod anyway
            # the common case is that we won't, though.
            st = os.fstat(self._fd)
            if stat.S_IMODE(st.st_mode) != new_mode:
                os.chmod(self.tmpfilename, new_mode)

    def _get_closed(self):
        symbol_versioning.warn('AtomicFile.closed deprecated in bzr 0.10',
                               DeprecationWarning, stacklevel=2)
        return self._fd is None

    closed = property(_get_closed)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self.realfilename)

    def write(self, data):
        """Write some data to the file. Like file.write()"""
        os.write(self._fd, data)

    def _close_tmpfile(self, func_name):
        """Close the local temp file in preparation for commit or abort"""
        if self._fd is None:
            raise errors.AtomicFileAlreadyClosed(path=self.realfilename,
                                                 function=func_name)
        fd = self._fd
        self._fd = None
        os.close(fd)

    def commit(self):
        """Close the file and move to final name."""
        self._close_tmpfile('commit')
        osutils.rename(self.tmpfilename, self.realfilename)

    def abort(self):
        """Discard temporary file without committing changes."""
        self._close_tmpfile('abort')
        os.remove(self.tmpfilename)

    def close(self):
        """Discard the file unless already committed."""
        if self._fd is not None:
            self.abort()

    def __del__(self):
        if self._fd is not None:
            warnings.warn("%r leaked" % self)
