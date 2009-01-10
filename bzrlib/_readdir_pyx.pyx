# Copyright (C) 2006, 2008 Canonical Ltd
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

"""Wrapper for readdir which returns files ordered by inode."""


import os
import sys

#python2.4 support
cdef extern from "python-compat.h":
    pass


cdef extern from 'errno.h':
    int ENOENT
    int ENOTDIR
    int EAGAIN
    int EINTR
    char *strerror(int errno)
    # not necessarily a real variable, but this should be close enough
    int errno

cdef extern from 'unistd.h':
    int chdir(char *path)
    int close(int fd)
    int fchdir(int fd)
    char *getcwd(char *, int size)

cdef extern from 'stdlib.h':
    void *malloc(int)
    void free(void *)


cdef extern from 'sys/types.h':
    ctypedef long ssize_t
    ctypedef unsigned long size_t
    ctypedef long time_t
    ctypedef unsigned long ino_t
    ctypedef unsigned long long off_t
    ctypedef int mode_t


cdef extern from 'sys/stat.h':
    cdef struct stat:
        int st_mode
        off_t st_size
        int st_dev
        ino_t st_ino
        int st_mtime
        int st_ctime
    int lstat(char *path, stat *buf)
    int S_ISDIR(int mode)
    int S_ISCHR(int mode)
    int S_ISBLK(int mode)
    int S_ISREG(int mode)
    int S_ISFIFO(int mode)
    int S_ISLNK(int mode)
    int S_ISSOCK(int mode)


cdef extern from 'fcntl.h':
    int O_RDONLY
    int open(char *pathname, int flags, mode_t mode)


cdef extern from 'Python.h':
    char * PyString_AS_STRING(object)
    ctypedef int Py_ssize_t # Required for older pyrex versions
    ctypedef struct PyObject:
        pass
    Py_ssize_t PyString_Size(object s)
    object PyList_GetItem(object lst, Py_ssize_t index)
    void *PyList_GetItem_object_void "PyList_GET_ITEM" (object lst, int index)
    int PyList_Append(object lst, object item) except -1
    void *PyTuple_GetItem_void_void "PyTuple_GET_ITEM" (void* tpl, int index)
    int PyTuple_SetItem(void *, Py_ssize_t pos, object item) except -1
    int PyTuple_SetItem_obj "PyTuple_SetItem" (void *, Py_ssize_t pos, PyObject * item) except -1
    void Py_INCREF(object o)
    void Py_DECREF(object o)
    void PyString_Concat(PyObject **string, object newpart)


cdef extern from 'dirent.h':
    ctypedef struct dirent:
        char d_name[256]
        ino_t d_ino
    # the opaque C library DIR type.
    ctypedef struct DIR
    # should be DIR *, pyrex barfs.
    DIR * opendir(char * name)
    int closedir(DIR * dir)
    dirent *readdir(DIR *dir)

_directory = 'directory'
_chardev = 'chardev'
_block = 'block'
_file = 'file'
_fifo = 'fifo'
_symlink = 'symlink'
_socket = 'socket'
_unknown = 'unknown'
_missing = 'missing'

# add a typedef struct dirent dirent to workaround pyrex
cdef extern from 'readdir.h':
    pass


cdef class _Stat:
    """Represent a 'stat' result."""

    cdef stat _st

    property st_dev:
        def __get__(self):
            return self._st.st_dev

    property st_ino:
        def __get__(self):
            return self._st.st_ino

    property st_mode:
        def __get__(self):
            return self._st.st_mode

    property st_ctime:
        def __get__(self):
            return self._st.st_ctime

    property st_mtime:
        def __get__(self):
            return self._st.st_mtime

    property st_size:
        def __get__(self):
            return self._st.st_size

    def __repr__(self):
        """Repr is the same as a Stat object.

        (mode, ino, dev, nlink, uid, gid, size, None(atime), mtime, ctime)
        """
        return repr((self.st_mode, 0, 0, 0, 0, 0, self.st_size, None,
                     self._mtime, self._ctime))


from bzrlib import osutils


cdef class UTF8DirReader:
    """A dir reader for utf8 file systems."""

    cdef readonly object _safe_utf8
    cdef _directory, _chardev, _block, _file, _fifo, _symlink
    cdef _socket, _unknown

    def __init__(self):
        self._safe_utf8 = osutils.safe_utf8
        self._directory = _directory
        self._chardev = _chardev
        self._block = _block
        self._file = _file
        self._fifo = _fifo
        self._symlink = _symlink
        self._socket = _socket
        self._unknown = _unknown

    def kind_from_mode(self, int mode):
        """Get the kind of a path from a mode status."""
        return self._kind_from_mode(mode)

    cdef _kind_from_mode(self, int mode):
        # Files and directories are the most common - check them first.
        if S_ISREG(mode):
            return self._file
        if S_ISDIR(mode):
            return self._directory
        if S_ISCHR(mode):
            return self._chardev
        if S_ISBLK(mode):
            return self._block
        if S_ISLNK(mode):
            return self._symlink
        if S_ISFIFO(mode):
            return self._fifo
        if S_ISSOCK(mode):
            return self._socket
        return self._unknown

    def top_prefix_to_starting_dir(self, top, prefix=""):
        """See DirReader.top_prefix_to_starting_dir."""
        return (self._safe_utf8(prefix), None, None, None,
            self._safe_utf8(top))

    def read_dir(self, prefix, top):
        """Read a single directory from a utf8 file system.

        All paths in and out are utf8.

        This sub-function is called when we know the filesystem is already in utf8
        encoding. So we don't need to transcode filenames.

        See DirReader.read_dir for details.
        """
        #cdef char *_prefix = prefix
        #cdef char *_top = top
        # Use C accelerated directory listing.
        cdef object newval
        cdef int index
        cdef int length
        cdef void * atuple
        cdef object name
        cdef PyObject * new_val_obj

        if PyString_Size(prefix):
            relprefix = prefix + '/'
        else:
            relprefix = ''
        top_slash = top + '/'

        # read_dir supplies in should-stat order.
        # for _, name in sorted(_listdir(top)):
        result = _read_dir(top)
        length = len(result)
        # result.sort()
        for index from 0 <= index < length:
            atuple = PyList_GetItem_object_void(result, index)
            name = <object>PyTuple_GetItem_void_void(atuple, 1)
            # We have a tuple with (inode, name, None, statvalue, None)
            # Now edit it:
            # inode -> path_from_top
            # direct concat - faster than operator +.
            new_val_obj = <PyObject *>relprefix
            Py_INCREF(relprefix)
            PyString_Concat(&new_val_obj, name)
            if NULL == new_val_obj:
                # PyString_Concat will have setup an exception, but how to get
                # at it?
                raise Exception("failed to strcat")
            PyTuple_SetItem_obj(atuple, 0, new_val_obj)
            # 1st None -> kind
            newval = self._kind_from_mode(
                (<_Stat>PyTuple_GetItem_void_void(atuple, 3)).st_mode)
            Py_INCREF(newval)
            PyTuple_SetItem(atuple, 2, newval)
            # 2nd None -> abspath # for all - the caller may need to stat files
            # etc.
            # direct concat - faster than operator +.
            new_val_obj = <PyObject *>top_slash
            Py_INCREF(top_slash)
            PyString_Concat(&new_val_obj, name)
            if NULL == new_val_obj:
                # PyString_Concat will have setup an exception, but how to get
                # at it?
                raise Exception("failed to strcat")
            PyTuple_SetItem_obj(atuple, 4, new_val_obj)
        return result


cdef _read_dir(path):
    """Like os.listdir, this reads the contents of a directory.

    :param path: the directory to list.
    :return: a list of single-owner (the list) tuples ready for editing into
        the result tuples walkdirs needs to yield. They contain (inode, name,
        None, statvalue, None).
    """
    cdef DIR *the_dir
    # currently this needs a fixup - the C code says 'dirent' but should say
    # 'struct dirent'
    cdef dirent * entry
    cdef dirent sentinel
    cdef char *name
    cdef int stat_result
    cdef _Stat statvalue
    global errno
    cdef int orig_dir_fd

    # Avoid chdir('') because it causes problems on Sun OS, and avoid this if
    # staying in .
    if path != "" and path != '.':
        # we change into the requested directory before reading, and back at the
        # end, because that turns out to make the stat calls measurably faster than
        # passing full paths every time.
        orig_dir_fd = open(".", O_RDONLY, 0)
        if orig_dir_fd == -1:
            raise OSError(errno, strerror(errno))
        if -1 == chdir(path):
            raise OSError(errno, strerror(errno))
    else:
        orig_dir_fd = -1

    try:
        the_dir = opendir(".")
        if NULL == the_dir:
            raise OSError(errno, strerror(errno))
        try:
            result = []
            entry = &sentinel
            while entry != NULL:
                # Unlike most libc functions, readdir needs errno set to 0
                # beforehand so that eof can be distinguished from errors.  See
                # <https://bugs.launchpad.net/bzr/+bug/279381>
                while True:
                    errno = 0
                    entry = readdir(the_dir)
                    if entry == NULL and (errno == EAGAIN or errno == EINTR):
                        # try again
                        continue
                    else:
                        break
                if entry == NULL:
                    if errno == ENOTDIR or errno == 0:
                        # We see ENOTDIR at the end of a normal directory.
                        # As ENOTDIR for read_dir(file) is triggered on opendir,
                        # we consider ENOTDIR to be 'no error'.
                        continue
                    else:
                        raise OSError(errno, strerror(errno))
                name = entry.d_name
                if not (name[0] == c"." and (
                    (name[1] == 0) or 
                    (name[1] == c"." and name[2] == 0))
                    ):
                    statvalue = _Stat()
                    stat_result = lstat(entry.d_name, &statvalue._st)
                    if stat_result != 0:
                        if errno != ENOENT:
                            raise OSError(errno, strerror(errno))
                        else:
                            kind = _missing
                            statvalue = None
                    # We append a 5-tuple that can be modified in-place by the C
                    # api:
                    # inode to sort on (to replace with top_path)
                    # name (to keep)
                    # kind (None, to set)
                    # statvalue (to keep)
                    # abspath (None, to set)
                    PyList_Append(result, (entry.d_ino, entry.d_name, None,
                        statvalue, None))
        finally:
            if -1 == closedir(the_dir):
                raise OSError(errno, strerror(errno))
    finally:
        if -1 != orig_dir_fd:
            failed = False
            if -1 == fchdir(orig_dir_fd):
                # try to close the original directory anyhow
                failed = True
            if -1 == close(orig_dir_fd) or failed:
                raise OSError(errno, strerror(errno))

    return result


# vim: tw=79 ai expandtab sw=4 sts=4
