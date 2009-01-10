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

# XXX: Some consideration of the problems that might occur if there are
# files whose id differs only in case.  That should probably be forbidden.


import errno
import os
from cStringIO import StringIO
from warnings import warn

from bzrlib import (
    errors,
    osutils,
    )
from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.weave import WeaveFile, Weave
from bzrlib.store import TransportStore
from bzrlib.atomicfile import AtomicFile
from bzrlib.symbol_versioning import (deprecated_method,
        )
from bzrlib.trace import mutter
import bzrlib.ui


class VersionedFileStore(TransportStore):
    """Collection of many versioned files in a transport."""

    # TODO: Rather than passing versionedfile_kwargs, perhaps pass in a
    # transport factory callable?
    def __init__(self, transport, prefixed=False, precious=False,
                 dir_mode=None, file_mode=None,
                 versionedfile_class=WeaveFile,
                 versionedfile_kwargs={},
                 escaped=False):
        super(VersionedFileStore, self).__init__(transport,
                dir_mode=dir_mode, file_mode=file_mode,
                prefixed=prefixed, compressed=False, escaped=escaped)
        self._precious = precious
        self._versionedfile_class = versionedfile_class
        self._versionedfile_kwargs = versionedfile_kwargs
        # Used for passing get_scope to versioned file constructors;
        self.get_scope = None

    def filename(self, file_id):
        """Return the path relative to the transport root."""
        return self._relpath(file_id)

    def __iter__(self):
        suffixes = self._versionedfile_class.get_suffixes()
        ids = set()
        for relpath in self._iter_files_recursive():
            for suffix in suffixes:
                if relpath.endswith(suffix):
                    # TODO: use standard remove_suffix function
                    escaped_id = os.path.basename(relpath[:-len(suffix)])
                    file_id = self._mapper.unmap(escaped_id)[0]
                    if file_id not in ids:
                        ids.add(file_id)
                        yield file_id
                    break # only one suffix can match

    def has_id(self, file_id):
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(file_id)
        for suffix in suffixes:
            if not self._transport.has(filename + suffix):
                return False
        return True

    def get_empty(self, file_id, transaction):
        """Get an empty weave, which implies deleting the existing one first."""
        if self.has_id(file_id):
            self.delete(file_id, transaction)
        return self.get_weave_or_empty(file_id, transaction)

    def delete(self, file_id, transaction):
        """Remove file_id from the store."""
        suffixes = self._versionedfile_class.get_suffixes()
        filename = self.filename(file_id)
        for suffix in suffixes:
            self._transport.delete(filename + suffix)

    def _get(self, file_id):
        return self._transport.get(self.filename(file_id))

    def _put(self, file_id, f):
        fn = self.filename(file_id)
        try:
            return self._transport.put_file(fn, f, mode=self._file_mode)
        except errors.NoSuchFile:
            if not self._prefixed:
                raise
            self._transport.mkdir(os.path.dirname(fn), mode=self._dir_mode)
            return self._transport.put_file(fn, f, mode=self._file_mode)

    def get_weave(self, file_id, transaction, _filename=None):
        """Return the VersionedFile for file_id.

        :param _filename: filename that would be returned from self.filename for
        file_id. This is used to reduce duplicate filename calculations when
        using 'get_weave_or_empty'. FOR INTERNAL USE ONLY.
        """
        if _filename is None:
            _filename = self.filename(file_id)
        if transaction.writeable():
            w = self._versionedfile_class(_filename, self._transport, self._file_mode,
                get_scope=self.get_scope, **self._versionedfile_kwargs)
        else:
            w = self._versionedfile_class(_filename,
                                          self._transport,
                                          self._file_mode,
                                          create=False,
                                          access_mode='r',
                                          get_scope=self.get_scope,
                                          **self._versionedfile_kwargs)
        return w

    def _make_new_versionedfile(self, file_id, transaction,
        known_missing=False, _filename=None):
        """Make a new versioned file.
        
        :param _filename: filename that would be returned from self.filename for
        file_id. This is used to reduce duplicate filename calculations when
        using 'get_weave_or_empty'. FOR INTERNAL USE ONLY.
        """
        if not known_missing and self.has_id(file_id):
            self.delete(file_id, transaction)
        if _filename is None:
            _filename = self.filename(file_id)
        try:
            # we try without making the directory first because thats optimising
            # for the common case.
            weave = self._versionedfile_class(_filename, self._transport, self._file_mode, create=True,
                get_scope=self.get_scope, **self._versionedfile_kwargs)
        except errors.NoSuchFile:
            if not self._prefixed:
                # unexpected error - NoSuchFile is expected to be raised on a
                # missing dir only and that only occurs when we are prefixed.
                raise
            dirname = osutils.dirname(_filename)
            self._transport.mkdir(dirname, mode=self._dir_mode)
            weave = self._versionedfile_class(_filename, self._transport,
                                              self._file_mode, create=True,
                                              get_scope=self.get_scope,
                                              **self._versionedfile_kwargs)
        return weave

    def get_weave_or_empty(self, file_id, transaction):
        """Return a weave, or an empty one if it doesn't exist."""
        # This is typically used from 'commit' and 'fetch/push/pull' where 
        # we scan across many versioned files once. As such the small overhead
        # of calculating the filename before doing a cache lookup is more than
        # compensated for by not calculating the filename when making new
        # versioned files.
        _filename = self.filename(file_id)
        try:
            return self.get_weave(file_id, transaction, _filename=_filename)
        except errors.NoSuchFile:
            weave = self._make_new_versionedfile(file_id, transaction,
                known_missing=True, _filename=_filename)
            return weave

    def _put_weave(self, file_id, weave, transaction):
        """Preserved here for upgrades-to-weaves to use."""
        myweave = self._make_new_versionedfile(file_id, transaction)
        myweave.insert_record_stream(weave.get_record_stream(
            [(version,) for version in weave.versions()],
            'topological', False))

    def copy_all_ids(self, store_from, pb=None, from_transaction=None,
                     to_transaction=None):
        """Copy all the file ids from store_from into self."""
        if from_transaction is None:
            warn("Please pass from_transaction into "
                 "versioned_store.copy_all_ids.", stacklevel=2)
        if to_transaction is None:
            warn("Please pass to_transaction into "
                 "versioned_store.copy_all_ids.", stacklevel=2)
        if not store_from.listable():
            raise errors.UnlistableStore(store_from)
        ids = []
        for count, file_id in enumerate(store_from):
            if pb:
                pb.update('listing files', count, count)
            ids.append(file_id)
        if pb:
            pb.clear()
        mutter('copy_all ids: %r', ids)
        self.copy_multi(store_from, ids, pb=pb,
                        from_transaction=from_transaction,
                        to_transaction=to_transaction)

    def copy_multi(self, from_store, file_ids, pb=None, from_transaction=None,
                   to_transaction=None):
        """Copy all the versions for multiple file_ids from from_store.
        
        :param from_transaction: required current transaction in from_store.
        """
        from bzrlib.transactions import PassThroughTransaction
        if from_transaction is None:
            warn("WeaveStore.copy_multi without a from_transaction parameter "
                 "is deprecated. Please provide a from_transaction.",
                 DeprecationWarning,
                 stacklevel=2)
            # we are reading one object - caching is irrelevant.
            from_transaction = PassThroughTransaction()
        if to_transaction is None:
            warn("WeaveStore.copy_multi without a to_transaction parameter "
                 "is deprecated. Please provide a to_transaction.",
                 DeprecationWarning,
                 stacklevel=2)
            # we are copying single objects, and there may be open tranasactions
            # so again with the passthrough
            to_transaction = PassThroughTransaction()
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            for count, f in enumerate(file_ids):
                mutter("copy weave {%s} into %s", f, self)
                pb.update('copy', count, len(file_ids))
                # if we have it in cache, its faster.
                # joining is fast with knits, and bearable for weaves -
                # indeed the new case can be optimised if needed.
                target = self._make_new_versionedfile(f, to_transaction)
                source = from_store.get_weave(f, from_transaction)
                target.insert_record_stream(source.get_record_stream(
                    [(version,) for version in source.versions()],
                    'topological', False))
        finally:
            pb.finished()

    def total_size(self):
        count, bytes =  super(VersionedFileStore, self).total_size()
        return (count / len(self._versionedfile_class.get_suffixes())), bytes

WeaveStore = VersionedFileStore
