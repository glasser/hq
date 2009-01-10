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

"""DirState objects record the state of a directory and its bzr metadata.

Pseudo EBNF grammar for the state file. Fields are separated by NULLs, and
lines by NL. The field delimiters are ommitted in the grammar, line delimiters
are not - this is done for clarity of reading. All string data is in utf8.

MINIKIND = "f" | "d" | "l" | "a" | "r" | "t";
NL = "\n";
NULL = "\0";
WHOLE_NUMBER = {digit}, digit;
BOOLEAN = "y" | "n";
REVISION_ID = a non-empty utf8 string;

dirstate format = header line, full checksum, row count, parent details,
 ghost_details, entries;
header line = "#bazaar dirstate flat format 3", NL;
full checksum = "crc32: ", ["-"], WHOLE_NUMBER, NL;
row count = "num_entries: ", WHOLE_NUMBER, NL;
parent_details = WHOLE NUMBER, {REVISION_ID}* NL;
ghost_details = WHOLE NUMBER, {REVISION_ID}*, NL;
entries = {entry};
entry = entry_key, current_entry_details, {parent_entry_details};
entry_key = dirname,  basename, fileid;
current_entry_details = common_entry_details, working_entry_details;
parent_entry_details = common_entry_details, history_entry_details;
common_entry_details = MINIKIND, fingerprint, size, executable
working_entry_details = packed_stat
history_entry_details = REVISION_ID;
executable = BOOLEAN;
size = WHOLE_NUMBER;
fingerprint = a nonempty utf8 sequence with meaning defined by minikind.

Given this definition, the following is useful to know:
entry (aka row) - all the data for a given key.
entry[0]: The key (dirname, basename, fileid)
entry[0][0]: dirname
entry[0][1]: basename
entry[0][2]: fileid
entry[1]: The tree(s) data for this path and id combination.
entry[1][0]: The current tree
entry[1][1]: The second tree

For an entry for a tree, we have (using tree 0 - current tree) to demonstrate:
entry[1][0][0]: minikind
entry[1][0][1]: fingerprint
entry[1][0][2]: size
entry[1][0][3]: executable
entry[1][0][4]: packed_stat
OR (for non tree-0)
entry[1][1][4]: revision_id

There may be multiple rows at the root, one per id present in the root, so the
in memory root row is now:
self._dirblocks[0] -> ('', [entry ...]),
and the entries in there are
entries[0][0]: ''
entries[0][1]: ''
entries[0][2]: file_id
entries[1][0]: The tree data for the current tree for this fileid at /
etc.

Kinds:
'r' is a relocated entry: This path is not present in this tree with this id,
    but the id can be found at another location. The fingerprint is used to
    point to the target location.
'a' is an absent entry: In that tree the id is not present at this path.
'd' is a directory entry: This path in this tree is a directory with the
    current file id. There is no fingerprint for directories.
'f' is a file entry: As for directory, but its a file. The fingerprint is a
    sha1 value.
'l' is a symlink entry: As for directory, but a symlink. The fingerprint is the
    link target.
't' is a reference to a nested subtree; the fingerprint is the referenced
    revision.

Ordering:

The entries on disk and in memory are ordered according to the following keys:

    directory, as a list of components
    filename
    file-id

--- Format 1 had the following different definition: ---
rows = dirname, NULL, basename, NULL, MINIKIND, NULL, fileid_utf8, NULL,
    WHOLE NUMBER (* size *), NULL, packed stat, NULL, sha1|symlink target, 
    {PARENT ROW}
PARENT ROW = NULL, revision_utf8, NULL, MINIKIND, NULL, dirname, NULL,
    basename, NULL, WHOLE NUMBER (* size *), NULL, "y" | "n", NULL,
    SHA1

PARENT ROW's are emitted for every parent that is not in the ghosts details
line. That is, if the parents are foo, bar, baz, and the ghosts are bar, then
each row will have a PARENT ROW for foo and baz, but not for bar.


In any tree, a kind of 'moved' indicates that the fingerprint field
(which we treat as opaque data specific to the 'kind' anyway) has the
details for the id of this row in that tree.

I'm strongly tempted to add a id->path index as well, but I think that
where we need id->path mapping; we also usually read the whole file, so
I'm going to skip that for the moment, as we have the ability to locate
via bisect any path in any tree, and if we lookup things by path, we can
accumulate an id->path mapping as we go, which will tend to match what we
looked for.

I plan to implement this asap, so please speak up now to alter/tweak the
design - and once we stabilise on this, I'll update the wiki page for
it.

The rationale for all this is that we want fast operations for the
common case (diff/status/commit/merge on all files) and extremely fast
operations for the less common but still occurs a lot status/diff/commit
on specific files). Operations on specific files involve a scan for all
the children of a path, *in every involved tree*, which the current
format did not accommodate. 
----

Design priorities:
 1) Fast end to end use for bzr's top 5 uses cases. (commmit/diff/status/merge/???)
 2) fall back current object model as needed.
 3) scale usably to the largest trees known today - say 50K entries. (mozilla
    is an example of this)


Locking:
 Eventually reuse dirstate objects across locks IFF the dirstate file has not
 been modified, but will require that we flush/ignore cached stat-hit data
 because we won't want to restat all files on disk just because a lock was
 acquired, yet we cannot trust the data after the previous lock was released.

Memory representation:
 vector of all directories, and vector of the childen ?
   i.e. 
     root_entrie = (direntry for root, [parent_direntries_for_root]), 
     dirblocks = [
     ('', ['data for achild', 'data for bchild', 'data for cchild'])
     ('dir', ['achild', 'cchild', 'echild'])
     ]
    - single bisect to find N subtrees from a path spec
    - in-order for serialisation - this is 'dirblock' grouping.
    - insertion of a file '/a' affects only the '/' child-vector, that is, to
      insert 10K elements from scratch does not generates O(N^2) memoves of a
      single vector, rather each individual, which tends to be limited to a 
      manageable number. Will scale badly on trees with 10K entries in a 
      single directory. compare with Inventory.InventoryDirectory which has
      a dictionary for the children. No bisect capability, can only probe for
      exact matches, or grab all elements and sort.
    - What's the risk of error here? Once we have the base format being processed
      we should have a net win regardless of optimality. So we are going to 
      go with what seems reasonable.
open questions:

Maybe we should do a test profile of the core structure - 10K simulated
searches/lookups/etc?

Objects for each row?
The lifetime of Dirstate objects is current per lock, but see above for
possible extensions. The lifetime of a row from a dirstate is expected to be
very short in the optimistic case: which we are optimising for. For instance,
subtree status will determine from analysis of the disk data what rows need to
be examined at all, and will be able to determine from a single row whether
that file has altered or not, so we are aiming to process tens of thousands of
entries each second within the dirstate context, before exposing anything to
the larger codebase. This suggests we want the time for a single file
comparison to be < 0.1 milliseconds. That would give us 10000 paths per second
processed, and to scale to 100 thousand we'll another order of magnitude to do
that. Now, as the lifetime for all unchanged entries is the time to parse, stat
the file on disk, and then immediately discard, the overhead of object creation
becomes a significant cost.

Figures: Creating a tuple from from 3 elements was profiled at 0.0625
microseconds, whereas creating a object which is subclassed from tuple was
0.500 microseconds, and creating an object with 3 elements and slots was 3
microseconds long. 0.1 milliseconds is 100 microseconds, and ideally we'll get
down to 10 microseconds for the total processing - having 33% of that be object
creation is a huge overhead. There is a potential cost in using tuples within
each row which is that the conditional code to do comparisons may be slower
than method invocation, but method invocation is known to be slow due to stack
frame creation, so avoiding methods in these tight inner loops in unfortunately
desirable. We can consider a pyrex version of this with objects in future if
desired.

"""

import bisect
import binascii
import errno
import os
from stat import S_IEXEC
import stat
import struct
import sys
import time
import zlib

from bzrlib import (
    cache_utf8,
    debug,
    errors,
    inventory,
    lock,
    osutils,
    trace,
    )


# This is the Windows equivalent of ENOTDIR
# It is defined in pywin32.winerror, but we don't want a strong dependency for
# just an error code.
ERROR_PATH_NOT_FOUND = 3
ERROR_DIRECTORY = 267


if not getattr(struct, '_compile', None):
    # Cannot pre-compile the dirstate pack_stat
    def pack_stat(st, _encode=binascii.b2a_base64, _pack=struct.pack):
        """Convert stat values into a packed representation."""
        return _encode(_pack('>LLLLLL', st.st_size, int(st.st_mtime),
            int(st.st_ctime), st.st_dev, st.st_ino & 0xFFFFFFFF,
            st.st_mode))[:-1]
else:
    # compile the struct compiler we need, so as to only do it once
    from _struct import Struct
    _compiled_pack = Struct('>LLLLLL').pack
    def pack_stat(st, _encode=binascii.b2a_base64, _pack=_compiled_pack):
        """Convert stat values into a packed representation."""
        # jam 20060614 it isn't really worth removing more entries if we
        # are going to leave it in packed form.
        # With only st_mtime and st_mode filesize is 5.5M and read time is 275ms
        # With all entries, filesize is 5.9M and read time is maybe 280ms
        # well within the noise margin

        # base64 encoding always adds a final newline, so strip it off
        # The current version
        return _encode(_pack(st.st_size, int(st.st_mtime), int(st.st_ctime),
            st.st_dev, st.st_ino & 0xFFFFFFFF, st.st_mode))[:-1]
        # This is 0.060s / 1.520s faster by not encoding as much information
        # return _encode(_pack('>LL', int(st.st_mtime), st.st_mode))[:-1]
        # This is not strictly faster than _encode(_pack())[:-1]
        # return '%X.%X.%X.%X.%X.%X' % (
        #      st.st_size, int(st.st_mtime), int(st.st_ctime),
        #      st.st_dev, st.st_ino, st.st_mode)
        # Similar to the _encode(_pack('>LL'))
        # return '%X.%X' % (int(st.st_mtime), st.st_mode)


class DirState(object):
    """Record directory and metadata state for fast access.

    A dirstate is a specialised data structure for managing local working
    tree state information. Its not yet well defined whether it is platform
    specific, and if it is how we detect/parameterize that.

    Dirstates use the usual lock_write, lock_read and unlock mechanisms.
    Unlike most bzr disk formats, DirStates must be locked for reading, using
    lock_read.  (This is an os file lock internally.)  This is necessary
    because the file can be rewritten in place.

    DirStates must be explicitly written with save() to commit changes; just
    unlocking them does not write the changes to disk.
    """

    _kind_to_minikind = {
            'absent': 'a',
            'file': 'f',
            'directory': 'd',
            'relocated': 'r',
            'symlink': 'l',
            'tree-reference': 't',
        }
    _minikind_to_kind = {
            'a': 'absent',
            'f': 'file',
            'd': 'directory',
            'l':'symlink',
            'r': 'relocated',
            't': 'tree-reference',
        }
    _stat_to_minikind = {
        stat.S_IFDIR:'d',
        stat.S_IFREG:'f',
        stat.S_IFLNK:'l',
    }
    _to_yesno = {True:'y', False: 'n'} # TODO profile the performance gain
     # of using int conversion rather than a dict here. AND BLAME ANDREW IF
     # it is faster.

    # TODO: jam 20070221 Figure out what to do if we have a record that exceeds
    #       the BISECT_PAGE_SIZE. For now, we just have to make it large enough
    #       that we are sure a single record will always fit.
    BISECT_PAGE_SIZE = 4096

    NOT_IN_MEMORY = 0
    IN_MEMORY_UNMODIFIED = 1
    IN_MEMORY_MODIFIED = 2

    # A pack_stat (the x's) that is just noise and will never match the output
    # of base64 encode.
    NULLSTAT = 'x' * 32
    NULL_PARENT_DETAILS = ('a', '', 0, False, '')

    HEADER_FORMAT_2 = '#bazaar dirstate flat format 2\n'
    HEADER_FORMAT_3 = '#bazaar dirstate flat format 3\n'

    def __init__(self, path):
        """Create a  DirState object.

        :param path: The path at which the dirstate file on disk should live.
        """
        # _header_state and _dirblock_state represent the current state
        # of the dirstate metadata and the per-row data respectiely.
        # NOT_IN_MEMORY indicates that no data is in memory
        # IN_MEMORY_UNMODIFIED indicates that what we have in memory
        #   is the same as is on disk
        # IN_MEMORY_MODIFIED indicates that we have a modified version
        #   of what is on disk. 
        # In future we will add more granularity, for instance _dirblock_state
        # will probably support partially-in-memory as a separate variable,
        # allowing for partially-in-memory unmodified and partially-in-memory
        # modified states.
        self._header_state = DirState.NOT_IN_MEMORY
        self._dirblock_state = DirState.NOT_IN_MEMORY
        # If true, an error has been detected while updating the dirstate, and 
        # for safety we're not going to commit to disk.
        self._changes_aborted = False
        self._dirblocks = []
        self._ghosts = []
        self._parents = []
        self._state_file = None
        self._filename = path
        self._lock_token = None
        self._lock_state = None
        self._id_index = None
        # a map from packed_stat to sha's.
        self._packed_stat_index = None
        self._end_of_header = None
        self._cutoff_time = None
        self._split_path_cache = {}
        self._bisect_page_size = DirState.BISECT_PAGE_SIZE
        if 'hashcache' in debug.debug_flags:
            self._sha1_file = self._sha1_file_and_mutter
        else:
            self._sha1_file = osutils.sha_file_by_name
        # These two attributes provide a simple cache for lookups into the
        # dirstate in-memory vectors. By probing respectively for the last
        # block, and for the next entry, we save nearly 2 bisections per path
        # during commit.
        self._last_block_index = None
        self._last_entry_index = None

    def __repr__(self):
        return "%s(%r)" % \
            (self.__class__.__name__, self._filename)

    def add(self, path, file_id, kind, stat, fingerprint):
        """Add a path to be tracked.

        :param path: The path within the dirstate - '' is the root, 'foo' is the
            path foo within the root, 'foo/bar' is the path bar within foo 
            within the root.
        :param file_id: The file id of the path being added.
        :param kind: The kind of the path, as a string like 'file', 
            'directory', etc.
        :param stat: The output of os.lstat for the path.
        :param fingerprint: The sha value of the file,
            or the target of a symlink,
            or the referenced revision id for tree-references,
            or '' for directories.
        """
        # adding a file:
        # find the block its in. 
        # find the location in the block.
        # check its not there
        # add it.
        #------- copied from inventory.ensure_normalized_name - keep synced.
        # --- normalized_filename wants a unicode basename only, so get one.
        dirname, basename = osutils.split(path)
        # we dont import normalized_filename directly because we want to be
        # able to change the implementation at runtime for tests.
        norm_name, can_access = osutils.normalized_filename(basename)
        if norm_name != basename:
            if can_access:
                basename = norm_name
            else:
                raise errors.InvalidNormalization(path)
        # you should never have files called . or ..; just add the directory
        # in the parent, or according to the special treatment for the root
        if basename == '.' or basename == '..':
            raise errors.InvalidEntryName(path)
        # now that we've normalised, we need the correct utf8 path and 
        # dirname and basename elements. This single encode and split should be
        # faster than three separate encodes.
        utf8path = (dirname + '/' + basename).strip('/').encode('utf8')
        dirname, basename = osutils.split(utf8path)
        # uses __class__ for speed; the check is needed for safety
        if file_id.__class__ is not str:
            raise AssertionError(
                "must be a utf8 file_id not %s" % (type(file_id), ))
        # Make sure the file_id does not exist in this tree
        file_id_entry = self._get_entry(0, fileid_utf8=file_id)
        if file_id_entry != (None, None):
            path = osutils.pathjoin(file_id_entry[0][0], file_id_entry[0][1])
            kind = DirState._minikind_to_kind[file_id_entry[1][0][0]]
            info = '%s:%s' % (kind, path)
            raise errors.DuplicateFileId(file_id, info)
        first_key = (dirname, basename, '')
        block_index, present = self._find_block_index_from_key(first_key)
        if present:
            # check the path is not in the tree
            block = self._dirblocks[block_index][1]
            entry_index, _ = self._find_entry_index(first_key, block)
            while (entry_index < len(block) and 
                block[entry_index][0][0:2] == first_key[0:2]):
                if block[entry_index][1][0][0] not in 'ar':
                    # this path is in the dirstate in the current tree.
                    raise Exception, "adding already added path!"
                entry_index += 1
        else:
            # The block where we want to put the file is not present. But it
            # might be because the directory was empty, or not loaded yet. Look
            # for a parent entry, if not found, raise NotVersionedError
            parent_dir, parent_base = osutils.split(dirname)
            parent_block_idx, parent_entry_idx, _, parent_present = \
                self._get_block_entry_index(parent_dir, parent_base, 0)
            if not parent_present:
                raise errors.NotVersionedError(path, str(self))
            self._ensure_block(parent_block_idx, parent_entry_idx, dirname)
        block = self._dirblocks[block_index][1]
        entry_key = (dirname, basename, file_id)
        if stat is None:
            size = 0
            packed_stat = DirState.NULLSTAT
        else:
            size = stat.st_size
            packed_stat = pack_stat(stat)
        parent_info = self._empty_parent_info()
        minikind = DirState._kind_to_minikind[kind]
        if kind == 'file':
            entry_data = entry_key, [
                (minikind, fingerprint, size, False, packed_stat),
                ] + parent_info
        elif kind == 'directory':
            entry_data = entry_key, [
                (minikind, '', 0, False, packed_stat),
                ] + parent_info
        elif kind == 'symlink':
            entry_data = entry_key, [
                (minikind, fingerprint, size, False, packed_stat),
                ] + parent_info
        elif kind == 'tree-reference':
            entry_data = entry_key, [
                (minikind, fingerprint, 0, False, packed_stat),
                ] + parent_info
        else:
            raise errors.BzrError('unknown kind %r' % kind)
        entry_index, present = self._find_entry_index(entry_key, block)
        if not present:
            block.insert(entry_index, entry_data)
        else:
            if block[entry_index][1][0][0] != 'a':
                raise AssertionError(" %r(%r) already added" % (basename, file_id))
            block[entry_index][1][0] = entry_data[1][0]

        if kind == 'directory':
           # insert a new dirblock
           self._ensure_block(block_index, entry_index, utf8path)
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        if self._id_index:
            self._id_index.setdefault(entry_key[2], set()).add(entry_key)

    def _bisect(self, paths):
        """Bisect through the disk structure for specific rows.

        :param paths: A list of paths to find
        :return: A dict mapping path => entries for found entries. Missing
                 entries will not be in the map.
                 The list is not sorted, and entries will be populated
                 based on when they were read.
        """
        self._requires_lock()
        # We need the file pointer to be right after the initial header block
        self._read_header_if_needed()
        # If _dirblock_state was in memory, we should just return info from
        # there, this function is only meant to handle when we want to read
        # part of the disk.
        if self._dirblock_state != DirState.NOT_IN_MEMORY:
            raise AssertionError("bad dirblock state %r" % self._dirblock_state)

        # The disk representation is generally info + '\0\n\0' at the end. But
        # for bisecting, it is easier to treat this as '\0' + info + '\0\n'
        # Because it means we can sync on the '\n'
        state_file = self._state_file
        file_size = os.fstat(state_file.fileno()).st_size
        # We end up with 2 extra fields, we should have a trailing '\n' to
        # ensure that we read the whole record, and we should have a precursur
        # '' which ensures that we start after the previous '\n'
        entry_field_count = self._fields_per_entry() + 1

        low = self._end_of_header
        high = file_size - 1 # Ignore the final '\0'
        # Map from (dir, name) => entry
        found = {}

        # Avoid infinite seeking
        max_count = 30*len(paths)
        count = 0
        # pending is a list of places to look.
        # each entry is a tuple of low, high, dir_names
        #   low -> the first byte offset to read (inclusive)
        #   high -> the last byte offset (inclusive)
        #   dir_names -> The list of (dir, name) pairs that should be found in
        #                the [low, high] range
        pending = [(low, high, paths)]

        page_size = self._bisect_page_size

        fields_to_entry = self._get_fields_to_entry()

        while pending:
            low, high, cur_files = pending.pop()

            if not cur_files or low >= high:
                # Nothing to find
                continue

            count += 1
            if count > max_count:
                raise errors.BzrError('Too many seeks, most likely a bug.')

            mid = max(low, (low+high-page_size)/2)

            state_file.seek(mid)
            # limit the read size, so we don't end up reading data that we have
            # already read.
            read_size = min(page_size, (high-mid)+1)
            block = state_file.read(read_size)

            start = mid
            entries = block.split('\n')

            if len(entries) < 2:
                # We didn't find a '\n', so we cannot have found any records.
                # So put this range back and try again. But we know we have to
                # increase the page size, because a single read did not contain
                # a record break (so records must be larger than page_size)
                page_size *= 2
                pending.append((low, high, cur_files))
                continue

            # Check the first and last entries, in case they are partial, or if
            # we don't care about the rest of this page
            first_entry_num = 0
            first_fields = entries[0].split('\0')
            if len(first_fields) < entry_field_count:
                # We didn't get the complete first entry
                # so move start, and grab the next, which
                # should be a full entry
                start += len(entries[0])+1
                first_fields = entries[1].split('\0')
                first_entry_num = 1

            if len(first_fields) <= 2:
                # We didn't even get a filename here... what do we do?
                # Try a large page size and repeat this query
                page_size *= 2
                pending.append((low, high, cur_files))
                continue
            else:
                # Find what entries we are looking for, which occur before and
                # after this first record.
                after = start
                if first_fields[1]:
                    first_path = first_fields[1] + '/' + first_fields[2]
                else:
                    first_path = first_fields[2]
                first_loc = _bisect_path_left(cur_files, first_path)

                # These exist before the current location
                pre = cur_files[:first_loc]
                # These occur after the current location, which may be in the
                # data we read, or might be after the last entry
                post = cur_files[first_loc:]

            if post and len(first_fields) >= entry_field_count:
                # We have files after the first entry

                # Parse the last entry
                last_entry_num = len(entries)-1
                last_fields = entries[last_entry_num].split('\0')
                if len(last_fields) < entry_field_count:
                    # The very last hunk was not complete,
                    # read the previous hunk
                    after = mid + len(block) - len(entries[-1])
                    last_entry_num -= 1
                    last_fields = entries[last_entry_num].split('\0')
                else:
                    after = mid + len(block)

                if last_fields[1]:
                    last_path = last_fields[1] + '/' + last_fields[2]
                else:
                    last_path = last_fields[2]
                last_loc = _bisect_path_right(post, last_path)

                middle_files = post[:last_loc]
                post = post[last_loc:]

                if middle_files:
                    # We have files that should occur in this block
                    # (>= first, <= last)
                    # Either we will find them here, or we can mark them as
                    # missing.

                    if middle_files[0] == first_path:
                        # We might need to go before this location
                        pre.append(first_path)
                    if middle_files[-1] == last_path:
                        post.insert(0, last_path)

                    # Find out what paths we have
                    paths = {first_path:[first_fields]}
                    # last_path might == first_path so we need to be
                    # careful if we should append rather than overwrite
                    if last_entry_num != first_entry_num:
                        paths.setdefault(last_path, []).append(last_fields)
                    for num in xrange(first_entry_num+1, last_entry_num):
                        # TODO: jam 20070223 We are already splitting here, so
                        #       shouldn't we just split the whole thing rather
                        #       than doing the split again in add_one_record?
                        fields = entries[num].split('\0')
                        if fields[1]:
                            path = fields[1] + '/' + fields[2]
                        else:
                            path = fields[2]
                        paths.setdefault(path, []).append(fields)

                    for path in middle_files:
                        for fields in paths.get(path, []):
                            # offset by 1 because of the opening '\0'
                            # consider changing fields_to_entry to avoid the
                            # extra list slice
                            entry = fields_to_entry(fields[1:])
                            found.setdefault(path, []).append(entry)

            # Now we have split up everything into pre, middle, and post, and
            # we have handled everything that fell in 'middle'.
            # We add 'post' first, so that we prefer to seek towards the
            # beginning, so that we will tend to go as early as we need, and
            # then only seek forward after that.
            if post:
                pending.append((after, high, post))
            if pre:
                pending.append((low, start-1, pre))

        # Consider that we may want to return the directory entries in sorted
        # order. For now, we just return them in whatever order we found them,
        # and leave it up to the caller if they care if it is ordered or not.
        return found

    def _bisect_dirblocks(self, dir_list):
        """Bisect through the disk structure to find entries in given dirs.

        _bisect_dirblocks is meant to find the contents of directories, which
        differs from _bisect, which only finds individual entries.

        :param dir_list: A sorted list of directory names ['', 'dir', 'foo'].
        :return: A map from dir => entries_for_dir
        """
        # TODO: jam 20070223 A lot of the bisecting logic could be shared
        #       between this and _bisect. It would require parameterizing the
        #       inner loop with a function, though. We should evaluate the
        #       performance difference.
        self._requires_lock()
        # We need the file pointer to be right after the initial header block
        self._read_header_if_needed()
        # If _dirblock_state was in memory, we should just return info from
        # there, this function is only meant to handle when we want to read
        # part of the disk.
        if self._dirblock_state != DirState.NOT_IN_MEMORY:
            raise AssertionError("bad dirblock state %r" % self._dirblock_state)
        # The disk representation is generally info + '\0\n\0' at the end. But
        # for bisecting, it is easier to treat this as '\0' + info + '\0\n'
        # Because it means we can sync on the '\n'
        state_file = self._state_file
        file_size = os.fstat(state_file.fileno()).st_size
        # We end up with 2 extra fields, we should have a trailing '\n' to
        # ensure that we read the whole record, and we should have a precursur
        # '' which ensures that we start after the previous '\n'
        entry_field_count = self._fields_per_entry() + 1

        low = self._end_of_header
        high = file_size - 1 # Ignore the final '\0'
        # Map from dir => entry
        found = {}

        # Avoid infinite seeking
        max_count = 30*len(dir_list)
        count = 0
        # pending is a list of places to look.
        # each entry is a tuple of low, high, dir_names
        #   low -> the first byte offset to read (inclusive)
        #   high -> the last byte offset (inclusive)
        #   dirs -> The list of directories that should be found in
        #                the [low, high] range
        pending = [(low, high, dir_list)]

        page_size = self._bisect_page_size

        fields_to_entry = self._get_fields_to_entry()

        while pending:
            low, high, cur_dirs = pending.pop()

            if not cur_dirs or low >= high:
                # Nothing to find
                continue

            count += 1
            if count > max_count:
                raise errors.BzrError('Too many seeks, most likely a bug.')

            mid = max(low, (low+high-page_size)/2)

            state_file.seek(mid)
            # limit the read size, so we don't end up reading data that we have
            # already read.
            read_size = min(page_size, (high-mid)+1)
            block = state_file.read(read_size)

            start = mid
            entries = block.split('\n')

            if len(entries) < 2:
                # We didn't find a '\n', so we cannot have found any records.
                # So put this range back and try again. But we know we have to
                # increase the page size, because a single read did not contain
                # a record break (so records must be larger than page_size)
                page_size *= 2
                pending.append((low, high, cur_dirs))
                continue

            # Check the first and last entries, in case they are partial, or if
            # we don't care about the rest of this page
            first_entry_num = 0
            first_fields = entries[0].split('\0')
            if len(first_fields) < entry_field_count:
                # We didn't get the complete first entry
                # so move start, and grab the next, which
                # should be a full entry
                start += len(entries[0])+1
                first_fields = entries[1].split('\0')
                first_entry_num = 1

            if len(first_fields) <= 1:
                # We didn't even get a dirname here... what do we do?
                # Try a large page size and repeat this query
                page_size *= 2
                pending.append((low, high, cur_dirs))
                continue
            else:
                # Find what entries we are looking for, which occur before and
                # after this first record.
                after = start
                first_dir = first_fields[1]
                first_loc = bisect.bisect_left(cur_dirs, first_dir)

                # These exist before the current location
                pre = cur_dirs[:first_loc]
                # These occur after the current location, which may be in the
                # data we read, or might be after the last entry
                post = cur_dirs[first_loc:]

            if post and len(first_fields) >= entry_field_count:
                # We have records to look at after the first entry

                # Parse the last entry
                last_entry_num = len(entries)-1
                last_fields = entries[last_entry_num].split('\0')
                if len(last_fields) < entry_field_count:
                    # The very last hunk was not complete,
                    # read the previous hunk
                    after = mid + len(block) - len(entries[-1])
                    last_entry_num -= 1
                    last_fields = entries[last_entry_num].split('\0')
                else:
                    after = mid + len(block)

                last_dir = last_fields[1]
                last_loc = bisect.bisect_right(post, last_dir)

                middle_files = post[:last_loc]
                post = post[last_loc:]

                if middle_files:
                    # We have files that should occur in this block
                    # (>= first, <= last)
                    # Either we will find them here, or we can mark them as
                    # missing.

                    if middle_files[0] == first_dir:
                        # We might need to go before this location
                        pre.append(first_dir)
                    if middle_files[-1] == last_dir:
                        post.insert(0, last_dir)

                    # Find out what paths we have
                    paths = {first_dir:[first_fields]}
                    # last_dir might == first_dir so we need to be
                    # careful if we should append rather than overwrite
                    if last_entry_num != first_entry_num:
                        paths.setdefault(last_dir, []).append(last_fields)
                    for num in xrange(first_entry_num+1, last_entry_num):
                        # TODO: jam 20070223 We are already splitting here, so
                        #       shouldn't we just split the whole thing rather
                        #       than doing the split again in add_one_record?
                        fields = entries[num].split('\0')
                        paths.setdefault(fields[1], []).append(fields)

                    for cur_dir in middle_files:
                        for fields in paths.get(cur_dir, []):
                            # offset by 1 because of the opening '\0'
                            # consider changing fields_to_entry to avoid the
                            # extra list slice
                            entry = fields_to_entry(fields[1:])
                            found.setdefault(cur_dir, []).append(entry)

            # Now we have split up everything into pre, middle, and post, and
            # we have handled everything that fell in 'middle'.
            # We add 'post' first, so that we prefer to seek towards the
            # beginning, so that we will tend to go as early as we need, and
            # then only seek forward after that.
            if post:
                pending.append((after, high, post))
            if pre:
                pending.append((low, start-1, pre))

        return found

    def _bisect_recursive(self, paths):
        """Bisect for entries for all paths and their children.

        This will use bisect to find all records for the supplied paths. It
        will then continue to bisect for any records which are marked as
        directories. (and renames?)

        :param paths: A sorted list of (dir, name) pairs
             eg: [('', 'a'), ('', 'f'), ('a/b', 'c')]
        :return: A dictionary mapping (dir, name, file_id) => [tree_info]
        """
        # Map from (dir, name, file_id) => [tree_info]
        found = {}

        found_dir_names = set()

        # Directories that have been read
        processed_dirs = set()
        # Get the ball rolling with the first bisect for all entries.
        newly_found = self._bisect(paths)

        while newly_found:
            # Directories that need to be read
            pending_dirs = set()
            paths_to_search = set()
            for entry_list in newly_found.itervalues():
                for dir_name_id, trees_info in entry_list:
                    found[dir_name_id] = trees_info
                    found_dir_names.add(dir_name_id[:2])
                    is_dir = False
                    for tree_info in trees_info:
                        minikind = tree_info[0]
                        if minikind == 'd':
                            if is_dir:
                                # We already processed this one as a directory,
                                # we don't need to do the extra work again.
                                continue
                            subdir, name, file_id = dir_name_id
                            path = osutils.pathjoin(subdir, name)
                            is_dir = True
                            if path not in processed_dirs:
                                pending_dirs.add(path)
                        elif minikind == 'r':
                            # Rename, we need to directly search the target
                            # which is contained in the fingerprint column
                            dir_name = osutils.split(tree_info[1])
                            if dir_name[0] in pending_dirs:
                                # This entry will be found in the dir search
                                continue
                            if dir_name not in found_dir_names:
                                paths_to_search.add(tree_info[1])
            # Now we have a list of paths to look for directly, and
            # directory blocks that need to be read.
            # newly_found is mixing the keys between (dir, name) and path
            # entries, but that is okay, because we only really care about the
            # targets.
            newly_found = self._bisect(sorted(paths_to_search))
            newly_found.update(self._bisect_dirblocks(sorted(pending_dirs)))
            processed_dirs.update(pending_dirs)
        return found

    def _discard_merge_parents(self):
        """Discard any parents trees beyond the first.
        
        Note that if this fails the dirstate is corrupted.

        After this function returns the dirstate contains 2 trees, neither of
        which are ghosted.
        """
        self._read_header_if_needed()
        parents = self.get_parent_ids()
        if len(parents) < 1:
            return
        # only require all dirblocks if we are doing a full-pass removal.
        self._read_dirblocks_if_needed()
        dead_patterns = set([('a', 'r'), ('a', 'a'), ('r', 'r'), ('r', 'a')])
        def iter_entries_removable():
            for block in self._dirblocks:
                deleted_positions = []
                for pos, entry in enumerate(block[1]):
                    yield entry
                    if (entry[1][0][0], entry[1][1][0]) in dead_patterns:
                        deleted_positions.append(pos)
                if deleted_positions:
                    if len(deleted_positions) == len(block[1]):
                        del block[1][:]
                    else:
                        for pos in reversed(deleted_positions):
                            del block[1][pos]
        # if the first parent is a ghost:
        if parents[0] in self.get_ghosts():
            empty_parent = [DirState.NULL_PARENT_DETAILS]
            for entry in iter_entries_removable():
                entry[1][1:] = empty_parent
        else:
            for entry in iter_entries_removable():
                del entry[1][2:]

        self._ghosts = []
        self._parents = [parents[0]]
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._header_state = DirState.IN_MEMORY_MODIFIED

    def _empty_parent_info(self):
        return [DirState.NULL_PARENT_DETAILS] * (len(self._parents) -
                                                    len(self._ghosts))

    def _ensure_block(self, parent_block_index, parent_row_index, dirname):
        """Ensure a block for dirname exists.

        This function exists to let callers which know that there is a
        directory dirname ensure that the block for it exists. This block can
        fail to exist because of demand loading, or because a directory had no
        children. In either case it is not an error. It is however an error to
        call this if there is no parent entry for the directory, and thus the
        function requires the coordinates of such an entry to be provided.

        The root row is special cased and can be indicated with a parent block
        and row index of -1

        :param parent_block_index: The index of the block in which dirname's row
            exists.
        :param parent_row_index: The index in the parent block where the row
            exists.
        :param dirname: The utf8 dirname to ensure there is a block for.
        :return: The index for the block.
        """
        if dirname == '' and parent_row_index == 0 and parent_block_index == 0:
            # This is the signature of the root row, and the
            # contents-of-root row is always index 1
            return 1
        # the basename of the directory must be the end of its full name.
        if not (parent_block_index == -1 and
            parent_block_index == -1 and dirname == ''):
            if not dirname.endswith(
                    self._dirblocks[parent_block_index][1][parent_row_index][0][1]):
                raise AssertionError("bad dirname %r" % dirname)
        block_index, present = self._find_block_index_from_key((dirname, '', ''))
        if not present:
            ## In future, when doing partial parsing, this should load and 
            # populate the entire block.
            self._dirblocks.insert(block_index, (dirname, []))
        return block_index

    def _entries_to_current_state(self, new_entries):
        """Load new_entries into self.dirblocks.

        Process new_entries into the current state object, making them the active
        state.  The entries are grouped together by directory to form dirblocks.

        :param new_entries: A sorted list of entries. This function does not sort
            to prevent unneeded overhead when callers have a sorted list already.
        :return: Nothing.
        """
        if new_entries[0][0][0:2] != ('', ''):
            raise AssertionError(
                "Missing root row %r" % (new_entries[0][0],))
        # The two blocks here are deliberate: the root block and the 
        # contents-of-root block.
        self._dirblocks = [('', []), ('', [])]
        current_block = self._dirblocks[0][1]
        current_dirname = ''
        root_key = ('', '')
        append_entry = current_block.append
        for entry in new_entries:
            if entry[0][0] != current_dirname:
                # new block - different dirname
                current_block = []
                current_dirname = entry[0][0]
                self._dirblocks.append((current_dirname, current_block))
                append_entry = current_block.append
            # append the entry to the current block
            append_entry(entry)
        self._split_root_dirblock_into_contents()

    def _split_root_dirblock_into_contents(self):
        """Split the root dirblocks into root and contents-of-root.

        After parsing by path, we end up with root entries and contents-of-root
        entries in the same block. This loop splits them out again.
        """
        # The above loop leaves the "root block" entries mixed with the
        # "contents-of-root block". But we don't want an if check on
        # all entries, so instead we just fix it up here.
        if self._dirblocks[1] != ('', []):
            raise ValueError("bad dirblock start %r" % (self._dirblocks[1],))
        root_block = []
        contents_of_root_block = []
        for entry in self._dirblocks[0][1]:
            if not entry[0][1]: # This is a root entry
                root_block.append(entry)
            else:
                contents_of_root_block.append(entry)
        self._dirblocks[0] = ('', root_block)
        self._dirblocks[1] = ('', contents_of_root_block)

    def _entries_for_path(self, path):
        """Return a list with all the entries that match path for all ids."""
        dirname, basename = os.path.split(path)
        key = (dirname, basename, '')
        block_index, present = self._find_block_index_from_key(key)
        if not present:
            # the block which should contain path is absent.
            return []
        result = []
        block = self._dirblocks[block_index][1]
        entry_index, _ = self._find_entry_index(key, block)
        # we may need to look at multiple entries at this path: walk while the specific_files match.
        while (entry_index < len(block) and
            block[entry_index][0][0:2] == key[0:2]):
            result.append(block[entry_index])
            entry_index += 1
        return result

    def _entry_to_line(self, entry):
        """Serialize entry to a NULL delimited line ready for _get_output_lines.

        :param entry: An entry_tuple as defined in the module docstring.
        """
        entire_entry = list(entry[0])
        for tree_number, tree_data in enumerate(entry[1]):
            # (minikind, fingerprint, size, executable, tree_specific_string)
            entire_entry.extend(tree_data)
            # 3 for the key, 5 for the fields per tree.
            tree_offset = 3 + tree_number * 5
            # minikind
            entire_entry[tree_offset + 0] = tree_data[0]
            # size
            entire_entry[tree_offset + 2] = str(tree_data[2])
            # executable
            entire_entry[tree_offset + 3] = DirState._to_yesno[tree_data[3]]
        return '\0'.join(entire_entry)

    def _fields_per_entry(self):
        """How many null separated fields should be in each entry row.

        Each line now has an extra '\n' field which is not used
        so we just skip over it
        entry size:
            3 fields for the key
            + number of fields per tree_data (5) * tree count
            + newline
         """
        tree_count = 1 + self._num_present_parents()
        return 3 + 5 * tree_count + 1

    def _find_block(self, key, add_if_missing=False):
        """Return the block that key should be present in.

        :param key: A dirstate entry key.
        :return: The block tuple.
        """
        block_index, present = self._find_block_index_from_key(key)
        if not present:
            if not add_if_missing:
                # check to see if key is versioned itself - we might want to
                # add it anyway, because dirs with no entries dont get a
                # dirblock at parse time.
                # This is an uncommon branch to take: most dirs have children,
                # and most code works with versioned paths.
                parent_base, parent_name = osutils.split(key[0])
                if not self._get_block_entry_index(parent_base, parent_name, 0)[3]:
                    # some parent path has not been added - its an error to add
                    # this child
                    raise errors.NotVersionedError(key[0:2], str(self))
            self._dirblocks.insert(block_index, (key[0], []))
        return self._dirblocks[block_index]

    def _find_block_index_from_key(self, key):
        """Find the dirblock index for a key.

        :return: The block index, True if the block for the key is present.
        """
        if key[0:2] == ('', ''):
            return 0, True
        try:
            if (self._last_block_index is not None and
                self._dirblocks[self._last_block_index][0] == key[0]):
                return self._last_block_index, True
        except IndexError:
            pass
        block_index = bisect_dirblock(self._dirblocks, key[0], 1,
                                      cache=self._split_path_cache)
        # _right returns one-past-where-key is so we have to subtract
        # one to use it. we use _right here because there are two
        # '' blocks - the root, and the contents of root
        # we always have a minimum of 2 in self._dirblocks: root and
        # root-contents, and for '', we get 2 back, so this is 
        # simple and correct:
        present = (block_index < len(self._dirblocks) and
            self._dirblocks[block_index][0] == key[0])
        self._last_block_index = block_index
        # Reset the entry index cache to the beginning of the block.
        self._last_entry_index = -1
        return block_index, present

    def _find_entry_index(self, key, block):
        """Find the entry index for a key in a block.

        :return: The entry index, True if the entry for the key is present.
        """
        len_block = len(block)
        try:
            if self._last_entry_index is not None:
                # mini-bisect here.
                entry_index = self._last_entry_index + 1
                # A hit is when the key is after the last slot, and before or
                # equal to the next slot.
                if ((entry_index > 0 and block[entry_index - 1][0] < key) and
                    key <= block[entry_index][0]):
                    self._last_entry_index = entry_index
                    present = (block[entry_index][0] == key)
                    return entry_index, present
        except IndexError:
            pass
        entry_index = bisect.bisect_left(block, (key, []))
        present = (entry_index < len_block and
            block[entry_index][0] == key)
        self._last_entry_index = entry_index
        return entry_index, present

    @staticmethod
    def from_tree(tree, dir_state_filename):
        """Create a dirstate from a bzr Tree.

        :param tree: The tree which should provide parent information and
            inventory ids.
        :return: a DirState object which is currently locked for writing.
            (it was locked by DirState.initialize)
        """
        result = DirState.initialize(dir_state_filename)
        try:
            tree.lock_read()
            try:
                parent_ids = tree.get_parent_ids()
                num_parents = len(parent_ids)
                parent_trees = []
                for parent_id in parent_ids:
                    parent_tree = tree.branch.repository.revision_tree(parent_id)
                    parent_trees.append((parent_id, parent_tree))
                    parent_tree.lock_read()
                result.set_parent_trees(parent_trees, [])
                result.set_state_from_inventory(tree.inventory)
            finally:
                for revid, parent_tree in parent_trees:
                    parent_tree.unlock()
                tree.unlock()
        except:
            # The caller won't have a chance to unlock this, so make sure we
            # cleanup ourselves
            result.unlock()
            raise
        return result

    def update_by_delta(self, delta):
        """Apply an inventory delta to the dirstate for tree 0

        :param delta: An inventory delta.  See Inventory.apply_delta for
            details.
        """
        self._read_dirblocks_if_needed()
        insertions = {}
        removals = {}
        for old_path, new_path, file_id, inv_entry in sorted(delta, reverse=True):
            if (file_id in insertions) or (file_id in removals):
                raise AssertionError("repeated file id in delta %r" % (file_id,))
            if old_path is not None:
                old_path = old_path.encode('utf-8')
                removals[file_id] = old_path
            if new_path is not None:
                new_path = new_path.encode('utf-8')
                dirname, basename = osutils.split(new_path)
                key = (dirname, basename, file_id)
                minikind = DirState._kind_to_minikind[inv_entry.kind]
                if minikind == 't':
                    fingerprint = inv_entry.reference_revision
                else:
                    fingerprint = ''
                insertions[file_id] = (key, minikind, inv_entry.executable,
                                       fingerprint, new_path)
            # Transform moves into delete+add pairs
            if None not in (old_path, new_path):
                for child in self._iter_child_entries(0, old_path):
                    if child[0][2] in insertions or child[0][2] in removals:
                        continue
                    child_dirname = child[0][0]
                    child_basename = child[0][1]
                    minikind = child[1][0][0]
                    fingerprint = child[1][0][4]
                    executable = child[1][0][3]
                    old_child_path = osutils.pathjoin(child[0][0],
                                                      child[0][1])
                    removals[child[0][2]] = old_child_path
                    child_suffix = child_dirname[len(old_path):]
                    new_child_dirname = (new_path + child_suffix)
                    key = (new_child_dirname, child_basename, child[0][2])
                    new_child_path = os.path.join(new_child_dirname,
                                                  child_basename)
                    insertions[child[0][2]] = (key, minikind, executable,
                                               fingerprint, new_child_path)
        self._apply_removals(removals.values())
        self._apply_insertions(insertions.values())

    def _apply_removals(self, removals):
        for path in sorted(removals, reverse=True):
            dirname, basename = osutils.split(path)
            block_i, entry_i, d_present, f_present = \
                self._get_block_entry_index(dirname, basename, 0)
            entry = self._dirblocks[block_i][1][entry_i]
            self._make_absent(entry)
            # See if we have a malformed delta: deleting a directory must not
            # leave crud behind. This increases the number of bisects needed
            # substantially, but deletion or renames of large numbers of paths
            # is rare enough it shouldn't be an issue (famous last words?) RBC
            # 20080730.
            block_i, entry_i, d_present, f_present = \
                self._get_block_entry_index(path, '', 0)
            if d_present:
                # The dir block is still present in the dirstate; this could
                # be due to it being in a parent tree, or a corrupt delta.
                for child_entry in self._dirblocks[block_i][1]:
                    if child_entry[1][0][0] not in ('r', 'a'):
                        raise errors.InconsistentDelta(path, entry[0][2],
                            "The file id was deleted but its children were "
                            "not deleted.")

    def _apply_insertions(self, adds):
        for key, minikind, executable, fingerprint, path_utf8 in sorted(adds):
            self.update_minimal(key, minikind, executable, fingerprint,
                                path_utf8=path_utf8)

    def update_basis_by_delta(self, delta, new_revid):
        """Update the parents of this tree after a commit.

        This gives the tree one parent, with revision id new_revid. The
        inventory delta is applied to the current basis tree to generate the
        inventory for the parent new_revid, and all other parent trees are
        discarded.

        Note that an exception during the operation of this method will leave
        the dirstate in a corrupt state where it should not be saved.

        Finally, we expect all changes to be synchronising the basis tree with
        the working tree.

        :param new_revid: The new revision id for the trees parent.
        :param delta: An inventory delta (see apply_inventory_delta) describing
            the changes from the current left most parent revision to new_revid.
        """
        self._read_dirblocks_if_needed()
        self._discard_merge_parents()
        if self._ghosts != []:
            raise NotImplementedError(self.update_basis_by_delta)
        if len(self._parents) == 0:
            # setup a blank tree, the most simple way.
            empty_parent = DirState.NULL_PARENT_DETAILS
            for entry in self._iter_entries():
                entry[1].append(empty_parent)
            self._parents.append(new_revid)

        self._parents[0] = new_revid

        delta = sorted(delta, reverse=True)
        adds = []
        changes = []
        deletes = []
        # The paths this function accepts are unicode and must be encoded as we
        # go.
        encode = cache_utf8.encode
        inv_to_entry = self._inv_entry_to_details
        # delta is now (deletes, changes), (adds) in reverse lexographical
        # order.
        # deletes in reverse lexographic order are safe to process in situ.
        # renames are not, as a rename from any path could go to a path
        # lexographically lower, so we transform renames into delete, add pairs,
        # expanding them recursively as needed.
        # At the same time, to reduce interface friction we convert the input
        # inventory entries to dirstate.
        root_only = ('', '')
        for old_path, new_path, file_id, inv_entry in delta:
            if old_path is None:
                adds.append((None, encode(new_path), file_id,
                    inv_to_entry(inv_entry), True))
            elif new_path is None:
                deletes.append((encode(old_path), None, file_id, None, True))
            elif (old_path, new_path) != root_only:
                # Renames:
                # Because renames must preserve their children we must have
                # processed all relocations and removes before hand. The sort
                # order ensures we've examined the child paths, but we also
                # have to execute the removals, or the split to an add/delete
                # pair will result in the deleted item being reinserted, or
                # renamed items being reinserted twice - and possibly at the
                # wrong place. Splitting into a delete/add pair also simplifies
                # the handling of entries with ('f', ...), ('r' ...) because
                # the target of the 'r' is old_path here, and we add that to
                # deletes, meaning that the add handler does not need to check
                # for 'r' items on every pass.
                self._update_basis_apply_deletes(deletes)
                deletes = []
                new_path_utf8 = encode(new_path)
                # Split into an add/delete pair recursively.
                adds.append((None, new_path_utf8, file_id,
                    inv_to_entry(inv_entry), False))
                # Expunge deletes that we've seen so that deleted/renamed
                # children of a rename directory are handled correctly.
                new_deletes = reversed(list(self._iter_child_entries(1,
                    encode(old_path))))
                # Remove the current contents of the tree at orig_path, and
                # reinsert at the correct new path.
                for entry in new_deletes:
                    if entry[0][0]:
                        source_path = entry[0][0] + '/' + entry[0][1]
                    else:
                        source_path = entry[0][1]
                    if new_path_utf8:
                        target_path = new_path_utf8 + source_path[len(old_path):]
                    else:
                        if old_path == '':
                            raise AssertionError("cannot rename directory to"
                                " itself")
                        target_path = source_path[len(old_path) + 1:]
                    adds.append((None, target_path, entry[0][2], entry[1][1], False))
                    deletes.append(
                        (source_path, target_path, entry[0][2], None, False))
                deletes.append(
                    (encode(old_path), new_path, file_id, None, False))
            else:
                # changes to just the root should not require remove/insertion
                # of everything.
                changes.append((encode(old_path), encode(new_path), file_id,
                    inv_to_entry(inv_entry)))

        # Finish expunging deletes/first half of renames.
        self._update_basis_apply_deletes(deletes)
        # Reinstate second half of renames and new paths.
        self._update_basis_apply_adds(adds)
        # Apply in-situ changes.
        self._update_basis_apply_changes(changes)

        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._id_index = None
        return

    def _update_basis_apply_adds(self, adds):
        """Apply a sequence of adds to tree 1 during update_basis_by_delta.

        They may be adds, or renames that have been split into add/delete
        pairs.

        :param adds: A sequence of adds. Each add is a tuple:
            (None, new_path_utf8, file_id, (entry_details), real_add). real_add
            is False when the add is the second half of a remove-and-reinsert
            pair created to handle renames and deletes.
        """
        # Adds are accumulated partly from renames, so can be in any input
        # order - sort it.
        adds.sort()
        # adds is now in lexographic order, which places all parents before
        # their children, so we can process it linearly.
        absent = 'ar'
        for old_path, new_path, file_id, new_details, real_add in adds:
            # the entry for this file_id must be in tree 0.
            entry = self._get_entry(0, file_id, new_path)
            if entry[0] is None or entry[0][2] != file_id:
                self._changes_aborted = True
                raise errors.InconsistentDelta(new_path, file_id,
                    'working tree does not contain new entry')
            if real_add and entry[1][1][0] not in absent:
                self._changes_aborted = True
                raise errors.InconsistentDelta(new_path, file_id,
                    'The entry was considered to be a genuinely new record,'
                    ' but there was already an old record for it.')
            # We don't need to update the target of an 'r' because the handling
            # of renames turns all 'r' situations into a delete at the original
            # location.
            entry[1][1] = new_details

    def _update_basis_apply_changes(self, changes):
        """Apply a sequence of changes to tree 1 during update_basis_by_delta.

        :param adds: A sequence of changes. Each change is a tuple:
            (path_utf8, path_utf8, file_id, (entry_details))
        """
        absent = 'ar'
        for old_path, new_path, file_id, new_details in changes:
            # the entry for this file_id must be in tree 0.
            entry = self._get_entry(0, file_id, new_path)
            if entry[0] is None or entry[0][2] != file_id:
                self._changes_aborted = True
                raise errors.InconsistentDelta(new_path, file_id,
                    'working tree does not contain new entry')
            if (entry[1][0][0] in absent or
                entry[1][1][0] in absent):
                self._changes_aborted = True
                raise errors.InconsistentDelta(new_path, file_id,
                    'changed considered absent')
            entry[1][1] = new_details

    def _update_basis_apply_deletes(self, deletes):
        """Apply a sequence of deletes to tree 1 during update_basis_by_delta.

        They may be deletes, or renames that have been split into add/delete
        pairs.

        :param deletes: A sequence of deletes. Each delete is a tuple:
            (old_path_utf8, new_path_utf8, file_id, None, real_delete).
            real_delete is True when the desired outcome is an actual deletion
            rather than the rename handling logic temporarily deleting a path
            during the replacement of a parent.
        """
        null = DirState.NULL_PARENT_DETAILS
        for old_path, new_path, file_id, _, real_delete in deletes:
            if real_delete != (new_path is None):
                raise AssertionError("bad delete delta")
            # the entry for this file_id must be in tree 1.
            dirname, basename = osutils.split(old_path)
            block_index, entry_index, dir_present, file_present = \
                self._get_block_entry_index(dirname, basename, 1)
            if not file_present:
                self._changes_aborted = True
                raise errors.InconsistentDelta(old_path, file_id,
                    'basis tree does not contain removed entry')
            entry = self._dirblocks[block_index][1][entry_index]
            if entry[0][2] != file_id:
                self._changes_aborted = True
                raise errors.InconsistentDelta(old_path, file_id,
                    'mismatched file_id in tree 1')
            if real_delete:
                if entry[1][0][0] != 'a':
                    self._changes_aborted = True
                    raise errors.InconsistentDelta(old_path, file_id,
                            'This was marked as a real delete, but the WT state'
                            ' claims that it still exists and is versioned.')
                del self._dirblocks[block_index][1][entry_index]
            else:
                if entry[1][0][0] == 'a':
                    self._changes_aborted = True
                    raise errors.InconsistentDelta(old_path, file_id,
                        'The entry was considered a rename, but the source path'
                        ' is marked as absent.')
                    # For whatever reason, we were asked to rename an entry
                    # that was originally marked as deleted. This could be
                    # because we are renaming the parent directory, and the WT
                    # current state has the file marked as deleted.
                elif entry[1][0][0] == 'r':
                    # implement the rename
                    del self._dirblocks[block_index][1][entry_index]
                else:
                    # it is being resurrected here, so blank it out temporarily.
                    self._dirblocks[block_index][1][entry_index][1][1] = null

    def _observed_sha1(self, entry, sha1, stat_value,
        _stat_to_minikind=_stat_to_minikind, _pack_stat=pack_stat):
        """Note the sha1 of a file.

        :param entry: The entry the sha1 is for.
        :param sha1: The observed sha1.
        :param stat_value: The os.lstat for the file.
        """
        try:
            minikind = _stat_to_minikind[stat_value.st_mode & 0170000]
        except KeyError:
            # Unhandled kind
            return None
        packed_stat = _pack_stat(stat_value)
        if minikind == 'f':
            if self._cutoff_time is None:
                self._sha_cutoff_time()
            if (stat_value.st_mtime < self._cutoff_time
                and stat_value.st_ctime < self._cutoff_time):
                entry[1][0] = ('f', sha1, entry[1][0][2], entry[1][0][3],
                    packed_stat)
                self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def _sha_cutoff_time(self):
        """Return cutoff time.

        Files modified more recently than this time are at risk of being
        undetectably modified and so can't be cached.
        """
        # Cache the cutoff time as long as we hold a lock.
        # time.time() isn't super expensive (approx 3.38us), but
        # when you call it 50,000 times it adds up.
        # For comparison, os.lstat() costs 7.2us if it is hot.
        self._cutoff_time = int(time.time()) - 3
        return self._cutoff_time

    def _lstat(self, abspath, entry):
        """Return the os.lstat value for this path."""
        return os.lstat(abspath)

    def _sha1_file_and_mutter(self, abspath):
        # when -Dhashcache is turned on, this is monkey-patched in to log
        # file reads
        trace.mutter("dirstate sha1 " + abspath)
        return osutils.sha_file_by_name(abspath)

    def _is_executable(self, mode, old_executable):
        """Is this file executable?"""
        return bool(S_IEXEC & mode)

    def _is_executable_win32(self, mode, old_executable):
        """On win32 the executable bit is stored in the dirstate."""
        return old_executable

    if sys.platform == 'win32':
        _is_executable = _is_executable_win32

    def _read_link(self, abspath, old_link):
        """Read the target of a symlink"""
        # TODO: jam 200700301 On Win32, this could just return the value
        #       already in memory. However, this really needs to be done at a
        #       higher level, because there either won't be anything on disk,
        #       or the thing on disk will be a file.
        return os.readlink(abspath)

    def get_ghosts(self):
        """Return a list of the parent tree revision ids that are ghosts."""
        self._read_header_if_needed()
        return self._ghosts

    def get_lines(self):
        """Serialise the entire dirstate to a sequence of lines."""
        if (self._header_state == DirState.IN_MEMORY_UNMODIFIED and
            self._dirblock_state == DirState.IN_MEMORY_UNMODIFIED):
            # read whats on disk.
            self._state_file.seek(0)
            return self._state_file.readlines()
        lines = []
        lines.append(self._get_parents_line(self.get_parent_ids()))
        lines.append(self._get_ghosts_line(self._ghosts))
        # append the root line which is special cased
        lines.extend(map(self._entry_to_line, self._iter_entries()))
        return self._get_output_lines(lines)

    def _get_ghosts_line(self, ghost_ids):
        """Create a line for the state file for ghost information."""
        return '\0'.join([str(len(ghost_ids))] + ghost_ids)

    def _get_parents_line(self, parent_ids):
        """Create a line for the state file for parents information."""
        return '\0'.join([str(len(parent_ids))] + parent_ids)

    def _get_fields_to_entry(self):
        """Get a function which converts entry fields into a entry record.

        This handles size and executable, as well as parent records.

        :return: A function which takes a list of fields, and returns an
            appropriate record for storing in memory.
        """
        # This is intentionally unrolled for performance
        num_present_parents = self._num_present_parents()
        if num_present_parents == 0:
            def fields_to_entry_0_parents(fields, _int=int):
                path_name_file_id_key = (fields[0], fields[1], fields[2])
                return (path_name_file_id_key, [
                    ( # Current tree
                        fields[3],                # minikind
                        fields[4],                # fingerprint
                        _int(fields[5]),          # size
                        fields[6] == 'y',         # executable
                        fields[7],                # packed_stat or revision_id
                    )])
            return fields_to_entry_0_parents
        elif num_present_parents == 1:
            def fields_to_entry_1_parent(fields, _int=int):
                path_name_file_id_key = (fields[0], fields[1], fields[2])
                return (path_name_file_id_key, [
                    ( # Current tree
                        fields[3],                # minikind
                        fields[4],                # fingerprint
                        _int(fields[5]),          # size
                        fields[6] == 'y',         # executable
                        fields[7],                # packed_stat or revision_id
                    ),
                    ( # Parent 1
                        fields[8],                # minikind
                        fields[9],                # fingerprint
                        _int(fields[10]),         # size
                        fields[11] == 'y',        # executable
                        fields[12],               # packed_stat or revision_id
                    ),
                    ])
            return fields_to_entry_1_parent
        elif num_present_parents == 2:
            def fields_to_entry_2_parents(fields, _int=int):
                path_name_file_id_key = (fields[0], fields[1], fields[2])
                return (path_name_file_id_key, [
                    ( # Current tree
                        fields[3],                # minikind
                        fields[4],                # fingerprint
                        _int(fields[5]),          # size
                        fields[6] == 'y',         # executable
                        fields[7],                # packed_stat or revision_id
                    ),
                    ( # Parent 1
                        fields[8],                # minikind
                        fields[9],                # fingerprint
                        _int(fields[10]),         # size
                        fields[11] == 'y',        # executable
                        fields[12],               # packed_stat or revision_id
                    ),
                    ( # Parent 2
                        fields[13],               # minikind
                        fields[14],               # fingerprint
                        _int(fields[15]),         # size
                        fields[16] == 'y',        # executable
                        fields[17],               # packed_stat or revision_id
                    ),
                    ])
            return fields_to_entry_2_parents
        else:
            def fields_to_entry_n_parents(fields, _int=int):
                path_name_file_id_key = (fields[0], fields[1], fields[2])
                trees = [(fields[cur],                # minikind
                          fields[cur+1],              # fingerprint
                          _int(fields[cur+2]),        # size
                          fields[cur+3] == 'y',       # executable
                          fields[cur+4],              # stat or revision_id
                         ) for cur in xrange(3, len(fields)-1, 5)]
                return path_name_file_id_key, trees
            return fields_to_entry_n_parents

    def get_parent_ids(self):
        """Return a list of the parent tree ids for the directory state."""
        self._read_header_if_needed()
        return list(self._parents)

    def _get_block_entry_index(self, dirname, basename, tree_index):
        """Get the coordinates for a path in the state structure.

        :param dirname: The utf8 dirname to lookup.
        :param basename: The utf8 basename to lookup.
        :param tree_index: The index of the tree for which this lookup should
            be attempted.
        :return: A tuple describing where the path is located, or should be
            inserted. The tuple contains four fields: the block index, the row
            index, the directory is present (boolean), the entire path is
            present (boolean).  There is no guarantee that either
            coordinate is currently reachable unless the found field for it is
            True. For instance, a directory not present in the searched tree
            may be returned with a value one greater than the current highest
            block offset. The directory present field will always be True when
            the path present field is True. The directory present field does
            NOT indicate that the directory is present in the searched tree,
            rather it indicates that there are at least some files in some
            tree present there.
        """
        self._read_dirblocks_if_needed()
        key = dirname, basename, ''
        block_index, present = self._find_block_index_from_key(key)
        if not present:
            # no such directory - return the dir index and 0 for the row.
            return block_index, 0, False, False
        block = self._dirblocks[block_index][1] # access the entries only
        entry_index, present = self._find_entry_index(key, block)
        # linear search through entries at this path to find the one
        # requested.
        while entry_index < len(block) and block[entry_index][0][1] == basename:
            if block[entry_index][1][tree_index][0] not in 'ar':
                # neither absent or relocated
                return block_index, entry_index, True, True
            entry_index += 1
        return block_index, entry_index, True, False

    def _get_entry(self, tree_index, fileid_utf8=None, path_utf8=None):
        """Get the dirstate entry for path in tree tree_index.

        If either file_id or path is supplied, it is used as the key to lookup.
        If both are supplied, the fastest lookup is used, and an error is
        raised if they do not both point at the same row.

        :param tree_index: The index of the tree we wish to locate this path
            in. If the path is present in that tree, the entry containing its
            details is returned, otherwise (None, None) is returned
            0 is the working tree, higher indexes are successive parent
            trees.
        :param fileid_utf8: A utf8 file_id to look up.
        :param path_utf8: An utf8 path to be looked up.
        :return: The dirstate entry tuple for path, or (None, None)
        """
        self._read_dirblocks_if_needed()
        if path_utf8 is not None:
            if type(path_utf8) is not str:
                raise AssertionError('path_utf8 is not a str: %s %s'
                    % (type(path_utf8), path_utf8))
            # path lookups are faster
            dirname, basename = osutils.split(path_utf8)
            block_index, entry_index, dir_present, file_present = \
                self._get_block_entry_index(dirname, basename, tree_index)
            if not file_present:
                return None, None
            entry = self._dirblocks[block_index][1][entry_index]
            if not (entry[0][2] and entry[1][tree_index][0] not in ('a', 'r')):
                raise AssertionError('unversioned entry?')
            if fileid_utf8:
                if entry[0][2] != fileid_utf8:
                    self._changes_aborted = True
                    raise errors.BzrError('integrity error ? : mismatching'
                                          ' tree_index, file_id and path')
            return entry
        else:
            possible_keys = self._get_id_index().get(fileid_utf8, None)
            if not possible_keys:
                return None, None
            for key in possible_keys:
                block_index, present = \
                    self._find_block_index_from_key(key)
                # strange, probably indicates an out of date
                # id index - for now, allow this.
                if not present:
                    continue
                # WARNING: DO not change this code to use _get_block_entry_index
                # as that function is not suitable: it does not use the key
                # to lookup, and thus the wrong coordinates are returned.
                block = self._dirblocks[block_index][1]
                entry_index, present = self._find_entry_index(key, block)
                if present:
                    entry = self._dirblocks[block_index][1][entry_index]
                    if entry[1][tree_index][0] in 'fdlt':
                        # this is the result we are looking for: the  
                        # real home of this file_id in this tree.
                        return entry
                    if entry[1][tree_index][0] == 'a':
                        # there is no home for this entry in this tree
                        return None, None
                    if entry[1][tree_index][0] != 'r':
                        raise AssertionError(
                            "entry %r has invalid minikind %r for tree %r" \
                            % (entry,
                               entry[1][tree_index][0],
                               tree_index))
                    real_path = entry[1][tree_index][1]
                    return self._get_entry(tree_index, fileid_utf8=fileid_utf8,
                        path_utf8=real_path)
            return None, None

    @classmethod
    def initialize(cls, path):
        """Create a new dirstate on path.

        The new dirstate will be an empty tree - that is it has no parents,
        and only a root node - which has id ROOT_ID.

        :param path: The name of the file for the dirstate.
        :return: A write-locked DirState object.
        """
        # This constructs a new DirState object on a path, sets the _state_file
        # to a new empty file for that path. It then calls _set_data() with our
        # stock empty dirstate information - a root with ROOT_ID, no children,
        # and no parents. Finally it calls save() to ensure that this data will
        # persist.
        result = cls(path)
        # root dir and root dir contents with no children.
        empty_tree_dirblocks = [('', []), ('', [])]
        # a new root directory, with a NULLSTAT.
        empty_tree_dirblocks[0][1].append(
            (('', '', inventory.ROOT_ID), [
                ('d', '', 0, False, DirState.NULLSTAT),
            ]))
        result.lock_write()
        try:
            result._set_data([], empty_tree_dirblocks)
            result.save()
        except:
            result.unlock()
            raise
        return result

    @staticmethod
    def _inv_entry_to_details(inv_entry):
        """Convert an inventory entry (from a revision tree) to state details.

        :param inv_entry: An inventory entry whose sha1 and link targets can be
            relied upon, and which has a revision set.
        :return: A details tuple - the details for a single tree at a path +
            id.
        """
        kind = inv_entry.kind
        minikind = DirState._kind_to_minikind[kind]
        tree_data = inv_entry.revision
        if kind == 'directory':
            fingerprint = ''
            size = 0
            executable = False
        elif kind == 'symlink':
            # We don't support non-ascii targets for symlinks yet.
            fingerprint = str(inv_entry.symlink_target or '')
            size = 0
            executable = False
        elif kind == 'file':
            fingerprint = inv_entry.text_sha1 or ''
            size = inv_entry.text_size or 0
            executable = inv_entry.executable
        elif kind == 'tree-reference':
            fingerprint = inv_entry.reference_revision or ''
            size = 0
            executable = False
        else:
            raise Exception("can't pack %s" % inv_entry)
        return (minikind, fingerprint, size, executable, tree_data)

    def _iter_child_entries(self, tree_index, path_utf8):
        """Iterate over all the entries that are children of path_utf.

        This only returns entries that are present (not in 'a', 'r') in 
        tree_index. tree_index data is not refreshed, so if tree 0 is used,
        results may differ from that obtained if paths were statted to
        determine what ones were directories.

        Asking for the children of a non-directory will return an empty
        iterator.
        """
        pending_dirs = []
        next_pending_dirs = [path_utf8]
        absent = 'ar'
        while next_pending_dirs:
            pending_dirs = next_pending_dirs
            next_pending_dirs = []
            for path in pending_dirs:
                block_index, present = self._find_block_index_from_key(
                    (path, '', ''))
                if block_index == 0:
                    block_index = 1
                    if len(self._dirblocks) == 1:
                        # asked for the children of the root with no other
                        # contents.
                        return
                if not present:
                    # children of a non-directory asked for.
                    continue
                block = self._dirblocks[block_index]
                for entry in block[1]:
                    kind = entry[1][tree_index][0]
                    if kind not in absent:
                        yield entry
                    if kind == 'd':
                        if entry[0][0]:
                            path = entry[0][0] + '/' + entry[0][1]
                        else:
                            path = entry[0][1]
                        next_pending_dirs.append(path)
    
    def _iter_entries(self):
        """Iterate over all the entries in the dirstate.

        Each yelt item is an entry in the standard format described in the
        docstring of bzrlib.dirstate.
        """
        self._read_dirblocks_if_needed()
        for directory in self._dirblocks:
            for entry in directory[1]:
                yield entry

    def _get_id_index(self):
        """Get an id index of self._dirblocks."""
        if self._id_index is None:
            id_index = {}
            for key, tree_details in self._iter_entries():
                id_index.setdefault(key[2], set()).add(key)
            self._id_index = id_index
        return self._id_index

    def _get_output_lines(self, lines):
        """Format lines for final output.

        :param lines: A sequence of lines containing the parents list and the
            path lines.
        """
        output_lines = [DirState.HEADER_FORMAT_3]
        lines.append('') # a final newline
        inventory_text = '\0\n\0'.join(lines)
        output_lines.append('crc32: %s\n' % (zlib.crc32(inventory_text),))
        # -3, 1 for num parents, 1 for ghosts, 1 for final newline
        num_entries = len(lines)-3
        output_lines.append('num_entries: %s\n' % (num_entries,))
        output_lines.append(inventory_text)
        return output_lines

    def _make_deleted_row(self, fileid_utf8, parents):
        """Return a deleted row for fileid_utf8."""
        return ('/', 'RECYCLED.BIN', 'file', fileid_utf8, 0, DirState.NULLSTAT,
            ''), parents

    def _num_present_parents(self):
        """The number of parent entries in each record row."""
        return len(self._parents) - len(self._ghosts)

    @staticmethod
    def on_file(path):
        """Construct a DirState on the file at path path.

        :return: An unlocked DirState object, associated with the given path.
        """
        result = DirState(path)
        return result

    def _read_dirblocks_if_needed(self):
        """Read in all the dirblocks from the file if they are not in memory.
        
        This populates self._dirblocks, and sets self._dirblock_state to
        IN_MEMORY_UNMODIFIED. It is not currently ready for incremental block
        loading.
        """
        self._read_header_if_needed()
        if self._dirblock_state == DirState.NOT_IN_MEMORY:
            _read_dirblocks(self)

    def _read_header(self):
        """This reads in the metadata header, and the parent ids.

        After reading in, the file should be positioned at the null
        just before the start of the first record in the file.

        :return: (expected crc checksum, number of entries, parent list)
        """
        self._read_prelude()
        parent_line = self._state_file.readline()
        info = parent_line.split('\0')
        num_parents = int(info[0])
        self._parents = info[1:-1]
        ghost_line = self._state_file.readline()
        info = ghost_line.split('\0')
        num_ghosts = int(info[1])
        self._ghosts = info[2:-1]
        self._header_state = DirState.IN_MEMORY_UNMODIFIED
        self._end_of_header = self._state_file.tell()

    def _read_header_if_needed(self):
        """Read the header of the dirstate file if needed."""
        # inline this as it will be called a lot
        if not self._lock_token:
            raise errors.ObjectNotLocked(self)
        if self._header_state == DirState.NOT_IN_MEMORY:
            self._read_header()

    def _read_prelude(self):
        """Read in the prelude header of the dirstate file.

        This only reads in the stuff that is not connected to the crc
        checksum. The position will be correct to read in the rest of
        the file and check the checksum after this point.
        The next entry in the file should be the number of parents,
        and their ids. Followed by a newline.
        """
        header = self._state_file.readline()
        if header != DirState.HEADER_FORMAT_3:
            raise errors.BzrError(
                'invalid header line: %r' % (header,))
        crc_line = self._state_file.readline()
        if not crc_line.startswith('crc32: '):
            raise errors.BzrError('missing crc32 checksum: %r' % crc_line)
        self.crc_expected = int(crc_line[len('crc32: '):-1])
        num_entries_line = self._state_file.readline()
        if not num_entries_line.startswith('num_entries: '):
            raise errors.BzrError('missing num_entries line')
        self._num_entries = int(num_entries_line[len('num_entries: '):-1])

    def sha1_from_stat(self, path, stat_result, _pack_stat=pack_stat):
        """Find a sha1 given a stat lookup."""
        return self._get_packed_stat_index().get(_pack_stat(stat_result), None)

    def _get_packed_stat_index(self):
        """Get a packed_stat index of self._dirblocks."""
        if self._packed_stat_index is None:
            index = {}
            for key, tree_details in self._iter_entries():
                if tree_details[0][0] == 'f':
                    index[tree_details[0][4]] = tree_details[0][1]
            self._packed_stat_index = index
        return self._packed_stat_index

    def save(self):
        """Save any pending changes created during this session.

        We reuse the existing file, because that prevents race conditions with
        file creation, and use oslocks on it to prevent concurrent modification
        and reads - because dirstate's incremental data aggregation is not
        compatible with reading a modified file, and replacing a file in use by
        another process is impossible on Windows.

        A dirstate in read only mode should be smart enough though to validate
        that the file has not changed, and otherwise discard its cache and
        start over, to allow for fine grained read lock duration, so 'status'
        wont block 'commit' - for example.
        """
        if self._changes_aborted:
            # Should this be a warning? For now, I'm expecting that places that
            # mark it inconsistent will warn, making a warning here redundant.
            trace.mutter('Not saving DirState because '
                    '_changes_aborted is set.')
            return
        if (self._header_state == DirState.IN_MEMORY_MODIFIED or
            self._dirblock_state == DirState.IN_MEMORY_MODIFIED):

            grabbed_write_lock = False
            if self._lock_state != 'w':
                grabbed_write_lock, new_lock = self._lock_token.temporary_write_lock()
                # Switch over to the new lock, as the old one may be closed.
                # TODO: jam 20070315 We should validate the disk file has
                #       not changed contents. Since temporary_write_lock may
                #       not be an atomic operation.
                self._lock_token = new_lock
                self._state_file = new_lock.f
                if not grabbed_write_lock:
                    # We couldn't grab a write lock, so we switch back to a read one
                    return
            try:
                self._state_file.seek(0)
                self._state_file.writelines(self.get_lines())
                self._state_file.truncate()
                self._state_file.flush()
                self._header_state = DirState.IN_MEMORY_UNMODIFIED
                self._dirblock_state = DirState.IN_MEMORY_UNMODIFIED
            finally:
                if grabbed_write_lock:
                    self._lock_token = self._lock_token.restore_read_lock()
                    self._state_file = self._lock_token.f
                    # TODO: jam 20070315 We should validate the disk file has
                    #       not changed contents. Since restore_read_lock may
                    #       not be an atomic operation.

    def _set_data(self, parent_ids, dirblocks):
        """Set the full dirstate data in memory.

        This is an internal function used to completely replace the objects
        in memory state. It puts the dirstate into state 'full-dirty'.

        :param parent_ids: A list of parent tree revision ids.
        :param dirblocks: A list containing one tuple for each directory in the
            tree. Each tuple contains the directory path and a list of entries 
            found in that directory.
        """
        # our memory copy is now authoritative.
        self._dirblocks = dirblocks
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._parents = list(parent_ids)
        self._id_index = None
        self._packed_stat_index = None

    def set_path_id(self, path, new_id):
        """Change the id of path to new_id in the current working tree.

        :param path: The path inside the tree to set - '' is the root, 'foo'
            is the path foo in the root.
        :param new_id: The new id to assign to the path. This must be a utf8
            file id (not unicode, and not None).
        """
        self._read_dirblocks_if_needed()
        if len(path):
            # TODO: logic not written
            raise NotImplementedError(self.set_path_id)
        # TODO: check new id is unique
        entry = self._get_entry(0, path_utf8=path)
        if entry[0][2] == new_id:
            # Nothing to change.
            return
        # mark the old path absent, and insert a new root path
        self._make_absent(entry)
        self.update_minimal(('', '', new_id), 'd',
            path_utf8='', packed_stat=entry[1][0][4])
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        if self._id_index is not None:
            self._id_index.setdefault(new_id, set()).add(entry[0])

    def set_parent_trees(self, trees, ghosts):
        """Set the parent trees for the dirstate.

        :param trees: A list of revision_id, tree tuples. tree must be provided
            even if the revision_id refers to a ghost: supply an empty tree in 
            this case.
        :param ghosts: A list of the revision_ids that are ghosts at the time
            of setting.
        """ 
        # TODO: generate a list of parent indexes to preserve to save 
        # processing specific parent trees. In the common case one tree will
        # be preserved - the left most parent.
        # TODO: if the parent tree is a dirstate, we might want to walk them
        # all by path in parallel for 'optimal' common-case performance.
        # generate new root row.
        self._read_dirblocks_if_needed()
        # TODO future sketch: Examine the existing parents to generate a change
        # map and then walk the new parent trees only, mapping them into the
        # dirstate. Walk the dirstate at the same time to remove unreferenced
        # entries.
        # for now: 
        # sketch: loop over all entries in the dirstate, cherry picking 
        # entries from the parent trees, if they are not ghost trees.
        # after we finish walking the dirstate, all entries not in the dirstate
        # are deletes, so we want to append them to the end as per the design
        # discussions. So do a set difference on ids with the parents to
        # get deletes, and add them to the end.
        # During the update process we need to answer the following questions:
        # - find other keys containing a fileid in order to create cross-path
        #   links. We dont't trivially use the inventory from other trees
        #   because this leads to either double touching, or to accessing
        #   missing keys,
        # - find other keys containing a path 
        # We accumulate each entry via this dictionary, including the root 
        by_path = {}
        id_index = {}
        # we could do parallel iterators, but because file id data may be
        # scattered throughout, we dont save on index overhead: we have to look
        # at everything anyway. We can probably save cycles by reusing parent
        # data and doing an incremental update when adding an additional
        # parent, but for now the common cases are adding a new parent (merge),
        # and replacing completely (commit), and commit is more common: so
        # optimise merge later.
        
        # ---- start generation of full tree mapping data
        # what trees should we use?
        parent_trees = [tree for rev_id, tree in trees if rev_id not in ghosts]
        # how many trees do we end up with 
        parent_count = len(parent_trees)

        # one: the current tree
        for entry in self._iter_entries():
            # skip entries not in the current tree
            if entry[1][0][0] in 'ar': # absent, relocated
                continue
            by_path[entry[0]] = [entry[1][0]] + \
                [DirState.NULL_PARENT_DETAILS] * parent_count
            id_index[entry[0][2]] = set([entry[0]])
        
        # now the parent trees:
        for tree_index, tree in enumerate(parent_trees):
            # the index is off by one, adjust it.
            tree_index = tree_index + 1
            # when we add new locations for a fileid we need these ranges for
            # any fileid in this tree as we set the by_path[id] to:
            # already_processed_tree_details + new_details + new_location_suffix
            # the suffix is from tree_index+1:parent_count+1.
            new_location_suffix = [DirState.NULL_PARENT_DETAILS] * (parent_count - tree_index)
            # now stitch in all the entries from this tree
            for path, entry in tree.inventory.iter_entries_by_dir():
                # here we process each trees details for each item in the tree.
                # we first update any existing entries for the id at other paths,
                # then we either create or update the entry for the id at the
                # right path, and finally we add (if needed) a mapping from
                # file_id to this path. We do it in this order to allow us to
                # avoid checking all known paths for the id when generating a
                # new entry at this path: by adding the id->path mapping last,
                # all the mappings are valid and have correct relocation
                # records where needed. 
                file_id = entry.file_id
                path_utf8 = path.encode('utf8')
                dirname, basename = osutils.split(path_utf8)
                new_entry_key = (dirname, basename, file_id)
                # tree index consistency: All other paths for this id in this tree
                # index must point to the correct path.
                for entry_key in id_index.setdefault(file_id, set()):
                    # TODO:PROFILING: It might be faster to just update
                    # rather than checking if we need to, and then overwrite
                    # the one we are located at.
                    if entry_key != new_entry_key:
                        # this file id is at a different path in one of the
                        # other trees, so put absent pointers there
                        # This is the vertical axis in the matrix, all pointing
                        # to the real path.
                        by_path[entry_key][tree_index] = ('r', path_utf8, 0, False, '')
                # by path consistency: Insert into an existing path record (trivial), or 
                # add a new one with relocation pointers for the other tree indexes.
                if new_entry_key in id_index[file_id]:
                    # there is already an entry where this data belongs, just insert it.
                    by_path[new_entry_key][tree_index] = \
                        self._inv_entry_to_details(entry)
                else:
                    # add relocated entries to the horizontal axis - this row
                    # mapping from path,id. We need to look up the correct path
                    # for the indexes from 0 to tree_index -1
                    new_details = []
                    for lookup_index in xrange(tree_index):
                        # boundary case: this is the first occurence of file_id
                        # so there are no id_indexs, possibly take this out of
                        # the loop?
                        if not len(id_index[file_id]):
                            new_details.append(DirState.NULL_PARENT_DETAILS)
                        else:
                            # grab any one entry, use it to find the right path.
                            # TODO: optimise this to reduce memory use in highly 
                            # fragmented situations by reusing the relocation
                            # records.
                            a_key = iter(id_index[file_id]).next()
                            if by_path[a_key][lookup_index][0] in ('r', 'a'):
                                # its a pointer or missing statement, use it as is.
                                new_details.append(by_path[a_key][lookup_index])
                            else:
                                # we have the right key, make a pointer to it.
                                real_path = ('/'.join(a_key[0:2])).strip('/')
                                new_details.append(('r', real_path, 0, False, ''))
                    new_details.append(self._inv_entry_to_details(entry))
                    new_details.extend(new_location_suffix)
                    by_path[new_entry_key] = new_details
                    id_index[file_id].add(new_entry_key)
        # --- end generation of full tree mappings

        # sort and output all the entries
        new_entries = self._sort_entries(by_path.items())
        self._entries_to_current_state(new_entries)
        self._parents = [rev_id for rev_id, tree in trees]
        self._ghosts = list(ghosts)
        self._header_state = DirState.IN_MEMORY_MODIFIED
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._id_index = id_index

    def _sort_entries(self, entry_list):
        """Given a list of entries, sort them into the right order.

        This is done when constructing a new dirstate from trees - normally we
        try to keep everything in sorted blocks all the time, but sometimes
        it's easier to sort after the fact.
        """
        def _key(entry):
            # sort by: directory parts, file name, file id
            return entry[0][0].split('/'), entry[0][1], entry[0][2]
        return sorted(entry_list, key=_key)

    def set_state_from_inventory(self, new_inv):
        """Set new_inv as the current state. 

        This API is called by tree transform, and will usually occur with
        existing parent trees.

        :param new_inv: The inventory object to set current state from.
        """
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(1,
                "set_state_from_inventory called; please mutate the tree instead")
        self._read_dirblocks_if_needed()
        # sketch:
        # Two iterators: current data and new data, both in dirblock order. 
        # We zip them together, which tells about entries that are new in the
        # inventory, or removed in the inventory, or present in both and
        # possibly changed.  
        #
        # You might think we could just synthesize a new dirstate directly
        # since we're processing it in the right order.  However, we need to
        # also consider there may be any number of parent trees and relocation
        # pointers, and we don't want to duplicate that here.
        new_iterator = new_inv.iter_entries_by_dir()
        # we will be modifying the dirstate, so we need a stable iterator. In
        # future we might write one, for now we just clone the state into a
        # list - which is a shallow copy.
        old_iterator = iter(list(self._iter_entries()))
        # both must have roots so this is safe:
        current_new = new_iterator.next()
        current_old = old_iterator.next()
        def advance(iterator):
            try:
                return iterator.next()
            except StopIteration:
                return None
        while current_new or current_old:
            # skip entries in old that are not really there
            if current_old and current_old[1][0][0] in 'ar':
                # relocated or absent
                current_old = advance(old_iterator)
                continue
            if current_new:
                # convert new into dirblock style
                new_path_utf8 = current_new[0].encode('utf8')
                new_dirname, new_basename = osutils.split(new_path_utf8)
                new_id = current_new[1].file_id
                new_entry_key = (new_dirname, new_basename, new_id)
                current_new_minikind = \
                    DirState._kind_to_minikind[current_new[1].kind]
                if current_new_minikind == 't':
                    fingerprint = current_new[1].reference_revision or ''
                else:
                    # We normally only insert or remove records, or update
                    # them when it has significantly changed.  Then we want to
                    # erase its fingerprint.  Unaffected records should
                    # normally not be updated at all.
                    fingerprint = ''
            else:
                # for safety disable variables
                new_path_utf8 = new_dirname = new_basename = new_id = \
                    new_entry_key = None
            # 5 cases, we dont have a value that is strictly greater than everything, so
            # we make both end conditions explicit
            if not current_old:
                # old is finished: insert current_new into the state.
                self.update_minimal(new_entry_key, current_new_minikind,
                    executable=current_new[1].executable,
                    path_utf8=new_path_utf8, fingerprint=fingerprint)
                current_new = advance(new_iterator)
            elif not current_new:
                # new is finished
                self._make_absent(current_old)
                current_old = advance(old_iterator)
            elif new_entry_key == current_old[0]:
                # same -  common case
                # We're looking at the same path and id in both the dirstate
                # and inventory, so just need to update the fields in the
                # dirstate from the one in the inventory.
                # TODO: update the record if anything significant has changed.
                # the minimal required trigger is if the execute bit or cached
                # kind has changed.
                if (current_old[1][0][3] != current_new[1].executable or
                    current_old[1][0][0] != current_new_minikind):
                    self.update_minimal(current_old[0], current_new_minikind,
                        executable=current_new[1].executable,
                        path_utf8=new_path_utf8, fingerprint=fingerprint)
                # both sides are dealt with, move on
                current_old = advance(old_iterator)
                current_new = advance(new_iterator)
            elif (cmp_by_dirs(new_dirname, current_old[0][0]) < 0
                  or (new_dirname == current_old[0][0]
                      and new_entry_key[1:] < current_old[0][1:])):
                # new comes before:
                # add a entry for this and advance new
                self.update_minimal(new_entry_key, current_new_minikind,
                    executable=current_new[1].executable,
                    path_utf8=new_path_utf8, fingerprint=fingerprint)
                current_new = advance(new_iterator)
            else:
                # we've advanced past the place where the old key would be,
                # without seeing it in the new list.  so it must be gone.
                self._make_absent(current_old)
                current_old = advance(old_iterator)
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        self._id_index = None
        self._packed_stat_index = None

    def _make_absent(self, current_old):
        """Mark current_old - an entry - as absent for tree 0.

        :return: True if this was the last details entry for the entry key:
            that is, if the underlying block has had the entry removed, thus
            shrinking in length.
        """
        # build up paths that this id will be left at after the change is made,
        # so we can update their cross references in tree 0
        all_remaining_keys = set()
        # Dont check the working tree, because it's going.
        for details in current_old[1][1:]:
            if details[0] not in 'ar': # absent, relocated
                all_remaining_keys.add(current_old[0])
            elif details[0] == 'r': # relocated
                # record the key for the real path.
                all_remaining_keys.add(tuple(osutils.split(details[1])) + (current_old[0][2],))
            # absent rows are not present at any path.
        last_reference = current_old[0] not in all_remaining_keys
        if last_reference:
            # the current row consists entire of the current item (being marked
            # absent), and relocated or absent entries for the other trees:
            # Remove it, its meaningless.
            block = self._find_block(current_old[0])
            entry_index, present = self._find_entry_index(current_old[0], block[1])
            if not present:
                raise AssertionError('could not find entry for %s' % (current_old,))
            block[1].pop(entry_index)
            # if we have an id_index in use, remove this key from it for this id.
            if self._id_index is not None:
                self._id_index[current_old[0][2]].remove(current_old[0])
        # update all remaining keys for this id to record it as absent. The
        # existing details may either be the record we are marking as deleted
        # (if there were other trees with the id present at this path), or may
        # be relocations.
        for update_key in all_remaining_keys:
            update_block_index, present = \
                self._find_block_index_from_key(update_key)
            if not present:
                raise AssertionError('could not find block for %s' % (update_key,))
            update_entry_index, present = \
                self._find_entry_index(update_key, self._dirblocks[update_block_index][1])
            if not present:
                raise AssertionError('could not find entry for %s' % (update_key,))
            update_tree_details = self._dirblocks[update_block_index][1][update_entry_index][1]
            # it must not be absent at the moment
            if update_tree_details[0][0] == 'a': # absent
                raise AssertionError('bad row %r' % (update_tree_details,))
            update_tree_details[0] = DirState.NULL_PARENT_DETAILS
        self._dirblock_state = DirState.IN_MEMORY_MODIFIED
        return last_reference

    def update_minimal(self, key, minikind, executable=False, fingerprint='',
                       packed_stat=None, size=0, path_utf8=None):
        """Update an entry to the state in tree 0.

        This will either create a new entry at 'key' or update an existing one.
        It also makes sure that any other records which might mention this are
        updated as well.

        :param key: (dir, name, file_id) for the new entry
        :param minikind: The type for the entry ('f' == 'file', 'd' ==
                'directory'), etc.
        :param executable: Should the executable bit be set?
        :param fingerprint: Simple fingerprint for new entry: sha1 for files, 
            referenced revision id for subtrees, etc.
        :param packed_stat: Packed stat value for new entry.
        :param size: Size information for new entry
        :param path_utf8: key[0] + '/' + key[1], just passed in to avoid doing
                extra computation.

        If packed_stat and fingerprint are not given, they're invalidated in
        the entry.
        """
        block = self._find_block(key)[1]
        if packed_stat is None:
            packed_stat = DirState.NULLSTAT
        # XXX: Some callers pass '' as the packed_stat, and it seems to be
        # sometimes present in the dirstate - this seems oddly inconsistent.
        # mbp 20071008
        entry_index, present = self._find_entry_index(key, block)
        new_details = (minikind, fingerprint, size, executable, packed_stat)
        id_index = self._get_id_index()
        if not present:
            # new entry, synthesis cross reference here,
            existing_keys = id_index.setdefault(key[2], set())
            if not existing_keys:
                # not currently in the state, simplest case
                new_entry = key, [new_details] + self._empty_parent_info()
            else:
                # present at one or more existing other paths.
                # grab one of them and use it to generate parent
                # relocation/absent entries.
                new_entry = key, [new_details]
                for other_key in existing_keys:
                    # change the record at other to be a pointer to this new
                    # record. The loop looks similar to the change to
                    # relocations when updating an existing record but its not:
                    # the test for existing kinds is different: this can be
                    # factored out to a helper though.
                    other_block_index, present = self._find_block_index_from_key(other_key)
                    if not present:
                        raise AssertionError('could not find block for %s' % (other_key,))
                    other_entry_index, present = self._find_entry_index(other_key,
                                            self._dirblocks[other_block_index][1])
                    if not present:
                        raise AssertionError('could not find entry for %s' % (other_key,))
                    if path_utf8 is None:
                        raise AssertionError('no path')
                    self._dirblocks[other_block_index][1][other_entry_index][1][0] = \
                        ('r', path_utf8, 0, False, '')

                num_present_parents = self._num_present_parents()
                for lookup_index in xrange(1, num_present_parents + 1):
                    # grab any one entry, use it to find the right path.
                    # TODO: optimise this to reduce memory use in highly 
                    # fragmented situations by reusing the relocation
                    # records.
                    update_block_index, present = \
                        self._find_block_index_from_key(other_key)
                    if not present:
                        raise AssertionError('could not find block for %s' % (other_key,))
                    update_entry_index, present = \
                        self._find_entry_index(other_key, self._dirblocks[update_block_index][1])
                    if not present:
                        raise AssertionError('could not find entry for %s' % (other_key,))
                    update_details = self._dirblocks[update_block_index][1][update_entry_index][1][lookup_index]
                    if update_details[0] in 'ar': # relocated, absent
                        # its a pointer or absent in lookup_index's tree, use
                        # it as is.
                        new_entry[1].append(update_details)
                    else:
                        # we have the right key, make a pointer to it.
                        pointer_path = osutils.pathjoin(*other_key[0:2])
                        new_entry[1].append(('r', pointer_path, 0, False, ''))
            block.insert(entry_index, new_entry)
            existing_keys.add(key)
        else:
            # Does the new state matter? 
            block[entry_index][1][0] = new_details
            # parents cannot be affected by what we do.
            # other occurences of this id can be found 
            # from the id index.
            # ---
            # tree index consistency: All other paths for this id in this tree
            # index must point to the correct path. We have to loop here because
            # we may have passed entries in the state with this file id already
            # that were absent - where parent entries are - and they need to be
            # converted to relocated.
            if path_utf8 is None:
                raise AssertionError('no path')
            for entry_key in id_index.setdefault(key[2], set()):
                # TODO:PROFILING: It might be faster to just update
                # rather than checking if we need to, and then overwrite
                # the one we are located at.
                if entry_key != key:
                    # this file id is at a different path in one of the
                    # other trees, so put absent pointers there
                    # This is the vertical axis in the matrix, all pointing
                    # to the real path.
                    block_index, present = self._find_block_index_from_key(entry_key)
                    if not present:
                        raise AssertionError('not present: %r', entry_key)
                    entry_index, present = self._find_entry_index(entry_key, self._dirblocks[block_index][1])
                    if not present:
                        raise AssertionError('not present: %r', entry_key)
                    self._dirblocks[block_index][1][entry_index][1][0] = \
                        ('r', path_utf8, 0, False, '')
        # add a containing dirblock if needed.
        if new_details[0] == 'd':
            subdir_key = (osutils.pathjoin(*key[0:2]), '', '')
            block_index, present = self._find_block_index_from_key(subdir_key)
            if not present:
                self._dirblocks.insert(block_index, (subdir_key[0], []))

        self._dirblock_state = DirState.IN_MEMORY_MODIFIED

    def _validate(self):
        """Check that invariants on the dirblock are correct.

        This can be useful in debugging; it shouldn't be necessary in 
        normal code.

        This must be called with a lock held.
        """
        # NOTE: This must always raise AssertionError not just assert,
        # otherwise it may not behave properly under python -O
        #
        # TODO: All entries must have some content that's not 'a' or 'r',
        # otherwise it could just be removed.
        #
        # TODO: All relocations must point directly to a real entry.
        #
        # TODO: No repeated keys.
        #
        # -- mbp 20070325
        from pprint import pformat
        self._read_dirblocks_if_needed()
        if len(self._dirblocks) > 0:
            if not self._dirblocks[0][0] == '':
                raise AssertionError(
                    "dirblocks don't start with root block:\n" + \
                    pformat(self._dirblocks))
        if len(self._dirblocks) > 1:
            if not self._dirblocks[1][0] == '':
                raise AssertionError(
                    "dirblocks missing root directory:\n" + \
                    pformat(self._dirblocks))
        # the dirblocks are sorted by their path components, name, and dir id
        dir_names = [d[0].split('/')
                for d in self._dirblocks[1:]]
        if dir_names != sorted(dir_names):
            raise AssertionError(
                "dir names are not in sorted order:\n" + \
                pformat(self._dirblocks) + \
                "\nkeys:\n" +
                pformat(dir_names))
        for dirblock in self._dirblocks:
            # within each dirblock, the entries are sorted by filename and
            # then by id.
            for entry in dirblock[1]:
                if dirblock[0] != entry[0][0]:
                    raise AssertionError(
                        "entry key for %r"
                        "doesn't match directory name in\n%r" %
                        (entry, pformat(dirblock)))
            if dirblock[1] != sorted(dirblock[1]):
                raise AssertionError(
                    "dirblock for %r is not sorted:\n%s" % \
                    (dirblock[0], pformat(dirblock)))

        def check_valid_parent():
            """Check that the current entry has a valid parent.

            This makes sure that the parent has a record,
            and that the parent isn't marked as "absent" in the
            current tree. (It is invalid to have a non-absent file in an absent
            directory.)
            """
            if entry[0][0:2] == ('', ''):
                # There should be no parent for the root row
                return
            parent_entry = self._get_entry(tree_index, path_utf8=entry[0][0])
            if parent_entry == (None, None):
                raise AssertionError(
                    "no parent entry for: %s in tree %s"
                    % (this_path, tree_index))
            if parent_entry[1][tree_index][0] != 'd':
                raise AssertionError(
                    "Parent entry for %s is not marked as a valid"
                    " directory. %s" % (this_path, parent_entry,))

        # For each file id, for each tree: either
        # the file id is not present at all; all rows with that id in the
        # key have it marked as 'absent'
        # OR the file id is present under exactly one name; any other entries 
        # that mention that id point to the correct name.
        #
        # We check this with a dict per tree pointing either to the present
        # name, or None if absent.
        tree_count = self._num_present_parents() + 1
        id_path_maps = [dict() for i in range(tree_count)]
        # Make sure that all renamed entries point to the correct location.
        for entry in self._iter_entries():
            file_id = entry[0][2]
            this_path = osutils.pathjoin(entry[0][0], entry[0][1])
            if len(entry[1]) != tree_count:
                raise AssertionError(
                "wrong number of entry details for row\n%s" \
                ",\nexpected %d" % \
                (pformat(entry), tree_count))
            absent_positions = 0
            for tree_index, tree_state in enumerate(entry[1]):
                this_tree_map = id_path_maps[tree_index]
                minikind = tree_state[0]
                if minikind in 'ar':
                    absent_positions += 1
                # have we seen this id before in this column?
                if file_id in this_tree_map:
                    previous_path, previous_loc = this_tree_map[file_id]
                    # any later mention of this file must be consistent with
                    # what was said before
                    if minikind == 'a':
                        if previous_path is not None:
                            raise AssertionError(
                            "file %s is absent in row %r but also present " \
                            "at %r"% \
                            (file_id, entry, previous_path))
                    elif minikind == 'r':
                        target_location = tree_state[1]
                        if previous_path != target_location:
                            raise AssertionError(
                            "file %s relocation in row %r but also at %r" \
                            % (file_id, entry, previous_path))
                    else:
                        # a file, directory, etc - may have been previously
                        # pointed to by a relocation, which must point here
                        if previous_path != this_path:
                            raise AssertionError(
                                "entry %r inconsistent with previous path %r "
                                "seen at %r" %
                                (entry, previous_path, previous_loc))
                        check_valid_parent()
                else:
                    if minikind == 'a':
                        # absent; should not occur anywhere else
                        this_tree_map[file_id] = None, this_path
                    elif minikind == 'r':
                        # relocation, must occur at expected location 
                        this_tree_map[file_id] = tree_state[1], this_path
                    else:
                        this_tree_map[file_id] = this_path, this_path
                        check_valid_parent()
            if absent_positions == tree_count:
                raise AssertionError(
                    "entry %r has no data for any tree." % (entry,))

    def _wipe_state(self):
        """Forget all state information about the dirstate."""
        self._header_state = DirState.NOT_IN_MEMORY
        self._dirblock_state = DirState.NOT_IN_MEMORY
        self._changes_aborted = False
        self._parents = []
        self._ghosts = []
        self._dirblocks = []
        self._id_index = None
        self._packed_stat_index = None
        self._end_of_header = None
        self._cutoff_time = None
        self._split_path_cache = {}

    def lock_read(self):
        """Acquire a read lock on the dirstate."""
        if self._lock_token is not None:
            raise errors.LockContention(self._lock_token)
        # TODO: jam 20070301 Rather than wiping completely, if the blocks are
        #       already in memory, we could read just the header and check for
        #       any modification. If not modified, we can just leave things
        #       alone
        self._lock_token = lock.ReadLock(self._filename)
        self._lock_state = 'r'
        self._state_file = self._lock_token.f
        self._wipe_state()

    def lock_write(self):
        """Acquire a write lock on the dirstate."""
        if self._lock_token is not None:
            raise errors.LockContention(self._lock_token)
        # TODO: jam 20070301 Rather than wiping completely, if the blocks are
        #       already in memory, we could read just the header and check for
        #       any modification. If not modified, we can just leave things
        #       alone
        self._lock_token = lock.WriteLock(self._filename)
        self._lock_state = 'w'
        self._state_file = self._lock_token.f
        self._wipe_state()

    def unlock(self):
        """Drop any locks held on the dirstate."""
        if self._lock_token is None:
            raise errors.LockNotHeld(self)
        # TODO: jam 20070301 Rather than wiping completely, if the blocks are
        #       already in memory, we could read just the header and check for
        #       any modification. If not modified, we can just leave things
        #       alone
        self._state_file = None
        self._lock_state = None
        self._lock_token.unlock()
        self._lock_token = None
        self._split_path_cache = {}

    def _requires_lock(self):
        """Check that a lock is currently held by someone on the dirstate."""
        if not self._lock_token:
            raise errors.ObjectNotLocked(self)


def py_update_entry(state, entry, abspath, stat_value,
                 _stat_to_minikind=DirState._stat_to_minikind,
                 _pack_stat=pack_stat):
    """Update the entry based on what is actually on disk.

    This function only calculates the sha if it needs to - if the entry is
    uncachable, or clearly different to the first parent's entry, no sha
    is calculated, and None is returned.

    :param state: The dirstate this entry is in.
    :param entry: This is the dirblock entry for the file in question.
    :param abspath: The path on disk for this file.
    :param stat_value: The stat value done on the path.
    :return: None, or The sha1 hexdigest of the file (40 bytes) or link
        target of a symlink.
    """
    try:
        minikind = _stat_to_minikind[stat_value.st_mode & 0170000]
    except KeyError:
        # Unhandled kind
        return None
    packed_stat = _pack_stat(stat_value)
    (saved_minikind, saved_link_or_sha1, saved_file_size,
     saved_executable, saved_packed_stat) = entry[1][0]

    if (minikind == saved_minikind
        and packed_stat == saved_packed_stat):
        # The stat hasn't changed since we saved, so we can re-use the
        # saved sha hash.
        if minikind == 'd':
            return None

        # size should also be in packed_stat
        if saved_file_size == stat_value.st_size:
            return saved_link_or_sha1

    # If we have gotten this far, that means that we need to actually
    # process this entry.
    link_or_sha1 = None
    if minikind == 'f':
        executable = state._is_executable(stat_value.st_mode,
                                         saved_executable)
        if state._cutoff_time is None:
            state._sha_cutoff_time()
        if (stat_value.st_mtime < state._cutoff_time
            and stat_value.st_ctime < state._cutoff_time
            and len(entry[1]) > 1
            and entry[1][1][0] != 'a'):
                # Could check for size changes for further optimised
                # avoidance of sha1's. However the most prominent case of
                # over-shaing is during initial add, which this catches.
            link_or_sha1 = state._sha1_file(abspath)
            entry[1][0] = ('f', link_or_sha1, stat_value.st_size,
                           executable, packed_stat)
        else:
            entry[1][0] = ('f', '', stat_value.st_size,
                           executable, DirState.NULLSTAT)
    elif minikind == 'd':
        link_or_sha1 = None
        entry[1][0] = ('d', '', 0, False, packed_stat)
        if saved_minikind != 'd':
            # This changed from something into a directory. Make sure we
            # have a directory block for it. This doesn't happen very
            # often, so this doesn't have to be super fast.
            block_index, entry_index, dir_present, file_present = \
                state._get_block_entry_index(entry[0][0], entry[0][1], 0)
            state._ensure_block(block_index, entry_index,
                               osutils.pathjoin(entry[0][0], entry[0][1]))
    elif minikind == 'l':
        link_or_sha1 = state._read_link(abspath, saved_link_or_sha1)
        if state._cutoff_time is None:
            state._sha_cutoff_time()
        if (stat_value.st_mtime < state._cutoff_time
            and stat_value.st_ctime < state._cutoff_time):
            entry[1][0] = ('l', link_or_sha1, stat_value.st_size,
                           False, packed_stat)
        else:
            entry[1][0] = ('l', '', stat_value.st_size,
                           False, DirState.NULLSTAT)
    state._dirblock_state = DirState.IN_MEMORY_MODIFIED
    return link_or_sha1
update_entry = py_update_entry


class ProcessEntryPython(object):

    __slots__ = ["old_dirname_to_file_id", "new_dirname_to_file_id", "uninteresting",
        "last_source_parent", "last_target_parent", "include_unchanged",
        "use_filesystem_for_exec", "utf8_decode", "searched_specific_files",
        "search_specific_files", "state", "source_index", "target_index",
        "want_unversioned", "tree"]

    def __init__(self, include_unchanged, use_filesystem_for_exec,
        search_specific_files, state, source_index, target_index,
        want_unversioned, tree):
        self.old_dirname_to_file_id = {}
        self.new_dirname_to_file_id = {}
        # Just a sentry, so that _process_entry can say that this
        # record is handled, but isn't interesting to process (unchanged)
        self.uninteresting = object()
        # Using a list so that we can access the values and change them in
        # nested scope. Each one is [path, file_id, entry]
        self.last_source_parent = [None, None]
        self.last_target_parent = [None, None]
        self.include_unchanged = include_unchanged
        self.use_filesystem_for_exec = use_filesystem_for_exec
        self.utf8_decode = cache_utf8._utf8_decode
        # for all search_indexs in each path at or under each element of
        # search_specific_files, if the detail is relocated: add the id, and add the
        # relocated path as one to search if its not searched already. If the
        # detail is not relocated, add the id.
        self.searched_specific_files = set()
        self.search_specific_files = search_specific_files
        self.state = state
        self.source_index = source_index
        self.target_index = target_index
        self.want_unversioned = want_unversioned
        self.tree = tree

    def _process_entry(self, entry, path_info, pathjoin=osutils.pathjoin):
        """Compare an entry and real disk to generate delta information.

        :param path_info: top_relpath, basename, kind, lstat, abspath for
            the path of entry. If None, then the path is considered absent.
            (Perhaps we should pass in a concrete entry for this ?)
            Basename is returned as a utf8 string because we expect this
            tuple will be ignored, and don't want to take the time to
            decode.
        :return: None if these don't match
                 A tuple of information about the change, or
                 the object 'uninteresting' if these match, but are
                 basically identical.
        """
        if self.source_index is None:
            source_details = DirState.NULL_PARENT_DETAILS
        else:
            source_details = entry[1][self.source_index]
        target_details = entry[1][self.target_index]
        target_minikind = target_details[0]
        if path_info is not None and target_minikind in 'fdlt':
            if not (self.target_index == 0):
                raise AssertionError()
            link_or_sha1 = update_entry(self.state, entry,
                abspath=path_info[4], stat_value=path_info[3])
            # The entry may have been modified by update_entry
            target_details = entry[1][self.target_index]
            target_minikind = target_details[0]
        else:
            link_or_sha1 = None
        file_id = entry[0][2]
        source_minikind = source_details[0]
        if source_minikind in 'fdltr' and target_minikind in 'fdlt':
            # claimed content in both: diff
            #   r    | fdlt   |      | add source to search, add id path move and perform
            #        |        |      | diff check on source-target
            #   r    | fdlt   |  a   | dangling file that was present in the basis.
            #        |        |      | ???
            if source_minikind in 'r':
                # add the source to the search path to find any children it
                # has.  TODO ? : only add if it is a container ?
                if not osutils.is_inside_any(self.searched_specific_files,
                                             source_details[1]):
                    self.search_specific_files.add(source_details[1])
                # generate the old path; this is needed for stating later
                # as well.
                old_path = source_details[1]
                old_dirname, old_basename = os.path.split(old_path)
                path = pathjoin(entry[0][0], entry[0][1])
                old_entry = self.state._get_entry(self.source_index,
                                             path_utf8=old_path)
                # update the source details variable to be the real
                # location.
                if old_entry == (None, None):
                    raise errors.CorruptDirstate(self.state._filename,
                        "entry '%s/%s' is considered renamed from %r"
                        " but source does not exist\n"
                        "entry: %s" % (entry[0][0], entry[0][1], old_path, entry))
                source_details = old_entry[1][self.source_index]
                source_minikind = source_details[0]
            else:
                old_dirname = entry[0][0]
                old_basename = entry[0][1]
                old_path = path = None
            if path_info is None:
                # the file is missing on disk, show as removed.
                content_change = True
                target_kind = None
                target_exec = False
            else:
                # source and target are both versioned and disk file is present.
                target_kind = path_info[2]
                if target_kind == 'directory':
                    if path is None:
                        old_path = path = pathjoin(old_dirname, old_basename)
                    self.new_dirname_to_file_id[path] = file_id
                    if source_minikind != 'd':
                        content_change = True
                    else:
                        # directories have no fingerprint
                        content_change = False
                    target_exec = False
                elif target_kind == 'file':
                    if source_minikind != 'f':
                        content_change = True
                    else:
                        # If the size is the same, check the sha:
                        if target_details[2] == source_details[2]:
                            if link_or_sha1 is None:
                                # Stat cache miss:
                                file_obj = file(path_info[4], 'rb')
                                try:
                                    statvalue = os.fstat(file_obj.fileno())
                                    link_or_sha1 = osutils.sha_file(file_obj)
                                finally:
                                    file_obj.close()
                                self.state._observed_sha1(entry, link_or_sha1,
                                    statvalue)
                            content_change = (link_or_sha1 != source_details[1])
                        else:
                            # Size changed, so must be different
                            content_change = True
                    # Target details is updated at update_entry time
                    if self.use_filesystem_for_exec:
                        # We don't need S_ISREG here, because we are sure
                        # we are dealing with a file.
                        target_exec = bool(stat.S_IEXEC & path_info[3].st_mode)
                    else:
                        target_exec = target_details[3]
                elif target_kind == 'symlink':
                    if source_minikind != 'l':
                        content_change = True
                    else:
                        content_change = (link_or_sha1 != source_details[1])
                    target_exec = False
                elif target_kind == 'tree-reference':
                    if source_minikind != 't':
                        content_change = True
                    else:
                        content_change = False
                    target_exec = False
                else:
                    raise Exception, "unknown kind %s" % path_info[2]
            if source_minikind == 'd':
                if path is None:
                    old_path = path = pathjoin(old_dirname, old_basename)
                self.old_dirname_to_file_id[old_path] = file_id
            # parent id is the entry for the path in the target tree
            if old_dirname == self.last_source_parent[0]:
                source_parent_id = self.last_source_parent[1]
            else:
                try:
                    source_parent_id = self.old_dirname_to_file_id[old_dirname]
                except KeyError:
                    source_parent_entry = self.state._get_entry(self.source_index,
                                                           path_utf8=old_dirname)
                    source_parent_id = source_parent_entry[0][2]
                if source_parent_id == entry[0][2]:
                    # This is the root, so the parent is None
                    source_parent_id = None
                else:
                    self.last_source_parent[0] = old_dirname
                    self.last_source_parent[1] = source_parent_id
            new_dirname = entry[0][0]
            if new_dirname == self.last_target_parent[0]:
                target_parent_id = self.last_target_parent[1]
            else:
                try:
                    target_parent_id = self.new_dirname_to_file_id[new_dirname]
                except KeyError:
                    # TODO: We don't always need to do the lookup, because the
                    #       parent entry will be the same as the source entry.
                    target_parent_entry = self.state._get_entry(self.target_index,
                                                           path_utf8=new_dirname)
                    if target_parent_entry == (None, None):
                        raise AssertionError(
                            "Could not find target parent in wt: %s\nparent of: %s"
                            % (new_dirname, entry))
                    target_parent_id = target_parent_entry[0][2]
                if target_parent_id == entry[0][2]:
                    # This is the root, so the parent is None
                    target_parent_id = None
                else:
                    self.last_target_parent[0] = new_dirname
                    self.last_target_parent[1] = target_parent_id

            source_exec = source_details[3]
            if (self.include_unchanged
                or content_change
                or source_parent_id != target_parent_id
                or old_basename != entry[0][1]
                or source_exec != target_exec
                ):
                if old_path is None:
                    old_path = path = pathjoin(old_dirname, old_basename)
                    old_path_u = self.utf8_decode(old_path)[0]
                    path_u = old_path_u
                else:
                    old_path_u = self.utf8_decode(old_path)[0]
                    if old_path == path:
                        path_u = old_path_u
                    else:
                        path_u = self.utf8_decode(path)[0]
                source_kind = DirState._minikind_to_kind[source_minikind]
                return (entry[0][2],
                       (old_path_u, path_u),
                       content_change,
                       (True, True),
                       (source_parent_id, target_parent_id),
                       (self.utf8_decode(old_basename)[0], self.utf8_decode(entry[0][1])[0]),
                       (source_kind, target_kind),
                       (source_exec, target_exec))
            else:
                return self.uninteresting
        elif source_minikind in 'a' and target_minikind in 'fdlt':
            # looks like a new file
            path = pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            # TODO: these are the same for an entire directory: cache em.
            parent_id = self.state._get_entry(self.target_index,
                                         path_utf8=entry[0][0])[0][2]
            if parent_id == entry[0][2]:
                parent_id = None
            if path_info is not None:
                # Present on disk:
                if self.use_filesystem_for_exec:
                    # We need S_ISREG here, because we aren't sure if this
                    # is a file or not.
                    target_exec = bool(
                        stat.S_ISREG(path_info[3].st_mode)
                        and stat.S_IEXEC & path_info[3].st_mode)
                else:
                    target_exec = target_details[3]
                return (entry[0][2],
                       (None, self.utf8_decode(path)[0]),
                       True,
                       (False, True),
                       (None, parent_id),
                       (None, self.utf8_decode(entry[0][1])[0]),
                       (None, path_info[2]),
                       (None, target_exec))
            else:
                # Its a missing file, report it as such.
                return (entry[0][2],
                       (None, self.utf8_decode(path)[0]),
                       False,
                       (False, True),
                       (None, parent_id),
                       (None, self.utf8_decode(entry[0][1])[0]),
                       (None, None),
                       (None, False))
        elif source_minikind in 'fdlt' and target_minikind in 'a':
            # unversioned, possibly, or possibly not deleted: we dont care.
            # if its still on disk, *and* theres no other entry at this
            # path [we dont know this in this routine at the moment -
            # perhaps we should change this - then it would be an unknown.
            old_path = pathjoin(entry[0][0], entry[0][1])
            # parent id is the entry for the path in the target tree
            parent_id = self.state._get_entry(self.source_index, path_utf8=entry[0][0])[0][2]
            if parent_id == entry[0][2]:
                parent_id = None
            return (entry[0][2],
                   (self.utf8_decode(old_path)[0], None),
                   True,
                   (True, False),
                   (parent_id, None),
                   (self.utf8_decode(entry[0][1])[0], None),
                   (DirState._minikind_to_kind[source_minikind], None),
                   (source_details[3], None))
        elif source_minikind in 'fdlt' and target_minikind in 'r':
            # a rename; could be a true rename, or a rename inherited from
            # a renamed parent. TODO: handle this efficiently. Its not
            # common case to rename dirs though, so a correct but slow
            # implementation will do.
            if not osutils.is_inside_any(self.searched_specific_files, target_details[1]):
                self.search_specific_files.add(target_details[1])
        elif source_minikind in 'ra' and target_minikind in 'ra':
            # neither of the selected trees contain this file,
            # so skip over it. This is not currently directly tested, but
            # is indirectly via test_too_much.TestCommands.test_conflicts.
            pass
        else:
            raise AssertionError("don't know how to compare "
                "source_minikind=%r, target_minikind=%r"
                % (source_minikind, target_minikind))
            ## import pdb;pdb.set_trace()
        return None

    def __iter__(self):
        return self

    def iter_changes(self):
        """Iterate over the changes."""
        utf8_decode = cache_utf8._utf8_decode
        _cmp_by_dirs = cmp_by_dirs
        _process_entry = self._process_entry
        uninteresting = self.uninteresting
        search_specific_files = self.search_specific_files
        searched_specific_files = self.searched_specific_files
        splitpath = osutils.splitpath
        # sketch: 
        # compare source_index and target_index at or under each element of search_specific_files.
        # follow the following comparison table. Note that we only want to do diff operations when
        # the target is fdl because thats when the walkdirs logic will have exposed the pathinfo 
        # for the target.
        # cases:
        # 
        # Source | Target | disk | action
        #   r    | fdlt   |      | add source to search, add id path move and perform
        #        |        |      | diff check on source-target
        #   r    | fdlt   |  a   | dangling file that was present in the basis. 
        #        |        |      | ???
        #   r    |  a     |      | add source to search
        #   r    |  a     |  a   | 
        #   r    |  r     |      | this path is present in a non-examined tree, skip.
        #   r    |  r     |  a   | this path is present in a non-examined tree, skip.
        #   a    | fdlt   |      | add new id
        #   a    | fdlt   |  a   | dangling locally added file, skip
        #   a    |  a     |      | not present in either tree, skip
        #   a    |  a     |  a   | not present in any tree, skip
        #   a    |  r     |      | not present in either tree at this path, skip as it
        #        |        |      | may not be selected by the users list of paths.
        #   a    |  r     |  a   | not present in either tree at this path, skip as it
        #        |        |      | may not be selected by the users list of paths.
        #  fdlt  | fdlt   |      | content in both: diff them
        #  fdlt  | fdlt   |  a   | deleted locally, but not unversioned - show as deleted ?
        #  fdlt  |  a     |      | unversioned: output deleted id for now
        #  fdlt  |  a     |  a   | unversioned and deleted: output deleted id
        #  fdlt  |  r     |      | relocated in this tree, so add target to search.
        #        |        |      | Dont diff, we will see an r,fd; pair when we reach
        #        |        |      | this id at the other path.
        #  fdlt  |  r     |  a   | relocated in this tree, so add target to search.
        #        |        |      | Dont diff, we will see an r,fd; pair when we reach
        #        |        |      | this id at the other path.

        # TODO: jam 20070516 - Avoid the _get_entry lookup overhead by
        #       keeping a cache of directories that we have seen.

        while search_specific_files:
            # TODO: the pending list should be lexically sorted?  the
            # interface doesn't require it.
            current_root = search_specific_files.pop()
            current_root_unicode = current_root.decode('utf8')
            searched_specific_files.add(current_root)
            # process the entries for this containing directory: the rest will be
            # found by their parents recursively.
            root_entries = self.state._entries_for_path(current_root)
            root_abspath = self.tree.abspath(current_root_unicode)
            try:
                root_stat = os.lstat(root_abspath)
            except OSError, e:
                if e.errno == errno.ENOENT:
                    # the path does not exist: let _process_entry know that.
                    root_dir_info = None
                else:
                    # some other random error: hand it up.
                    raise
            else:
                root_dir_info = ('', current_root,
                    osutils.file_kind_from_stat_mode(root_stat.st_mode), root_stat,
                    root_abspath)
                if root_dir_info[2] == 'directory':
                    if self.tree._directory_is_tree_reference(
                        current_root.decode('utf8')):
                        root_dir_info = root_dir_info[:2] + \
                            ('tree-reference',) + root_dir_info[3:]

            if not root_entries and not root_dir_info:
                # this specified path is not present at all, skip it.
                continue
            path_handled = False
            for entry in root_entries:
                result = _process_entry(entry, root_dir_info)
                if result is not None:
                    path_handled = True
                    if result is not uninteresting:
                        yield result
            if self.want_unversioned and not path_handled and root_dir_info:
                new_executable = bool(
                    stat.S_ISREG(root_dir_info[3].st_mode)
                    and stat.S_IEXEC & root_dir_info[3].st_mode)
                yield (None,
                       (None, current_root_unicode),
                       True,
                       (False, False),
                       (None, None),
                       (None, splitpath(current_root_unicode)[-1]),
                       (None, root_dir_info[2]),
                       (None, new_executable)
                      )
            initial_key = (current_root, '', '')
            block_index, _ = self.state._find_block_index_from_key(initial_key)
            if block_index == 0:
                # we have processed the total root already, but because the
                # initial key matched it we should skip it here.
                block_index +=1
            if root_dir_info and root_dir_info[2] == 'tree-reference':
                current_dir_info = None
            else:
                dir_iterator = osutils._walkdirs_utf8(root_abspath, prefix=current_root)
                try:
                    current_dir_info = dir_iterator.next()
                except OSError, e:
                    # on win32, python2.4 has e.errno == ERROR_DIRECTORY, but
                    # python 2.5 has e.errno == EINVAL,
                    #            and e.winerror == ERROR_DIRECTORY
                    e_winerror = getattr(e, 'winerror', None)
                    win_errors = (ERROR_DIRECTORY, ERROR_PATH_NOT_FOUND)
                    # there may be directories in the inventory even though
                    # this path is not a file on disk: so mark it as end of
                    # iterator
                    if e.errno in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL):
                        current_dir_info = None
                    elif (sys.platform == 'win32'
                          and (e.errno in win_errors
                               or e_winerror in win_errors)):
                        current_dir_info = None
                    else:
                        raise
                else:
                    if current_dir_info[0][0] == '':
                        # remove .bzr from iteration
                        bzr_index = bisect.bisect_left(current_dir_info[1], ('.bzr',))
                        if current_dir_info[1][bzr_index][0] != '.bzr':
                            raise AssertionError()
                        del current_dir_info[1][bzr_index]
            # walk until both the directory listing and the versioned metadata
            # are exhausted. 
            if (block_index < len(self.state._dirblocks) and
                osutils.is_inside(current_root, self.state._dirblocks[block_index][0])):
                current_block = self.state._dirblocks[block_index]
            else:
                current_block = None
            while (current_dir_info is not None or
                   current_block is not None):
                if (current_dir_info and current_block
                    and current_dir_info[0][0] != current_block[0]):
                    if _cmp_by_dirs(current_dir_info[0][0], current_block[0]) < 0:
                        # filesystem data refers to paths not covered by the dirblock.
                        # this has two possibilities:
                        # A) it is versioned but empty, so there is no block for it
                        # B) it is not versioned.

                        # if (A) then we need to recurse into it to check for
                        # new unknown files or directories.
                        # if (B) then we should ignore it, because we don't
                        # recurse into unknown directories.
                        path_index = 0
                        while path_index < len(current_dir_info[1]):
                                current_path_info = current_dir_info[1][path_index]
                                if self.want_unversioned:
                                    if current_path_info[2] == 'directory':
                                        if self.tree._directory_is_tree_reference(
                                            current_path_info[0].decode('utf8')):
                                            current_path_info = current_path_info[:2] + \
                                                ('tree-reference',) + current_path_info[3:]
                                    new_executable = bool(
                                        stat.S_ISREG(current_path_info[3].st_mode)
                                        and stat.S_IEXEC & current_path_info[3].st_mode)
                                    yield (None,
                                        (None, utf8_decode(current_path_info[0])[0]),
                                        True,
                                        (False, False),
                                        (None, None),
                                        (None, utf8_decode(current_path_info[1])[0]),
                                        (None, current_path_info[2]),
                                        (None, new_executable))
                                # dont descend into this unversioned path if it is
                                # a dir
                                if current_path_info[2] in ('directory',
                                                            'tree-reference'):
                                    del current_dir_info[1][path_index]
                                    path_index -= 1
                                path_index += 1

                        # This dir info has been handled, go to the next
                        try:
                            current_dir_info = dir_iterator.next()
                        except StopIteration:
                            current_dir_info = None
                    else:
                        # We have a dirblock entry for this location, but there
                        # is no filesystem path for this. This is most likely
                        # because a directory was removed from the disk.
                        # We don't have to report the missing directory,
                        # because that should have already been handled, but we
                        # need to handle all of the files that are contained
                        # within.
                        for current_entry in current_block[1]:
                            # entry referring to file not present on disk.
                            # advance the entry only, after processing.
                            result = _process_entry(current_entry, None)
                            if result is not None:
                                if result is not uninteresting:
                                    yield result
                        block_index +=1
                        if (block_index < len(self.state._dirblocks) and
                            osutils.is_inside(current_root,
                                              self.state._dirblocks[block_index][0])):
                            current_block = self.state._dirblocks[block_index]
                        else:
                            current_block = None
                    continue
                entry_index = 0
                if current_block and entry_index < len(current_block[1]):
                    current_entry = current_block[1][entry_index]
                else:
                    current_entry = None
                advance_entry = True
                path_index = 0
                if current_dir_info and path_index < len(current_dir_info[1]):
                    current_path_info = current_dir_info[1][path_index]
                    if current_path_info[2] == 'directory':
                        if self.tree._directory_is_tree_reference(
                            current_path_info[0].decode('utf8')):
                            current_path_info = current_path_info[:2] + \
                                ('tree-reference',) + current_path_info[3:]
                else:
                    current_path_info = None
                advance_path = True
                path_handled = False
                while (current_entry is not None or
                    current_path_info is not None):
                    if current_entry is None:
                        # the check for path_handled when the path is adnvaced
                        # will yield this path if needed.
                        pass
                    elif current_path_info is None:
                        # no path is fine: the per entry code will handle it.
                        result = _process_entry(current_entry, current_path_info)
                        if result is not None:
                            if result is not uninteresting:
                                yield result
                    elif (current_entry[0][1] != current_path_info[1]
                          or current_entry[1][self.target_index][0] in 'ar'):
                        # The current path on disk doesn't match the dirblock
                        # record. Either the dirblock is marked as absent, or
                        # the file on disk is not present at all in the
                        # dirblock. Either way, report about the dirblock
                        # entry, and let other code handle the filesystem one.

                        # Compare the basename for these files to determine
                        # which comes first
                        if current_path_info[1] < current_entry[0][1]:
                            # extra file on disk: pass for now, but only
                            # increment the path, not the entry
                            advance_entry = False
                        else:
                            # entry referring to file not present on disk.
                            # advance the entry only, after processing.
                            result = _process_entry(current_entry, None)
                            if result is not None:
                                if result is not uninteresting:
                                    yield result
                            advance_path = False
                    else:
                        result = _process_entry(current_entry, current_path_info)
                        if result is not None:
                            path_handled = True
                            if result is not uninteresting:
                                yield result
                    if advance_entry and current_entry is not None:
                        entry_index += 1
                        if entry_index < len(current_block[1]):
                            current_entry = current_block[1][entry_index]
                        else:
                            current_entry = None
                    else:
                        advance_entry = True # reset the advance flaga
                    if advance_path and current_path_info is not None:
                        if not path_handled:
                            # unversioned in all regards
                            if self.want_unversioned:
                                new_executable = bool(
                                    stat.S_ISREG(current_path_info[3].st_mode)
                                    and stat.S_IEXEC & current_path_info[3].st_mode)
                                try:
                                    relpath_unicode = utf8_decode(current_path_info[0])[0]
                                except UnicodeDecodeError:
                                    raise errors.BadFilenameEncoding(
                                        current_path_info[0], osutils._fs_enc)
                                yield (None,
                                    (None, relpath_unicode),
                                    True,
                                    (False, False),
                                    (None, None),
                                    (None, utf8_decode(current_path_info[1])[0]),
                                    (None, current_path_info[2]),
                                    (None, new_executable))
                            # dont descend into this unversioned path if it is
                            # a dir
                            if current_path_info[2] in ('directory'):
                                del current_dir_info[1][path_index]
                                path_index -= 1
                        # dont descend the disk iterator into any tree 
                        # paths.
                        if current_path_info[2] == 'tree-reference':
                            del current_dir_info[1][path_index]
                            path_index -= 1
                        path_index += 1
                        if path_index < len(current_dir_info[1]):
                            current_path_info = current_dir_info[1][path_index]
                            if current_path_info[2] == 'directory':
                                if self.tree._directory_is_tree_reference(
                                    current_path_info[0].decode('utf8')):
                                    current_path_info = current_path_info[:2] + \
                                        ('tree-reference',) + current_path_info[3:]
                        else:
                            current_path_info = None
                        path_handled = False
                    else:
                        advance_path = True # reset the advance flagg.
                if current_block is not None:
                    block_index += 1
                    if (block_index < len(self.state._dirblocks) and
                        osutils.is_inside(current_root, self.state._dirblocks[block_index][0])):
                        current_block = self.state._dirblocks[block_index]
                    else:
                        current_block = None
                if current_dir_info is not None:
                    try:
                        current_dir_info = dir_iterator.next()
                    except StopIteration:
                        current_dir_info = None
_process_entry = ProcessEntryPython


# Try to load the compiled form if possible
try:
    from bzrlib._dirstate_helpers_c import (
        _read_dirblocks_c as _read_dirblocks,
        bisect_dirblock_c as bisect_dirblock,
        _bisect_path_left_c as _bisect_path_left,
        _bisect_path_right_c as _bisect_path_right,
        cmp_by_dirs_c as cmp_by_dirs,
        ProcessEntryC as _process_entry,
        update_entry as update_entry,
        )
except ImportError:
    from bzrlib._dirstate_helpers_py import (
        _read_dirblocks_py as _read_dirblocks,
        bisect_dirblock_py as bisect_dirblock,
        _bisect_path_left_py as _bisect_path_left,
        _bisect_path_right_py as _bisect_path_right,
        cmp_by_dirs_py as cmp_by_dirs,
        )
