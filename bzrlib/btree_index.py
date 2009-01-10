# Copyright (C) 2008 Canonical Ltd
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
#

"""B+Tree indices"""

import array
import bisect
from bisect import bisect_right
from copy import deepcopy
import math
import struct
import tempfile
import zlib

from bzrlib import (
    chunk_writer,
    debug,
    errors,
    index,
    lru_cache,
    osutils,
    trace,
    )
from bzrlib.index import _OPTION_NODE_REFS, _OPTION_KEY_ELEMENTS, _OPTION_LEN
from bzrlib.transport import get_transport


_BTSIGNATURE = "B+Tree Graph Index 2\n"
_OPTION_ROW_LENGTHS = "row_lengths="
_LEAF_FLAG = "type=leaf\n"
_INTERNAL_FLAG = "type=internal\n"
_INTERNAL_OFFSET = "offset="

_RESERVED_HEADER_BYTES = 120
_PAGE_SIZE = 4096

# 4K per page: 4MB - 1000 entries
_NODE_CACHE_SIZE = 1000


class _BuilderRow(object):
    """The stored state accumulated while writing out a row in the index.

    :ivar spool: A temporary file used to accumulate nodes for this row
        in the tree.
    :ivar nodes: The count of nodes emitted so far.
    """

    def __init__(self):
        """Create a _BuilderRow."""
        self.nodes = 0
        self.spool = tempfile.TemporaryFile()
        self.writer = None

    def finish_node(self, pad=True):
        byte_lines, _, padding = self.writer.finish()
        if self.nodes == 0:
            # padded note:
            self.spool.write("\x00" * _RESERVED_HEADER_BYTES)
        skipped_bytes = 0
        if not pad and padding:
            del byte_lines[-1]
            skipped_bytes = padding
        self.spool.writelines(byte_lines)
        remainder = (self.spool.tell() + skipped_bytes) % _PAGE_SIZE
        if remainder != 0:
            raise AssertionError("incorrect node length: %d, %d"
                                 % (self.spool.tell(), remainder))
        self.nodes += 1
        self.writer = None


class _InternalBuilderRow(_BuilderRow):
    """The stored state accumulated while writing out internal rows."""

    def finish_node(self, pad=True):
        if not pad:
            raise AssertionError("Must pad internal nodes only.")
        _BuilderRow.finish_node(self)


class _LeafBuilderRow(_BuilderRow):
    """The stored state accumulated while writing out a leaf rows."""


class BTreeBuilder(index.GraphIndexBuilder):
    """A Builder for B+Tree based Graph indices.

    The resulting graph has the structure:

    _SIGNATURE OPTIONS NODES
    _SIGNATURE     := 'B+Tree Graph Index 1' NEWLINE
    OPTIONS        := REF_LISTS KEY_ELEMENTS LENGTH
    REF_LISTS      := 'node_ref_lists=' DIGITS NEWLINE
    KEY_ELEMENTS   := 'key_elements=' DIGITS NEWLINE
    LENGTH         := 'len=' DIGITS NEWLINE
    ROW_LENGTHS    := 'row_lengths' DIGITS (COMMA DIGITS)*
    NODES          := NODE_COMPRESSED*
    NODE_COMPRESSED:= COMPRESSED_BYTES{4096}
    NODE_RAW       := INTERNAL | LEAF
    INTERNAL       := INTERNAL_FLAG POINTERS
    LEAF           := LEAF_FLAG ROWS
    KEY_ELEMENT    := Not-whitespace-utf8
    KEY            := KEY_ELEMENT (NULL KEY_ELEMENT)*
    ROWS           := ROW*
    ROW            := KEY NULL ABSENT? NULL REFERENCES NULL VALUE NEWLINE
    ABSENT         := 'a'
    REFERENCES     := REFERENCE_LIST (TAB REFERENCE_LIST){node_ref_lists - 1}
    REFERENCE_LIST := (REFERENCE (CR REFERENCE)*)?
    REFERENCE      := KEY
    VALUE          := no-newline-no-null-bytes
    """

    def __init__(self, reference_lists=0, key_elements=1, spill_at=100000):
        """See GraphIndexBuilder.__init__.

        :param spill_at: Optional parameter controlling the maximum number
            of nodes that BTreeBuilder will hold in memory.
        """
        index.GraphIndexBuilder.__init__(self, reference_lists=reference_lists,
            key_elements=key_elements)
        self._spill_at = spill_at
        self._backing_indices = []
        # A map of {key: (node_refs, value)}
        self._nodes = {}
        # Indicate it hasn't been built yet
        self._nodes_by_key = None
        self._optimize_for_size = False

    def add_node(self, key, value, references=()):
        """Add a node to the index.

        If adding the node causes the builder to reach its spill_at threshold,
        disk spilling will be triggered.

        :param key: The key. keys are non-empty tuples containing
            as many whitespace-free utf8 bytestrings as the key length
            defined for this index.
        :param references: An iterable of iterables of keys. Each is a
            reference to another key.
        :param value: The value to associate with the key. It may be any
            bytes as long as it does not contain \0 or \n.
        """
        # we don't care about absent_references
        node_refs, _ = self._check_key_ref_value(key, references, value)
        if key in self._nodes:
            raise errors.BadIndexDuplicateKey(key, self)
        self._nodes[key] = (node_refs, value)
        self._keys.add(key)
        if self._nodes_by_key is not None and self._key_length > 1:
            self._update_nodes_by_key(key, value, node_refs)
        if len(self._keys) < self._spill_at:
            return
        self._spill_mem_keys_to_disk()

    def _spill_mem_keys_to_disk(self):
        """Write the in memory keys down to disk to cap memory consumption.

        If we already have some keys written to disk, we will combine them so
        as to preserve the sorted order.  The algorithm for combining uses
        powers of two.  So on the first spill, write all mem nodes into a
        single index. On the second spill, combine the mem nodes with the nodes
        on disk to create a 2x sized disk index and get rid of the first index.
        On the third spill, create a single new disk index, which will contain
        the mem nodes, and preserve the existing 2x sized index.  On the fourth,
        combine mem with the first and second indexes, creating a new one of
        size 4x. On the fifth create a single new one, etc.
        """
        iterators_to_combine = [self._iter_mem_nodes()]
        pos = -1
        for pos, backing in enumerate(self._backing_indices):
            if backing is None:
                pos -= 1
                break
            iterators_to_combine.append(backing.iter_all_entries())
        backing_pos = pos + 1
        new_backing_file, size = \
            self._write_nodes(self._iter_smallest(iterators_to_combine))
        dir_path, base_name = osutils.split(new_backing_file.name)
        # Note: The transport here isn't strictly needed, because we will use
        #       direct access to the new_backing._file object
        new_backing = BTreeGraphIndex(get_transport(dir_path),
                                      base_name, size)
        # GC will clean up the file
        new_backing._file = new_backing_file
        if len(self._backing_indices) == backing_pos:
            self._backing_indices.append(None)
        self._backing_indices[backing_pos] = new_backing
        for pos in range(backing_pos):
            self._backing_indices[pos] = None
        self._keys = set()
        self._nodes = {}
        self._nodes_by_key = None

    def add_nodes(self, nodes):
        """Add nodes to the index.

        :param nodes: An iterable of (key, node_refs, value) entries to add.
        """
        if self.reference_lists:
            for (key, value, node_refs) in nodes:
                self.add_node(key, value, node_refs)
        else:
            for (key, value) in nodes:
                self.add_node(key, value)

    def _iter_mem_nodes(self):
        """Iterate over the nodes held in memory."""
        nodes = self._nodes
        if self.reference_lists:
            for key in sorted(nodes):
                references, value = nodes[key]
                yield self, key, value, references
        else:
            for key in sorted(nodes):
                references, value = nodes[key]
                yield self, key, value

    def _iter_smallest(self, iterators_to_combine):
        if len(iterators_to_combine) == 1:
            for value in iterators_to_combine[0]:
                yield value
            return
        current_values = []
        for iterator in iterators_to_combine:
            try:
                current_values.append(iterator.next())
            except StopIteration:
                current_values.append(None)
        last = None
        while True:
            # Decorate candidates with the value to allow 2.4's min to be used.
            candidates = [(item[1][1], item) for item
                in enumerate(current_values) if item[1] is not None]
            if not len(candidates):
                return
            selected = min(candidates)
            # undecorate back to (pos, node)
            selected = selected[1]
            if last == selected[1][1]:
                raise errors.BadIndexDuplicateKey(last, self)
            last = selected[1][1]
            # Yield, with self as the index
            yield (self,) + selected[1][1:]
            pos = selected[0]
            try:
                current_values[pos] = iterators_to_combine[pos].next()
            except StopIteration:
                current_values[pos] = None

    def _add_key(self, string_key, line, rows):
        """Add a key to the current chunk.

        :param string_key: The key to add.
        :param line: The fully serialised key and value.
        """
        if rows[-1].writer is None:
            # opening a new leaf chunk;
            for pos, internal_row in enumerate(rows[:-1]):
                # flesh out any internal nodes that are needed to
                # preserve the height of the tree
                if internal_row.writer is None:
                    length = _PAGE_SIZE
                    if internal_row.nodes == 0:
                        length -= _RESERVED_HEADER_BYTES # padded
                    internal_row.writer = chunk_writer.ChunkWriter(length, 0,
                        optimize_for_size=self._optimize_for_size)
                    internal_row.writer.write(_INTERNAL_FLAG)
                    internal_row.writer.write(_INTERNAL_OFFSET +
                        str(rows[pos + 1].nodes) + "\n")
            # add a new leaf
            length = _PAGE_SIZE
            if rows[-1].nodes == 0:
                length -= _RESERVED_HEADER_BYTES # padded
            rows[-1].writer = chunk_writer.ChunkWriter(length,
                optimize_for_size=self._optimize_for_size)
            rows[-1].writer.write(_LEAF_FLAG)
        if rows[-1].writer.write(line):
            # this key did not fit in the node:
            rows[-1].finish_node()
            key_line = string_key + "\n"
            new_row = True
            for row in reversed(rows[:-1]):
                # Mark the start of the next node in the node above. If it
                # doesn't fit then propogate upwards until we find one that
                # it does fit into.
                if row.writer.write(key_line):
                    row.finish_node()
                else:
                    # We've found a node that can handle the pointer.
                    new_row = False
                    break
            # If we reached the current root without being able to mark the
            # division point, then we need a new root:
            if new_row:
                # We need a new row
                if 'index' in debug.debug_flags:
                    trace.mutter('Inserting new global row.')
                new_row = _InternalBuilderRow()
                reserved_bytes = 0
                rows.insert(0, new_row)
                # This will be padded, hence the -100
                new_row.writer = chunk_writer.ChunkWriter(
                    _PAGE_SIZE - _RESERVED_HEADER_BYTES,
                    reserved_bytes,
                    optimize_for_size=self._optimize_for_size)
                new_row.writer.write(_INTERNAL_FLAG)
                new_row.writer.write(_INTERNAL_OFFSET +
                    str(rows[1].nodes - 1) + "\n")
                new_row.writer.write(key_line)
            self._add_key(string_key, line, rows)

    def _write_nodes(self, node_iterator):
        """Write node_iterator out as a B+Tree.

        :param node_iterator: An iterator of sorted nodes. Each node should
            match the output given by iter_all_entries.
        :return: A file handle for a temporary file containing a B+Tree for
            the nodes.
        """
        # The index rows - rows[0] is the root, rows[1] is the layer under it
        # etc.
        rows = []
        # forward sorted by key. In future we may consider topological sorting,
        # at the cost of table scans for direct lookup, or a second index for
        # direct lookup
        key_count = 0
        # A stack with the number of nodes of each size. 0 is the root node
        # and must always be 1 (if there are any nodes in the tree).
        self.row_lengths = []
        # Loop over all nodes adding them to the bottom row
        # (rows[-1]). When we finish a chunk in a row,
        # propogate the key that didn't fit (comes after the chunk) to the
        # row above, transitively.
        for node in node_iterator:
            if key_count == 0:
                # First key triggers the first row
                rows.append(_LeafBuilderRow())
            key_count += 1
            string_key, line = _btree_serializer._flatten_node(node,
                                    self.reference_lists)
            self._add_key(string_key, line, rows)
        for row in reversed(rows):
            pad = (type(row) != _LeafBuilderRow)
            row.finish_node(pad=pad)
        result = tempfile.NamedTemporaryFile()
        lines = [_BTSIGNATURE]
        lines.append(_OPTION_NODE_REFS + str(self.reference_lists) + '\n')
        lines.append(_OPTION_KEY_ELEMENTS + str(self._key_length) + '\n')
        lines.append(_OPTION_LEN + str(key_count) + '\n')
        row_lengths = [row.nodes for row in rows]
        lines.append(_OPTION_ROW_LENGTHS + ','.join(map(str, row_lengths)) + '\n')
        result.writelines(lines)
        position = sum(map(len, lines))
        root_row = True
        if position > _RESERVED_HEADER_BYTES:
            raise AssertionError("Could not fit the header in the"
                                 " reserved space: %d > %d"
                                 % (position, _RESERVED_HEADER_BYTES))
        # write the rows out:
        for row in rows:
            reserved = _RESERVED_HEADER_BYTES # reserved space for first node
            row.spool.flush()
            row.spool.seek(0)
            # copy nodes to the finalised file.
            # Special case the first node as it may be prefixed
            node = row.spool.read(_PAGE_SIZE)
            result.write(node[reserved:])
            result.write("\x00" * (reserved - position))
            position = 0 # Only the root row actually has an offset
            copied_len = osutils.pumpfile(row.spool, result)
            if copied_len != (row.nodes - 1) * _PAGE_SIZE:
                if type(row) != _LeafBuilderRow:
                    raise AssertionError("Incorrect amount of data copied"
                        " expected: %d, got: %d"
                        % ((row.nodes - 1) * _PAGE_SIZE,
                           copied_len))
        result.flush()
        size = result.tell()
        result.seek(0)
        return result, size

    def finish(self):
        """Finalise the index.

        :return: A file handle for a temporary file containing the nodes added
            to the index.
        """
        return self._write_nodes(self.iter_all_entries())[0]

    def iter_all_entries(self):
        """Iterate over all keys within the index

        :return: An iterable of (index, key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (in this case dictionary hash order).
        """
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(3,
                "iter_all_entries scales with size of history.")
        # Doing serial rather than ordered would be faster; but this shouldn't
        # be getting called routinely anyway.
        iterators = [self._iter_mem_nodes()]
        for backing in self._backing_indices:
            if backing is not None:
                iterators.append(backing.iter_all_entries())
        if len(iterators) == 1:
            return iterators[0]
        return self._iter_smallest(iterators)

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (index, key, value, reference_lists). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (keys iteration order in this case).
        """
        keys = set(keys)
        local_keys = keys.intersection(self._keys)
        if self.reference_lists:
            for key in local_keys:
                node = self._nodes[key]
                yield self, key, node[1], node[0]
        else:
            for key in local_keys:
                node = self._nodes[key]
                yield self, key, node[1]
        # Find things that are in backing indices that have not been handled
        # yet.
        if not self._backing_indices:
            return # We won't find anything there either
        # Remove all of the keys that we found locally
        keys.difference_update(local_keys)
        for backing in self._backing_indices:
            if backing is None:
                continue
            if not keys:
                return
            for node in backing.iter_entries(keys):
                keys.remove(node[1])
                yield (self,) + node[1:]

    def iter_entries_prefix(self, keys):
        """Iterate over keys within the index using prefix matching.

        Prefix matching is applied within the tuple of a key, not to within
        the bytestring of each key element. e.g. if you have the keys ('foo',
        'bar'), ('foobar', 'gam') and do a prefix search for ('foo', None) then
        only the former key is returned.

        :param keys: An iterable providing the key prefixes to be retrieved.
            Each key prefix takes the form of a tuple the length of a key, but
            with the last N elements 'None' rather than a regular bytestring.
            The first element cannot be 'None'.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys with a matching prefix to those supplied. No additional keys
            will be returned, and every match that is in the index will be
            returned.
        """
        # XXX: To much duplication with the GraphIndex class; consider finding
        # a good place to pull out the actual common logic.
        keys = set(keys)
        if not keys:
            return
        for backing in self._backing_indices:
            if backing is None:
                continue
            for node in backing.iter_entries_prefix(keys):
                yield (self,) + node[1:]
        if self._key_length == 1:
            for key in keys:
                # sanity check
                if key[0] is None:
                    raise errors.BadIndexKey(key)
                if len(key) != self._key_length:
                    raise errors.BadIndexKey(key)
                try:
                    node = self._nodes[key]
                except KeyError:
                    continue
                if self.reference_lists:
                    yield self, key, node[1], node[0]
                else:
                    yield self, key, node[1]
            return
        for key in keys:
            # sanity check
            if key[0] is None:
                raise errors.BadIndexKey(key)
            if len(key) != self._key_length:
                raise errors.BadIndexKey(key)
            # find what it refers to:
            key_dict = self._get_nodes_by_key()
            elements = list(key)
            # find the subdict to return
            try:
                while len(elements) and elements[0] is not None:
                    key_dict = key_dict[elements[0]]
                    elements.pop(0)
            except KeyError:
                # a non-existant lookup.
                continue
            if len(elements):
                dicts = [key_dict]
                while dicts:
                    key_dict = dicts.pop(-1)
                    # can't be empty or would not exist
                    item, value = key_dict.iteritems().next()
                    if type(value) == dict:
                        # push keys
                        dicts.extend(key_dict.itervalues())
                    else:
                        # yield keys
                        for value in key_dict.itervalues():
                            yield (self, ) + value
            else:
                yield (self, ) + key_dict

    def _get_nodes_by_key(self):
        if self._nodes_by_key is None:
            nodes_by_key = {}
            if self.reference_lists:
                for key, (references, value) in self._nodes.iteritems():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value, references
            else:
                for key, (references, value) in self._nodes.iteritems():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value
            self._nodes_by_key = nodes_by_key
        return self._nodes_by_key

    def key_count(self):
        """Return an estimate of the number of keys in this index.

        For InMemoryGraphIndex the estimate is exact.
        """
        return len(self._keys) + sum(backing.key_count() for backing in
            self._backing_indices if backing is not None)

    def validate(self):
        """In memory index's have no known corruption at the moment."""


class _LeafNode(object):
    """A leaf node for a serialised B+Tree index."""

    def __init__(self, bytes, key_length, ref_list_length):
        """Parse bytes to create a leaf node object."""
        # splitlines mangles the \r delimiters.. don't use it.
        self.keys = dict(_btree_serializer._parse_leaf_lines(bytes,
            key_length, ref_list_length))


class _InternalNode(object):
    """An internal node for a serialised B+Tree index."""

    def __init__(self, bytes):
        """Parse bytes to create an internal node object."""
        # splitlines mangles the \r delimiters.. don't use it.
        self.keys = self._parse_lines(bytes.split('\n'))

    def _parse_lines(self, lines):
        nodes = []
        self.offset = int(lines[1][7:])
        for line in lines[2:]:
            if line == '':
                break
            nodes.append(tuple(line.split('\0')))
        return nodes


class BTreeGraphIndex(object):
    """Access to nodes via the standard GraphIndex interface for B+Tree's.

    Individual nodes are held in a LRU cache. This holds the root node in
    memory except when very large walks are done.
    """

    def __init__(self, transport, name, size):
        """Create a B+Tree index object on the index name.

        :param transport: The transport to read data for the index from.
        :param name: The file name of the index on transport.
        :param size: Optional size of the index in bytes. This allows
            compatibility with the GraphIndex API, as well as ensuring that
            the initial read (to read the root node header) can be done
            without over-reading even on empty indices, and on small indices
            allows single-IO to read the entire index.
        """
        self._transport = transport
        self._name = name
        self._size = size
        self._file = None
        self._recommended_pages = self._compute_recommended_pages()
        self._root_node = None
        # Default max size is 100,000 leave values
        self._leaf_value_cache = None # lru_cache.LRUCache(100*1000)
        self._leaf_node_cache = lru_cache.LRUCache(_NODE_CACHE_SIZE)
        self._internal_node_cache = lru_cache.LRUCache()
        self._key_count = None
        self._row_lengths = None
        self._row_offsets = None # Start of each row, [-1] is the end

    def __eq__(self, other):
        """Equal when self and other were created with the same parameters."""
        return (
            type(self) == type(other) and
            self._transport == other._transport and
            self._name == other._name and
            self._size == other._size)

    def __ne__(self, other):
        return not self.__eq__(other)

    def _get_and_cache_nodes(self, nodes):
        """Read nodes and cache them in the lru.

        The nodes list supplied is sorted and then read from disk, each node
        being inserted it into the _node_cache.

        Note: Asking for more nodes than the _node_cache can contain will
        result in some of the results being immediately discarded, to prevent
        this an assertion is raised if more nodes are asked for than are
        cachable.

        :return: A dict of {node_pos: node}
        """
        found = {}
        start_of_leaves = None
        for node_pos, node in self._read_nodes(sorted(nodes)):
            if node_pos == 0: # Special case
                self._root_node = node
            else:
                if start_of_leaves is None:
                    start_of_leaves = self._row_offsets[-2]
                if node_pos < start_of_leaves:
                    self._internal_node_cache.add(node_pos, node)
                else:
                    self._leaf_node_cache.add(node_pos, node)
            found[node_pos] = node
        return found

    def _compute_recommended_pages(self):
        """Convert transport's recommended_page_size into btree pages.

        recommended_page_size is in bytes, we want to know how many _PAGE_SIZE
        pages fit in that length.
        """
        recommended_read = self._transport.recommended_page_size()
        recommended_pages = int(math.ceil(recommended_read /
                                          float(_PAGE_SIZE)))
        return recommended_pages

    def _compute_total_pages_in_index(self):
        """How many pages are in the index.

        If we have read the header we will use the value stored there.
        Otherwise it will be computed based on the length of the index.
        """
        if self._size is None:
            raise AssertionError('_compute_total_pages_in_index should not be'
                                 ' called when self._size is None')
        if self._root_node is not None:
            # This is the number of pages as defined by the header
            return self._row_offsets[-1]
        # This is the number of pages as defined by the size of the index. They
        # should be indentical.
        total_pages = int(math.ceil(self._size / float(_PAGE_SIZE)))
        return total_pages

    def _expand_offsets(self, offsets):
        """Find extra pages to download.

        The idea is that we always want to make big-enough requests (like 64kB
        for http), so that we don't waste round trips. So given the entries
        that we already have cached and the new pages being downloaded figure
        out what other pages we might want to read.

        See also doc/developers/btree_index_prefetch.txt for more details.

        :param offsets: The offsets to be read
        :return: A list of offsets to download
        """
        if 'index' in debug.debug_flags:
            trace.mutter('expanding: %s\toffsets: %s', self._name, offsets)

        if len(offsets) >= self._recommended_pages:
            # Don't add more, we are already requesting more than enough
            if 'index' in debug.debug_flags:
                trace.mutter('  not expanding large request (%s >= %s)',
                             len(offsets), self._recommended_pages)
            return offsets
        if self._size is None:
            # Don't try anything, because we don't know where the file ends
            if 'index' in debug.debug_flags:
                trace.mutter('  not expanding without knowing index size')
            return offsets
        total_pages = self._compute_total_pages_in_index()
        cached_offsets = self._get_offsets_to_cached_pages()
        # If reading recommended_pages would read the rest of the index, just
        # do so.
        if total_pages - len(cached_offsets) <= self._recommended_pages:
            # Read whatever is left
            if cached_offsets:
                expanded = [x for x in xrange(total_pages)
                               if x not in cached_offsets]
            else:
                expanded = range(total_pages)
            if 'index' in debug.debug_flags:
                trace.mutter('  reading all unread pages: %s', expanded)
            return expanded

        if self._root_node is None:
            # ATM on the first read of the root node of a large index, we don't
            # bother pre-reading any other pages. This is because the
            # likelyhood of actually reading interesting pages is very low.
            # See doc/developers/btree_index_prefetch.txt for a discussion, and
            # a possible implementation when we are guessing that the second
            # layer index is small
            final_offsets = offsets
        else:
            tree_depth = len(self._row_lengths)
            if len(cached_offsets) < tree_depth and len(offsets) == 1:
                # We haven't read enough to justify expansion
                # If we are only going to read the root node, and 1 leaf node,
                # then it isn't worth expanding our request. Once we've read at
                # least 2 nodes, then we are probably doing a search, and we
                # start expanding our requests.
                if 'index' in debug.debug_flags:
                    trace.mutter('  not expanding on first reads')
                return offsets
            final_offsets = self._expand_to_neighbors(offsets, cached_offsets,
                                                      total_pages)

        final_offsets = sorted(final_offsets)
        if 'index' in debug.debug_flags:
            trace.mutter('expanded:  %s', final_offsets)
        return final_offsets

    def _expand_to_neighbors(self, offsets, cached_offsets, total_pages):
        """Expand requests to neighbors until we have enough pages.

        This is called from _expand_offsets after policy has determined that we
        want to expand.
        We only want to expand requests within a given layer. We cheat a little
        bit and assume all requests will be in the same layer. This is true
        given the current design, but if it changes this algorithm may perform
        oddly.

        :param offsets: requested offsets
        :param cached_offsets: offsets for pages we currently have cached
        :return: A set() of offsets after expansion
        """
        final_offsets = set(offsets)
        first = end = None
        new_tips = set(final_offsets)
        while len(final_offsets) < self._recommended_pages and new_tips:
            next_tips = set()
            for pos in new_tips:
                if first is None:
                    first, end = self._find_layer_first_and_end(pos)
                previous = pos - 1
                if (previous > 0
                    and previous not in cached_offsets
                    and previous not in final_offsets
                    and previous >= first):
                    next_tips.add(previous)
                after = pos + 1
                if (after < total_pages
                    and after not in cached_offsets
                    and after not in final_offsets
                    and after < end):
                    next_tips.add(after)
                # This would keep us from going bigger than
                # recommended_pages by only expanding the first offsets.
                # However, if we are making a 'wide' request, it is
                # reasonable to expand all points equally.
                # if len(final_offsets) > recommended_pages:
                #     break
            final_offsets.update(next_tips)
            new_tips = next_tips
        return final_offsets

    def _find_layer_first_and_end(self, offset):
        """Find the start/stop nodes for the layer corresponding to offset.

        :return: (first, end)
            first is the first node in this layer
            end is the first node of the next layer
        """
        first = end = 0
        for roffset in self._row_offsets:
            first = end
            end = roffset
            if offset < roffset:
                break
        return first, end

    def _get_offsets_to_cached_pages(self):
        """Determine what nodes we already have cached."""
        cached_offsets = set(self._internal_node_cache.keys())
        cached_offsets.update(self._leaf_node_cache.keys())
        if self._root_node is not None:
            cached_offsets.add(0)
        return cached_offsets

    def _get_root_node(self):
        if self._root_node is None:
            # We may not have a root node yet
            self._get_internal_nodes([0])
        return self._root_node

    def _get_nodes(self, cache, node_indexes):
        found = {}
        needed = []
        for idx in node_indexes:
            if idx == 0 and self._root_node is not None:
                found[0] = self._root_node
                continue
            try:
                found[idx] = cache[idx]
            except KeyError:
                needed.append(idx)
        if not needed:
            return found
        needed = self._expand_offsets(needed)
        found.update(self._get_and_cache_nodes(needed))
        return found

    def _get_internal_nodes(self, node_indexes):
        """Get a node, from cache or disk.

        After getting it, the node will be cached.
        """
        return self._get_nodes(self._internal_node_cache, node_indexes)

    def _cache_leaf_values(self, nodes):
        """Cache directly from key => value, skipping the btree."""
        if self._leaf_value_cache is not None:
            for node in nodes.itervalues():
                for key, value in node.keys.iteritems():
                    if key in self._leaf_value_cache:
                        # Don't add the rest of the keys, we've seen this node
                        # before.
                        break
                    self._leaf_value_cache[key] = value

    def _get_leaf_nodes(self, node_indexes):
        """Get a bunch of nodes, from cache or disk."""
        found = self._get_nodes(self._leaf_node_cache, node_indexes)
        self._cache_leaf_values(found)
        return found

    def iter_all_entries(self):
        """Iterate over all keys within the index.

        :return: An iterable of (index, key, value) or (index, key, value, reference_lists).
            The former tuple is used when there are no reference lists in the
            index, making the API compatible with simple key:value index types.
            There is no defined order for the result iteration - it will be in
            the most efficient order for the index.
        """
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(3,
                "iter_all_entries scales with size of history.")
        if not self.key_count():
            return
        if self._row_offsets[-1] == 1:
            # There is only the root node, and we read that via key_count()
            if self.node_ref_lists:
                for key, (value, refs) in sorted(self._root_node.keys.items()):
                    yield (self, key, value, refs)
            else:
                for key, (value, refs) in sorted(self._root_node.keys.items()):
                    yield (self, key, value)
            return
        start_of_leaves = self._row_offsets[-2]
        end_of_leaves = self._row_offsets[-1]
        needed_offsets = range(start_of_leaves, end_of_leaves)
        if needed_offsets == [0]:
            # Special case when we only have a root node, as we have already
            # read everything
            nodes = [(0, self._root_node)]
        else:
            nodes = self._read_nodes(needed_offsets)
        # We iterate strictly in-order so that we can use this function
        # for spilling index builds to disk.
        if self.node_ref_lists:
            for _, node in nodes:
                for key, (value, refs) in sorted(node.keys.items()):
                    yield (self, key, value, refs)
        else:
            for _, node in nodes:
                for key, (value, refs) in sorted(node.keys.items()):
                    yield (self, key, value)

    @staticmethod
    def _multi_bisect_right(in_keys, fixed_keys):
        """Find the positions where each 'in_key' would fit in fixed_keys.

        This is equivalent to doing "bisect_right" on each in_key into
        fixed_keys

        :param in_keys: A sorted list of keys to match with fixed_keys
        :param fixed_keys: A sorted list of keys to match against
        :return: A list of (integer position, [key list]) tuples.
        """
        if not in_keys:
            return []
        if not fixed_keys:
            # no pointers in the fixed_keys list, which means everything must
            # fall to the left.
            return [(0, in_keys)]

        # TODO: Iterating both lists will generally take M + N steps
        #       Bisecting each key will generally take M * log2 N steps.
        #       If we had an efficient way to compare, we could pick the method
        #       based on which has the fewer number of steps.
        #       There is also the argument that bisect_right is a compiled
        #       function, so there is even more to be gained.
        # iter_steps = len(in_keys) + len(fixed_keys)
        # bisect_steps = len(in_keys) * math.log(len(fixed_keys), 2)
        if len(in_keys) == 1: # Bisect will always be faster for M = 1
            return [(bisect_right(fixed_keys, in_keys[0]), in_keys)]
        # elif bisect_steps < iter_steps:
        #     offsets = {}
        #     for key in in_keys:
        #         offsets.setdefault(bisect_right(fixed_keys, key),
        #                            []).append(key)
        #     return [(o, offsets[o]) for o in sorted(offsets)]
        in_keys_iter = iter(in_keys)
        fixed_keys_iter = enumerate(fixed_keys)
        cur_in_key = in_keys_iter.next()
        cur_fixed_offset, cur_fixed_key = fixed_keys_iter.next()

        class InputDone(Exception): pass
        class FixedDone(Exception): pass

        output = []
        cur_out = []

        # TODO: Another possibility is that rather than iterating on each side,
        #       we could use a combination of bisecting and iterating. For
        #       example, while cur_in_key < fixed_key, bisect to find its
        #       point, then iterate all matching keys, then bisect (restricted
        #       to only the remainder) for the next one, etc.
        try:
            while True:
                if cur_in_key < cur_fixed_key:
                    cur_keys = []
                    cur_out = (cur_fixed_offset, cur_keys)
                    output.append(cur_out)
                    while cur_in_key < cur_fixed_key:
                        cur_keys.append(cur_in_key)
                        try:
                            cur_in_key = in_keys_iter.next()
                        except StopIteration:
                            raise InputDone
                    # At this point cur_in_key must be >= cur_fixed_key
                # step the cur_fixed_key until we pass the cur key, or walk off
                # the end
                while cur_in_key >= cur_fixed_key:
                    try:
                        cur_fixed_offset, cur_fixed_key = fixed_keys_iter.next()
                    except StopIteration:
                        raise FixedDone
        except InputDone:
            # We consumed all of the input, nothing more to do
            pass
        except FixedDone:
            # There was some input left, but we consumed all of fixed, so we
            # have to add one more for the tail
            cur_keys = [cur_in_key]
            cur_keys.extend(in_keys_iter)
            cur_out = (len(fixed_keys), cur_keys)
            output.append(cur_out)
        return output

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys supplied. No additional keys will be returned, and every
            key supplied that is in the index will be returned.
        """
        # 6 seconds spent in miss_torture using the sorted() line.
        # Even with out of order disk IO it seems faster not to sort it when
        # large queries are being made.
        # However, now that we are doing multi-way bisecting, we need the keys
        # in sorted order anyway. We could change the multi-way code to not
        # require sorted order. (For example, it bisects for the first node,
        # does an in-order search until a key comes before the current point,
        # which it then bisects for, etc.)
        keys = frozenset(keys)
        if not keys:
            return

        if not self.key_count():
            return

        needed_keys = []
        if self._leaf_value_cache is None:
            needed_keys = keys
        else:
            for key in keys:
                value = self._leaf_value_cache.get(key, None)
                if value is not None:
                    # This key is known not to be here, skip it
                    value, refs = value
                    if self.node_ref_lists:
                        yield (self, key, value, refs)
                    else:
                        yield (self, key, value)
                else:
                    needed_keys.append(key)

        last_key = None
        needed_keys = keys
        if not needed_keys:
            return
        # 6 seconds spent in miss_torture using the sorted() line.
        # Even with out of order disk IO it seems faster not to sort it when
        # large queries are being made.
        needed_keys = sorted(needed_keys)

        nodes_and_keys = [(0, needed_keys)]

        for row_pos, next_row_start in enumerate(self._row_offsets[1:-1]):
            node_indexes = [idx for idx, s_keys in nodes_and_keys]
            nodes = self._get_internal_nodes(node_indexes)

            next_nodes_and_keys = []
            for node_index, sub_keys in nodes_and_keys:
                node = nodes[node_index]
                positions = self._multi_bisect_right(sub_keys, node.keys)
                node_offset = next_row_start + node.offset
                next_nodes_and_keys.extend([(node_offset + pos, s_keys)
                                           for pos, s_keys in positions])
            nodes_and_keys = next_nodes_and_keys
        # We should now be at the _LeafNodes
        node_indexes = [idx for idx, s_keys in nodes_and_keys]

        # TODO: We may *not* want to always read all the nodes in one
        #       big go. Consider setting a max size on this.

        nodes = self._get_leaf_nodes(node_indexes)
        for node_index, sub_keys in nodes_and_keys:
            if not sub_keys:
                continue
            node = nodes[node_index]
            for next_sub_key in sub_keys:
                if next_sub_key in node.keys:
                    value, refs = node.keys[next_sub_key]
                    if self.node_ref_lists:
                        yield (self, next_sub_key, value, refs)
                    else:
                        yield (self, next_sub_key, value)

    def iter_entries_prefix(self, keys):
        """Iterate over keys within the index using prefix matching.

        Prefix matching is applied within the tuple of a key, not to within
        the bytestring of each key element. e.g. if you have the keys ('foo',
        'bar'), ('foobar', 'gam') and do a prefix search for ('foo', None) then
        only the former key is returned.

        WARNING: Note that this method currently causes a full index parse
        unconditionally (which is reasonably appropriate as it is a means for
        thunking many small indices into one larger one and still supplies
        iter_all_entries at the thunk layer).

        :param keys: An iterable providing the key prefixes to be retrieved.
            Each key prefix takes the form of a tuple the length of a key, but
            with the last N elements 'None' rather than a regular bytestring.
            The first element cannot be 'None'.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys with a matching prefix to those supplied. No additional keys
            will be returned, and every match that is in the index will be
            returned.
        """
        keys = sorted(set(keys))
        if not keys:
            return
        # Load if needed to check key lengths
        if self._key_count is None:
            self._get_root_node()
        # TODO: only access nodes that can satisfy the prefixes we are looking
        # for. For now, to meet API usage (as this function is not used by
        # current bzrlib) just suck the entire index and iterate in memory.
        nodes = {}
        if self.node_ref_lists:
            if self._key_length == 1:
                for _1, key, value, refs in self.iter_all_entries():
                    nodes[key] = value, refs
            else:
                nodes_by_key = {}
                for _1, key, value, refs in self.iter_all_entries():
                    key_value = key, value, refs
                    # For a key of (foo, bar, baz) create
                    # _nodes_by_key[foo][bar][baz] = key_value
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key_value
        else:
            if self._key_length == 1:
                for _1, key, value in self.iter_all_entries():
                    nodes[key] = value
            else:
                nodes_by_key = {}
                for _1, key, value in self.iter_all_entries():
                    key_value = key, value
                    # For a key of (foo, bar, baz) create
                    # _nodes_by_key[foo][bar][baz] = key_value
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key_value
        if self._key_length == 1:
            for key in keys:
                # sanity check
                if key[0] is None:
                    raise errors.BadIndexKey(key)
                if len(key) != self._key_length:
                    raise errors.BadIndexKey(key)
                try:
                    if self.node_ref_lists:
                        value, node_refs = nodes[key]
                        yield self, key, value, node_refs
                    else:
                        yield self, key, nodes[key]
                except KeyError:
                    pass
            return
        for key in keys:
            # sanity check
            if key[0] is None:
                raise errors.BadIndexKey(key)
            if len(key) != self._key_length:
                raise errors.BadIndexKey(key)
            # find what it refers to:
            key_dict = nodes_by_key
            elements = list(key)
            # find the subdict whose contents should be returned.
            try:
                while len(elements) and elements[0] is not None:
                    key_dict = key_dict[elements[0]]
                    elements.pop(0)
            except KeyError:
                # a non-existant lookup.
                continue
            if len(elements):
                dicts = [key_dict]
                while dicts:
                    key_dict = dicts.pop(-1)
                    # can't be empty or would not exist
                    item, value = key_dict.iteritems().next()
                    if type(value) == dict:
                        # push keys
                        dicts.extend(key_dict.itervalues())
                    else:
                        # yield keys
                        for value in key_dict.itervalues():
                            # each value is the key:value:node refs tuple
                            # ready to yield.
                            yield (self, ) + value
            else:
                # the last thing looked up was a terminal element
                yield (self, ) + key_dict

    def key_count(self):
        """Return an estimate of the number of keys in this index.

        For BTreeGraphIndex the estimate is exact as it is contained in the
        header.
        """
        if self._key_count is None:
            self._get_root_node()
        return self._key_count

    def _compute_row_offsets(self):
        """Fill out the _row_offsets attribute based on _row_lengths."""
        offsets = []
        row_offset = 0
        for row in self._row_lengths:
            offsets.append(row_offset)
            row_offset += row
        offsets.append(row_offset)
        self._row_offsets = offsets

    def _parse_header_from_bytes(self, bytes):
        """Parse the header from a region of bytes.

        :param bytes: The data to parse.
        :return: An offset, data tuple such as readv yields, for the unparsed
            data. (which may be of length 0).
        """
        signature = bytes[0:len(self._signature())]
        if not signature == self._signature():
            raise errors.BadIndexFormatSignature(self._name, BTreeGraphIndex)
        lines = bytes[len(self._signature()):].splitlines()
        options_line = lines[0]
        if not options_line.startswith(_OPTION_NODE_REFS):
            raise errors.BadIndexOptions(self)
        try:
            self.node_ref_lists = int(options_line[len(_OPTION_NODE_REFS):])
        except ValueError:
            raise errors.BadIndexOptions(self)
        options_line = lines[1]
        if not options_line.startswith(_OPTION_KEY_ELEMENTS):
            raise errors.BadIndexOptions(self)
        try:
            self._key_length = int(options_line[len(_OPTION_KEY_ELEMENTS):])
        except ValueError:
            raise errors.BadIndexOptions(self)
        options_line = lines[2]
        if not options_line.startswith(_OPTION_LEN):
            raise errors.BadIndexOptions(self)
        try:
            self._key_count = int(options_line[len(_OPTION_LEN):])
        except ValueError:
            raise errors.BadIndexOptions(self)
        options_line = lines[3]
        if not options_line.startswith(_OPTION_ROW_LENGTHS):
            raise errors.BadIndexOptions(self)
        try:
            self._row_lengths = map(int, [length for length in
                options_line[len(_OPTION_ROW_LENGTHS):].split(',')
                if len(length)])
        except ValueError:
            raise errors.BadIndexOptions(self)
        self._compute_row_offsets()

        # calculate the bytes we have processed
        header_end = (len(signature) + sum(map(len, lines[0:4])) + 4)
        return header_end, bytes[header_end:]

    def _read_nodes(self, nodes):
        """Read some nodes from disk into the LRU cache.

        This performs a readv to get the node data into memory, and parses each
        node, then yields it to the caller. The nodes are requested in the
        supplied order. If possible doing sort() on the list before requesting
        a read may improve performance.

        :param nodes: The nodes to read. 0 - first node, 1 - second node etc.
        :return: None
        """
        # may be the byte string of the whole file
        bytes = None
        # list of (offset, length) regions of the file that should, evenually
        # be read in to data_ranges, either from 'bytes' or from the transport
        ranges = []
        for index in nodes:
            offset = index * _PAGE_SIZE
            size = _PAGE_SIZE
            if index == 0:
                # Root node - special case
                if self._size:
                    size = min(_PAGE_SIZE, self._size)
                else:
                    # The only case where we don't know the size, is for very
                    # small indexes. So we read the whole thing
                    bytes = self._transport.get_bytes(self._name)
                    self._size = len(bytes)
                    # the whole thing should be parsed out of 'bytes'
                    ranges.append((0, len(bytes)))
                    break
            else:
                if offset > self._size:
                    raise AssertionError('tried to read past the end'
                                         ' of the file %s > %s'
                                         % (offset, self._size))
                size = min(size, self._size - offset)
            ranges.append((offset, size))
        if not ranges:
            return
        elif bytes is not None:
            # already have the whole file
            data_ranges = [(start, bytes[start:start+_PAGE_SIZE])
                           for start in xrange(0, len(bytes), _PAGE_SIZE)]
        elif self._file is None:
            data_ranges = self._transport.readv(self._name, ranges)
        else:
            data_ranges = []
            for offset, size in ranges:
                self._file.seek(offset)
                data_ranges.append((offset, self._file.read(size)))
        for offset, data in data_ranges:
            if offset == 0:
                # extract the header
                offset, data = self._parse_header_from_bytes(data)
                if len(data) == 0:
                    continue
            bytes = zlib.decompress(data)
            if bytes.startswith(_LEAF_FLAG):
                node = _LeafNode(bytes, self._key_length, self.node_ref_lists)
            elif bytes.startswith(_INTERNAL_FLAG):
                node = _InternalNode(bytes)
            else:
                raise AssertionError("Unknown node type for %r" % bytes)
            yield offset / _PAGE_SIZE, node

    def _signature(self):
        """The file signature for this index type."""
        return _BTSIGNATURE

    def validate(self):
        """Validate that everything in the index can be accessed."""
        # just read and parse every node.
        self._get_root_node()
        if len(self._row_lengths) > 1:
            start_node = self._row_offsets[1]
        else:
            # We shouldn't be reading anything anyway
            start_node = 1
        node_end = self._row_offsets[-1]
        for node in self._read_nodes(range(start_node, node_end)):
            pass


try:
    from bzrlib import _btree_serializer_c as _btree_serializer
except ImportError:
    from bzrlib import _btree_serializer_py as _btree_serializer
