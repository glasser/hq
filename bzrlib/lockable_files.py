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

from cStringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import codecs
import warnings

from bzrlib import (
    errors,
    osutils,
    transactions,
    urlutils,
    )
""")

from bzrlib.decorators import (
    needs_read_lock,
    needs_write_lock,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )


# XXX: The tracking here of lock counts and whether the lock is held is
# somewhat redundant with what's done in LockDir; the main difference is that
# LockableFiles permits reentrancy.

class LockableFiles(object):
    """Object representing a set of related files locked within the same scope.

    These files are used by a WorkingTree, Repository or Branch, and should
    generally only be touched by that object.

    LockableFiles also provides some policy on top of Transport for encoding
    control files as utf-8.

    LockableFiles manage a lock count and can be locked repeatedly by
    a single caller.  (The underlying lock implementation generally does not
    support this.)

    Instances of this class are often called control_files.
    
    This object builds on top of a Transport, which is used to actually write
    the files to disk, and an OSLock or LockDir, which controls how access to
    the files is controlled.  The particular type of locking used is set when
    the object is constructed.  In older formats OSLocks are used everywhere.
    in newer formats a LockDir is used for Repositories and Branches, and 
    OSLocks for the local filesystem.

    This class is now deprecated; code should move to using the Transport 
    directly for file operations and using the lock or CountedLock for 
    locking.
    """

    # _lock_mode: None, or 'r' or 'w'

    # _lock_count: If _lock_mode is true, a positive count of the number of
    # times the lock has been taken *by this process*.   
    
    def __init__(self, transport, lock_name, lock_class):
        """Create a LockableFiles group

        :param transport: Transport pointing to the directory holding the 
            control files and lock.
        :param lock_name: Name of the lock guarding these files.
        :param lock_class: Class of lock strategy to use: typically
            either LockDir or TransportLock.
        """
        self._transport = transport
        self.lock_name = lock_name
        self._transaction = None
        self._lock_mode = None
        self._lock_count = 0
        self._find_modes()
        esc_name = self._escape(lock_name)
        self._lock = lock_class(transport, esc_name,
                                file_modebits=self._file_mode,
                                dir_modebits=self._dir_mode)

    def create_lock(self):
        """Create the lock.

        This should normally be called only when the LockableFiles directory
        is first created on disk.
        """
        self._lock.create(mode=self._dir_mode)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self._transport)
    def __str__(self):
        return 'LockableFiles(%s, %s)' % (self.lock_name, self._transport.base)

    def __del__(self):
        if self.is_locked():
            # do not automatically unlock; there should have been a
            # try/finally to unlock this.
            warnings.warn("%r was gc'd while locked" % self)

    def break_lock(self):
        """Break the lock of this lockable files group if it is held.

        The current ui factory will be used to prompt for user conformation.
        """
        self._lock.break_lock()

    def _escape(self, file_or_path):
        """DEPRECATED: Do not use outside this class"""
        if not isinstance(file_or_path, basestring):
            file_or_path = '/'.join(file_or_path)
        if file_or_path == '':
            return u''
        return urlutils.escape(osutils.safe_unicode(file_or_path))

    def _find_modes(self):
        """Determine the appropriate modes for files and directories.
        
        :deprecated: Replaced by BzrDir._find_modes.
        """
        try:
            st = self._transport.stat('.')
        except errors.TransportNotPossible:
            self._dir_mode = 0755
            self._file_mode = 0644
        else:
            # Check the directory mode, but also make sure the created
            # directories and files are read-write for this user. This is
            # mostly a workaround for filesystems which lie about being able to
            # write to a directory (cygwin & win32)
            self._dir_mode = (st.st_mode & 07777) | 00700
            # Remove the sticky and execute bits for files
            self._file_mode = self._dir_mode & ~07111

    @deprecated_method(deprecated_in((1, 6, 0)))
    def controlfilename(self, file_or_path):
        """Return location relative to branch.
        
        :deprecated: Use Transport methods instead.
        """
        return self._transport.abspath(self._escape(file_or_path))

    @needs_read_lock
    @deprecated_method(deprecated_in((1, 5, 0)))
    def get(self, relpath):
        """Get a file as a bytestream.
        
        :deprecated: Use a Transport instead of LockableFiles.
        """
        relpath = self._escape(relpath)
        return self._transport.get(relpath)

    @needs_read_lock
    @deprecated_method(deprecated_in((1, 5, 0)))
    def get_utf8(self, relpath):
        """Get a file as a unicode stream.
        
        :deprecated: Use a Transport instead of LockableFiles.
        """
        relpath = self._escape(relpath)
        # DO NOT introduce an errors=replace here.
        return codecs.getreader('utf-8')(self._transport.get(relpath))

    @needs_write_lock
    @deprecated_method(deprecated_in((1, 6, 0)))
    def put(self, path, file):
        """Write a file.
        
        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param file: A file-like or string object whose contents should be copied.

        :deprecated: Use Transport methods instead.
        """
        self._transport.put_file(self._escape(path), file, mode=self._file_mode)

    @needs_write_lock
    @deprecated_method(deprecated_in((1, 6, 0)))
    def put_bytes(self, path, a_string):
        """Write a string of bytes.

        :param path: The path to put the bytes, relative to the transport root.
        :param a_string: A string object, whose exact bytes are to be copied.

        :deprecated: Use Transport methods instead.
        """
        self._transport.put_bytes(self._escape(path), a_string,
                                  mode=self._file_mode)

    @needs_write_lock
    @deprecated_method(deprecated_in((1, 6, 0)))
    def put_utf8(self, path, a_string):
        """Write a string, encoding as utf-8.

        :param path: The path to put the string, relative to the transport root.
        :param string: A string or unicode object whose contents should be copied.

        :deprecated: Use Transport methods instead.
        """
        # IterableFile would not be needed if Transport.put took iterables
        # instead of files.  ADHB 2005-12-25
        # RBC 20060103 surely its not needed anyway, with codecs transcode
        # file support ?
        # JAM 20060103 We definitely don't want encode(..., 'replace')
        # these are valuable files which should have exact contents.
        if not isinstance(a_string, basestring):
            raise errors.BzrBadParameterNotString(a_string)
        self.put_bytes(path, a_string.encode('utf-8'))

    def leave_in_place(self):
        """Set this LockableFiles to not clear the physical lock on unlock."""
        self._lock.leave_in_place()

    def dont_leave_in_place(self):
        """Set this LockableFiles to clear the physical lock on unlock."""
        self._lock.dont_leave_in_place()

    def lock_write(self, token=None):
        """Lock this group of files for writing.
        
        :param token: if this is already locked, then lock_write will fail
            unless the token matches the existing lock.
        :returns: a token if this instance supports tokens, otherwise None.
        :raises TokenLockingNotSupported: when a token is given but this
            instance doesn't support using token locks.
        :raises MismatchedToken: if the specified token doesn't match the token
            of the existing lock.

        A token should be passed in if you know that you have locked the object
        some other way, and need to synchronise this object's state with that
        fact.
        """
        # TODO: Upgrade locking to support using a Transport,
        # and potentially a remote locking protocol
        if self._lock_mode:
            if self._lock_mode != 'w' or not self.get_transaction().writeable():
                raise errors.ReadOnlyError(self)
            self._lock.validate_token(token)
            self._lock_count += 1
            return self._token_from_lock
        else:
            token_from_lock = self._lock.lock_write(token=token)
            #traceback.print_stack()
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_transaction(transactions.WriteTransaction())
            self._token_from_lock = token_from_lock
            return token_from_lock

    def lock_read(self):
        if self._lock_mode:
            if self._lock_mode not in ('r', 'w'):
                raise ValueError("invalid lock mode %r" % (self._lock_mode,))
            self._lock_count += 1
        else:
            self._lock.lock_read()
            #traceback.print_stack()
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_transaction(transactions.ReadOnlyTransaction())
            # 5K may be excessive, but hey, its a knob.
            self.get_transaction().set_cache_size(5000)
                        
    def unlock(self):
        if not self._lock_mode:
            raise errors.LockNotHeld(self)
        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            #traceback.print_stack()
            self._finish_transaction()
            try:
                self._lock.unlock()
            finally:
                self._lock_mode = self._lock_count = None

    def is_locked(self):
        """Return true if this LockableFiles group is locked"""
        return self._lock_count >= 1

    def get_physical_lock_status(self):
        """Return physical lock status.
        
        Returns true if a lock is held on the transport. If no lock is held, or
        the underlying locking mechanism does not support querying lock
        status, false is returned.
        """
        try:
            return self._lock.peek() is not None
        except NotImplementedError:
            return False

    def get_transaction(self):
        """Return the current active transaction.

        If no transaction is active, this returns a passthrough object
        for which all data is immediately flushed and no caching happens.
        """
        if self._transaction is None:
            return transactions.PassThroughTransaction()
        else:
            return self._transaction

    def _set_transaction(self, new_transaction):
        """Set a new active transaction."""
        if self._transaction is not None:
            raise errors.LockError('Branch %s is in a transaction already.' %
                                   self)
        self._transaction = new_transaction

    def _finish_transaction(self):
        """Exit the current transaction."""
        if self._transaction is None:
            raise errors.LockError('Branch %s is not in a transaction' %
                                   self)
        transaction = self._transaction
        self._transaction = None
        transaction.finish()


class TransportLock(object):
    """Locking method which uses transport-dependent locks.

    On the local filesystem these transform into OS-managed locks.

    These do not guard against concurrent access via different
    transports.

    This is suitable for use only in WorkingTrees (which are at present
    always local).
    """
    def __init__(self, transport, escaped_name, file_modebits, dir_modebits):
        self._transport = transport
        self._escaped_name = escaped_name
        self._file_modebits = file_modebits
        self._dir_modebits = dir_modebits

    def break_lock(self):
        raise NotImplementedError(self.break_lock)

    def leave_in_place(self):
        raise NotImplementedError(self.leave_in_place)

    def dont_leave_in_place(self):
        raise NotImplementedError(self.dont_leave_in_place)

    def lock_write(self, token=None):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
        self._lock = self._transport.lock_write(self._escaped_name)

    def lock_read(self):
        self._lock = self._transport.lock_read(self._escaped_name)

    def unlock(self):
        self._lock.unlock()
        self._lock = None

    def peek(self):
        raise NotImplementedError()

    def create(self, mode=None):
        """Create lock mechanism"""
        # for old-style locks, create the file now
        self._transport.put_bytes(self._escaped_name, '',
                            mode=self._file_modebits)

    def validate_token(self, token):
        if token is not None:
            raise errors.TokenLockingNotSupported(self)
        
