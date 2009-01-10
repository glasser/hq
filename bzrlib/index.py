# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Indexing facilities."""

__all__ = [
    'CombinedGraphIndex',
    'GraphIndex',
    'GraphIndexBuilder',
    'GraphIndexPrefixAdapter',
    'InMemoryGraphIndex',
    ]

from bisect import bisect_right
from cStringIO import StringIO
import re
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import trace
from bzrlib.bisect_multi import bisect_multi_bytes
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
""")
from bzrlib import (
    debug,
    errors,
    symbol_versioning,
    )

_HEADER_READV = (0, 200)
_OPTION_KEY_ELEMENTS = "key_elements="
_OPTION_LEN = "len="
_OPTION_NODE_REFS = "node_ref_lists="
_SIGNATURE = "Bazaar Graph Index 1\n"


_whitespace_re = re.compile('[\t\n\x0b\x0c\r\x00 ]')
_newline_null_re = re.compile('[\n\0]')


def _has_key_from_parent_map(self, key):
    """Check if this index has one key.

    If it's possible to check for multiple keys at once through 
    calling get_parent_map that should be faster.
    """
    return (key in self.get_parent_map([key]))


def _missing_keys_from_parent_map(self, keys):
    return set(keys) - set(self.get_parent_map(keys))


class GraphIndexBuilder(object):
    """A builder that can build a GraphIndex.
    
    The resulting graph has the structure:
    
    _SIGNATURE OPTIONS NODES NEWLINE
    _SIGNATURE     := 'Bazaar Graph Index 1' NEWLINE
    OPTIONS        := 'node_ref_lists=' DIGITS NEWLINE
    NODES          := NODE*
    NODE           := KEY NULL ABSENT? NULL REFERENCES NULL VALUE NEWLINE
    KEY            := Not-whitespace-utf8
    ABSENT         := 'a'
    REFERENCES     := REFERENCE_LIST (TAB REFERENCE_LIST){node_ref_lists - 1}
    REFERENCE_LIST := (REFERENCE (CR REFERENCE)*)?
    REFERENCE      := DIGITS  ; digits is the byte offset in the index of the
                              ; referenced key.
    VALUE          := no-newline-no-null-bytes
    """

    def __init__(self, reference_lists=0, key_elements=1):
        """Create a GraphIndex builder.

        :param reference_lists: The number of node references lists for each
            entry.
        :param key_elements: The number of bytestrings in each key.
        """
        self.reference_lists = reference_lists
        self._keys = set()
        # A dict of {key: (absent, ref_lists, value)}
        self._nodes = {}
        self._nodes_by_key = None
        self._key_length = key_elements
        self._optimize_for_size = False

    def _check_key(self, key):
        """Raise BadIndexKey if key is not a valid key for this index."""
        if type(key) != tuple:
            raise errors.BadIndexKey(key)
        if self._key_length != len(key):
            raise errors.BadIndexKey(key)
        for element in key:
            if not element or _whitespace_re.search(element) is not None:
                raise errors.BadIndexKey(element)

    def _external_references(self):
        """Return references that are not present in this index.
        """
        keys = set()
        refs = set()
        # TODO: JAM 2008-11-21 This makes an assumption about how the reference
        #       lists are used. It is currently correct for pack-0.92 through
        #       1.9, which use the node references (3rd column) second
        #       reference list as the compression parent. Perhaps this should
        #       be moved into something higher up the stack, since it
        #       makes assumptions about how the index is used.
        if self.reference_lists > 1:
            for node in self.iter_all_entries():
                keys.add(node[1])
                refs.update(node[3][1])
            return refs - keys
        else:
            # If reference_lists == 0 there can be no external references, and
            # if reference_lists == 1, then there isn't a place to store the
            # compression parent
            return set()

    def _get_nodes_by_key(self):
        if self._nodes_by_key is None:
            nodes_by_key = {}
            if self.reference_lists:
                for key, (absent, references, value) in self._nodes.iteritems():
                    if absent:
                        continue
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value, references
            else:
                for key, (absent, references, value) in self._nodes.iteritems():
                    if absent:
                        continue
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value
            self._nodes_by_key = nodes_by_key
        return self._nodes_by_key

    def _update_nodes_by_key(self, key, value, node_refs):
        """Update the _nodes_by_key dict with a new key.

        For a key of (foo, bar, baz) create
        _nodes_by_key[foo][bar][baz] = key_value
        """
        if self._nodes_by_key is None:
            return
        key_dict = self._nodes_by_key
        if self.reference_lists:
            key_value = key, value, node_refs
        else:
            key_value = key, value
        for subkey in key[:-1]:
            key_dict = key_dict.setdefault(subkey, {})
        key_dict[key[-1]] = key_value

    def _check_key_ref_value(self, key, references, value):
        """Check that 'key' and 'references' are all valid.

        :param key: A key tuple. Must conform to the key interface (be a tuple,
            be of the right length, not have any whitespace or nulls in any key
            element.)
        :param references: An iterable of reference lists. Something like
            [[(ref, key)], [(ref, key), (other, key)]]
        :param value: The value associate with this key. Must not contain
            newlines or null characters.
        :return: (node_refs, absent_references)
            node_refs   basically a packed form of 'references' where all
                        iterables are tuples
            absent_references   reference keys that are not in self._nodes.
                                This may contain duplicates if the same key is
                                referenced in multiple lists.
        """
        self._check_key(key)
        if _newline_null_re.search(value) is not None:
            raise errors.BadIndexValue(value)
        if len(references) != self.reference_lists:
            raise errors.BadIndexValue(references)
        node_refs = []
        absent_references = []
        for reference_list in references:
            for reference in reference_list:
                # If reference *is* in self._nodes, then we know it has already
                # been checked.
                if reference not in self._nodes:
                    self._check_key(reference)
                    absent_references.append(reference)
            node_refs.append(tuple(reference_list))
        return tuple(node_refs), absent_references

    def add_node(self, key, value, references=()):
        """Add a node to the index.

        :param key: The key. keys are non-empty tuples containing
            as many whitespace-free utf8 bytestrings as the key length
            defined for this index.
        :param references: An iterable of iterables of keys. Each is a
            reference to another key.
        :param value: The value to associate with the key. It may be any
            bytes as long as it does not contain \0 or \n.
        """
        (node_refs,
         absent_references) = self._check_key_ref_value(key, references, value)
        if key in self._nodes and self._nodes[key][0] != 'a':
            raise errors.BadIndexDuplicateKey(key, self)
        for reference in absent_references:
            # There may be duplicates, but I don't think it is worth worrying
            # about
            self._nodes[reference] = ('a', (), '')
        self._nodes[key] = ('', node_refs, value)
        self._keys.add(key)
        if self._nodes_by_key is not None and self._key_length > 1:
            self._update_nodes_by_key(key, value, node_refs)

    def finish(self):
        lines = [_SIGNATURE]
        lines.append(_OPTION_NODE_REFS + str(self.reference_lists) + '\n')
        lines.append(_OPTION_KEY_ELEMENTS + str(self._key_length) + '\n')
        lines.append(_OPTION_LEN + str(len(self._keys)) + '\n')
        prefix_length = sum(len(x) for x in lines)
        # references are byte offsets. To avoid having to do nasty
        # polynomial work to resolve offsets (references to later in the
        # file cannot be determined until all the inbetween references have
        # been calculated too) we pad the offsets with 0's to make them be
        # of consistent length. Using binary offsets would break the trivial
        # file parsing.
        # to calculate the width of zero's needed we do three passes:
        # one to gather all the non-reference data and the number of references.
        # one to pad all the data with reference-length and determine entry
        # addresses.
        # One to serialise.
        
        # forward sorted by key. In future we may consider topological sorting,
        # at the cost of table scans for direct lookup, or a second index for
        # direct lookup
        nodes = sorted(self._nodes.items())
        # if we do not prepass, we don't know how long it will be up front.
        expected_bytes = None
        # we only need to pre-pass if we have reference lists at all.
        if self.reference_lists:
            key_offset_info = []
            non_ref_bytes = prefix_length
            total_references = 0
            # TODO use simple multiplication for the constants in this loop.
            for key, (absent, references, value) in nodes:
                # record the offset known *so far* for this key:
                # the non reference bytes to date, and the total references to
                # date - saves reaccumulating on the second pass
                key_offset_info.append((key, non_ref_bytes, total_references))
                # key is literal, value is literal, there are 3 null's, 1 NL
                # key is variable length tuple, \x00 between elements
                non_ref_bytes += sum(len(element) for element in key)
                if self._key_length > 1:
                    non_ref_bytes += self._key_length - 1
                # value is literal bytes, there are 3 null's, 1 NL.
                non_ref_bytes += len(value) + 3 + 1
                # one byte for absent if set.
                if absent:
                    non_ref_bytes += 1
                elif self.reference_lists:
                    # (ref_lists -1) tabs
                    non_ref_bytes += self.reference_lists - 1
                    # (ref-1 cr's per ref_list)
                    for ref_list in references:
                        # how many references across the whole file?
                        total_references += len(ref_list)
                        # accrue reference separators
                        if ref_list:
                            non_ref_bytes += len(ref_list) - 1
            # how many digits are needed to represent the total byte count?
            digits = 1
            possible_total_bytes = non_ref_bytes + total_references*digits
            while 10 ** digits < possible_total_bytes:
                digits += 1
                possible_total_bytes = non_ref_bytes + total_references*digits
            expected_bytes = possible_total_bytes + 1 # terminating newline
            # resolve key addresses.
            key_addresses = {}
            for key, non_ref_bytes, total_references in key_offset_info:
                key_addresses[key] = non_ref_bytes + total_references*digits
            # serialise
            format_string = '%%0%sd' % digits
        for key, (absent, references, value) in nodes:
            flattened_references = []
            for ref_list in references:
                ref_addresses = []
                for reference in ref_list:
                    ref_addresses.append(format_string % key_addresses[reference])
                flattened_references.append('\r'.join(ref_addresses))
            string_key = '\x00'.join(key)
            lines.append("%s\x00%s\x00%s\x00%s\n" % (string_key, absent,
                '\t'.join(flattened_references), value))
        lines.append('\n')
        result = StringIO(''.join(lines))
        if expected_bytes and len(result.getvalue()) != expected_bytes:
            raise errors.BzrError('Failed index creation. Internal error:'
                ' mismatched output length and expected length: %d %d' %
                (len(result.getvalue()), expected_bytes))
        return result

    def set_optimize(self, for_size=True):
        """Change how the builder tries to optimize the result.

        :param for_size: Tell the builder to try and make the index as small as
            possible.
        :return: None
        """
        # GraphIndexBuilder itself doesn't pay attention to the flag yet, but
        # other builders do.
        self._optimize_for_size = for_size


class GraphIndex(object):
    """An index for data with embedded graphs.
 
    The index maps keys to a list of key reference lists, and a value.
    Each node has the same number of key reference lists. Each key reference
    list can be empty or an arbitrary length. The value is an opaque NULL
    terminated string without any newlines. The storage of the index is 
    hidden in the interface: keys and key references are always tuples of
    bytestrings, never the internal representation (e.g. dictionary offsets).

    It is presumed that the index will not be mutated - it is static data.

    Successive iter_all_entries calls will read the entire index each time.
    Additionally, iter_entries calls will read the index linearly until the
    desired keys are found. XXX: This must be fixed before the index is
    suitable for production use. :XXX
    """

    def __init__(self, transport, name, size):
        """Open an index called name on transport.

        :param transport: A bzrlib.transport.Transport.
        :param name: A path to provide to transport API calls.
        :param size: The size of the index in bytes. This is used for bisection
            logic to perform partial index reads. While the size could be
            obtained by statting the file this introduced an additional round
            trip as well as requiring stat'able transports, both of which are
            avoided by having it supplied. If size is None, then bisection
            support will be disabled and accessing the index will just stream
            all the data.
        """
        self._transport = transport
        self._name = name
        # Becomes a dict of key:(value, reference-list-byte-locations) used by
        # the bisection interface to store parsed but not resolved keys.
        self._bisect_nodes = None
        # Becomes a dict of key:(value, reference-list-keys) which are ready to
        # be returned directly to callers.
        self._nodes = None
        # a sorted list of slice-addresses for the parsed bytes of the file.
        # e.g. (0,1) would mean that byte 0 is parsed.
        self._parsed_byte_map = []
        # a sorted list of keys matching each slice address for parsed bytes
        # e.g. (None, 'foo@bar') would mean that the first byte contained no
        # key, and the end byte of the slice is the of the data for 'foo@bar'
        self._parsed_key_map = []
        self._key_count = None
        self._keys_by_offset = None
        self._nodes_by_key = None
        self._size = size
        # The number of bytes we've read so far in trying to process this file
        self._bytes_read = 0

    def __eq__(self, other):
        """Equal when self and other were created with the same parameters."""
        return (
            type(self) == type(other) and
            self._transport == other._transport and
            self._name == other._name and
            self._size == other._size)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__,
            self._transport.abspath(self._name))

    def _buffer_all(self, stream=None):
        """Buffer all the index data.

        Mutates self._nodes and self.keys_by_offset.
        """
        if self._nodes is not None:
            # We already did this
            return
        if 'index' in debug.debug_flags:
            mutter('Reading entire index %s', self._transport.abspath(self._name))
        if stream is None:
            stream = self._transport.get(self._name)
        self._read_prefix(stream)
        self._expected_elements = 3 + self._key_length
        line_count = 0
        # raw data keyed by offset
        self._keys_by_offset = {}
        # ready-to-return key:value or key:value, node_ref_lists
        self._nodes = {}
        self._nodes_by_key = None
        trailers = 0
        pos = stream.tell()
        lines = stream.read().split('\n')
        del lines[-1]
        _, _, _, trailers = self._parse_lines(lines, pos)
        for key, absent, references, value in self._keys_by_offset.itervalues():
            if absent:
                continue
            # resolve references:
            if self.node_ref_lists:
                node_value = (value, self._resolve_references(references))
            else:
                node_value = value
            self._nodes[key] = node_value
        # cache the keys for quick set intersections
        self._keys = set(self._nodes)
        if trailers != 1:
            # there must be one line - the empty trailer line.
            raise errors.BadIndexData(self)

    def _get_nodes_by_key(self):
        if self._nodes_by_key is None:
            nodes_by_key = {}
            if self.node_ref_lists:
                for key, (value, references) in self._nodes.iteritems():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value, references
            else:
                for key, value in self._nodes.iteritems():
                    key_dict = nodes_by_key
                    for subkey in key[:-1]:
                        key_dict = key_dict.setdefault(subkey, {})
                    key_dict[key[-1]] = key, value
            self._nodes_by_key = nodes_by_key
        return self._nodes_by_key

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
        if self._nodes is None:
            self._buffer_all()
        if self.node_ref_lists:
            for key, (value, node_ref_lists) in self._nodes.iteritems():
                yield self, key, value, node_ref_lists
        else:
            for key, value in self._nodes.iteritems():
                yield self, key, value

    def _read_prefix(self, stream):
        signature = stream.read(len(self._signature()))
        if not signature == self._signature():
            raise errors.BadIndexFormatSignature(self._name, GraphIndex)
        options_line = stream.readline()
        if not options_line.startswith(_OPTION_NODE_REFS):
            raise errors.BadIndexOptions(self)
        try:
            self.node_ref_lists = int(options_line[len(_OPTION_NODE_REFS):-1])
        except ValueError:
            raise errors.BadIndexOptions(self)
        options_line = stream.readline()
        if not options_line.startswith(_OPTION_KEY_ELEMENTS):
            raise errors.BadIndexOptions(self)
        try:
            self._key_length = int(options_line[len(_OPTION_KEY_ELEMENTS):-1])
        except ValueError:
            raise errors.BadIndexOptions(self)
        options_line = stream.readline()
        if not options_line.startswith(_OPTION_LEN):
            raise errors.BadIndexOptions(self)
        try:
            self._key_count = int(options_line[len(_OPTION_LEN):-1])
        except ValueError:
            raise errors.BadIndexOptions(self)

    def _resolve_references(self, references):
        """Return the resolved key references for references.
        
        References are resolved by looking up the location of the key in the
        _keys_by_offset map and substituting the key name, preserving ordering.

        :param references: An iterable of iterables of key locations. e.g. 
            [[123, 456], [123]]
        :return: A tuple of tuples of keys.
        """
        node_refs = []
        for ref_list in references:
            node_refs.append(tuple([self._keys_by_offset[ref][0] for ref in ref_list]))
        return tuple(node_refs)

    def _find_index(self, range_map, key):
        """Helper for the _parsed_*_index calls.

        Given a range map - [(start, end), ...], finds the index of the range
        in the map for key if it is in the map, and if it is not there, the
        immediately preceeding range in the map.
        """
        result = bisect_right(range_map, key) - 1
        if result + 1 < len(range_map):
            # check the border condition, it may be in result + 1
            if range_map[result + 1][0] == key[0]:
                return result + 1
        return result

    def _parsed_byte_index(self, offset):
        """Return the index of the entry immediately before offset.

        e.g. if the parsed map has regions 0,10 and 11,12 parsed, meaning that
        there is one unparsed byte (the 11th, addressed as[10]). then:
        asking for 0 will return 0
        asking for 10 will return 0
        asking for 11 will return 1
        asking for 12 will return 1
        """
        key = (offset, 0)
        return self._find_index(self._parsed_byte_map, key)

    def _parsed_key_index(self, key):
        """Return the index of the entry immediately before key.

        e.g. if the parsed map has regions (None, 'a') and ('b','c') parsed,
        meaning that keys from None to 'a' inclusive, and 'b' to 'c' inclusive
        have been parsed, then:
        asking for '' will return 0
        asking for 'a' will return 0
        asking for 'b' will return 1
        asking for 'e' will return 1
        """
        search_key = (key, None)
        return self._find_index(self._parsed_key_map, search_key)

    def _is_parsed(self, offset):
        """Returns True if offset has been parsed."""
        index = self._parsed_byte_index(offset)
        if index == len(self._parsed_byte_map):
            return offset < self._parsed_byte_map[index - 1][1]
        start, end = self._parsed_byte_map[index]
        return offset >= start and offset < end

    def _iter_entries_from_total_buffer(self, keys):
        """Iterate over keys when the entire index is parsed."""
        keys = keys.intersection(self._keys)
        if self.node_ref_lists:
            for key in keys:
                value, node_refs = self._nodes[key]
                yield self, key, value, node_refs
        else:
            for key in keys:
                yield self, key, self._nodes[key]

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable as per iter_all_entries, but restricted to the
            keys supplied. No additional keys will be returned, and every
            key supplied that is in the index will be returned.
        """
        keys = set(keys)
        if not keys:
            return []
        if self._size is None and self._nodes is None:
            self._buffer_all()

        # We fit about 20 keys per minimum-read (4K), so if we are looking for
        # more than 1/20th of the index its likely (assuming homogenous key
        # spread) that we'll read the entire index. If we're going to do that,
        # buffer the whole thing. A better analysis might take key spread into
        # account - but B+Tree indices are better anyway.
        # We could look at all data read, and use a threshold there, which will
        # trigger on ancestry walks, but that is not yet fully mapped out.
        if self._nodes is None and len(keys) * 20 > self.key_count():
            self._buffer_all()
        if self._nodes is not None:
            return self._iter_entries_from_total_buffer(keys)
        else:
            return (result[1] for result in bisect_multi_bytes(
                self._lookup_keys_via_location, self._size, keys))

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
        keys = set(keys)
        if not keys:
            return
        # load data - also finds key lengths
        if self._nodes is None:
            self._buffer_all()
        if self._key_length == 1:
            for key in keys:
                # sanity check
                if key[0] is None:
                    raise errors.BadIndexKey(key)
                if len(key) != self._key_length:
                    raise errors.BadIndexKey(key)
                if self.node_ref_lists:
                    value, node_refs = self._nodes[key]
                    yield self, key, value, node_refs
                else:
                    yield self, key, self._nodes[key]
            return
        nodes_by_key = self._get_nodes_by_key()
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
        
        For GraphIndex the estimate is exact.
        """
        if self._key_count is None:
            self._read_and_parse([_HEADER_READV])
        return self._key_count

    def _lookup_keys_via_location(self, location_keys):
        """Public interface for implementing bisection.

        If _buffer_all has been called, then all the data for the index is in
        memory, and this method should not be called, as it uses a separate
        cache because it cannot pre-resolve all indices, which buffer_all does
        for performance.

        :param location_keys: A list of location(byte offset), key tuples.
        :return: A list of (location_key, result) tuples as expected by
            bzrlib.bisect_multi.bisect_multi_bytes.
        """
        # Possible improvements:
        #  - only bisect lookup each key once
        #  - sort the keys first, and use that to reduce the bisection window
        # ----- 
        # this progresses in three parts:
        # read data
        # parse it
        # attempt to answer the question from the now in memory data.
        # build the readv request
        # for each location, ask for 800 bytes - much more than rows we've seen
        # anywhere.
        readv_ranges = []
        for location, key in location_keys:
            # can we answer from cache?
            if self._bisect_nodes and key in self._bisect_nodes:
                # We have the key parsed.
                continue
            index = self._parsed_key_index(key)
            if (len(self._parsed_key_map) and 
                self._parsed_key_map[index][0] <= key and
                (self._parsed_key_map[index][1] >= key or
                 # end of the file has been parsed
                 self._parsed_byte_map[index][1] == self._size)):
                # the key has been parsed, so no lookup is needed even if its
                # not present.
                continue
            # - if we have examined this part of the file already - yes
            index = self._parsed_byte_index(location)
            if (len(self._parsed_byte_map) and 
                self._parsed_byte_map[index][0] <= location and
                self._parsed_byte_map[index][1] > location):
                # the byte region has been parsed, so no read is needed.
                continue
            length = 800
            if location + length > self._size:
                length = self._size - location
            # todo, trim out parsed locations.
            if length > 0:
                readv_ranges.append((location, length))
        # read the header if needed
        if self._bisect_nodes is None:
            readv_ranges.append(_HEADER_READV)
        self._read_and_parse(readv_ranges)
        result = []
        if self._nodes is not None:
            # _read_and_parse triggered a _buffer_all because we requested the
            # whole data range
            for location, key in location_keys:
                if key not in self._nodes: # not present
                    result.append(((location, key), False))
                elif self.node_ref_lists:
                    value, refs = self._nodes[key]
                    result.append(((location, key),
                        (self, key, value, refs)))
                else:
                    result.append(((location, key),
                        (self, key, self._nodes[key])))
            return result
        # generate results:
        #  - figure out <, >, missing, present
        #  - result present references so we can return them.
        # keys that we cannot answer until we resolve references
        pending_references = []
        pending_locations = set()
        for location, key in location_keys:
            # can we answer from cache?
            if key in self._bisect_nodes:
                # the key has been parsed, so no lookup is needed
                if self.node_ref_lists:
                    # the references may not have been all parsed.
                    value, refs = self._bisect_nodes[key]
                    wanted_locations = []
                    for ref_list in refs:
                        for ref in ref_list:
                            if ref not in self._keys_by_offset:
                                wanted_locations.append(ref)
                    if wanted_locations:
                        pending_locations.update(wanted_locations)
                        pending_references.append((location, key))
                        continue
                    result.append(((location, key), (self, key,
                        value, self._resolve_references(refs))))
                else:
                    result.append(((location, key),
                        (self, key, self._bisect_nodes[key])))
                continue
            else:
                # has the region the key should be in, been parsed?
                index = self._parsed_key_index(key)
                if (self._parsed_key_map[index][0] <= key and
                    (self._parsed_key_map[index][1] >= key or
                     # end of the file has been parsed
                     self._parsed_byte_map[index][1] == self._size)):
                    result.append(((location, key), False))
                    continue
            # no, is the key above or below the probed location:
            # get the range of the probed & parsed location
            index = self._parsed_byte_index(location)
            # if the key is below the start of the range, its below
            if key < self._parsed_key_map[index][0]:
                direction = -1
            else:
                direction = +1
            result.append(((location, key), direction))
        readv_ranges = []
        # lookup data to resolve references
        for location in pending_locations:
            length = 800
            if location + length > self._size:
                length = self._size - location
            # TODO: trim out parsed locations (e.g. if the 800 is into the
            # parsed region trim it, and dont use the adjust_for_latency
            # facility)
            if length > 0:
                readv_ranges.append((location, length))
        self._read_and_parse(readv_ranges)
        if self._nodes is not None:
            # The _read_and_parse triggered a _buffer_all, grab the data and
            # return it
            for location, key in pending_references:
                value, refs = self._nodes[key]
                result.append(((location, key), (self, key, value, refs)))
            return result
        for location, key in pending_references:
            # answer key references we had to look-up-late.
            value, refs = self._bisect_nodes[key]
            result.append(((location, key), (self, key,
                value, self._resolve_references(refs))))
        return result

    def _parse_header_from_bytes(self, bytes):
        """Parse the header from a region of bytes.

        :param bytes: The data to parse.
        :return: An offset, data tuple such as readv yields, for the unparsed
            data. (which may length 0).
        """
        signature = bytes[0:len(self._signature())]
        if not signature == self._signature():
            raise errors.BadIndexFormatSignature(self._name, GraphIndex)
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
        # calculate the bytes we have processed
        header_end = (len(signature) + len(lines[0]) + len(lines[1]) +
            len(lines[2]) + 3)
        self._parsed_bytes(0, None, header_end, None)
        # setup parsing state
        self._expected_elements = 3 + self._key_length
        # raw data keyed by offset
        self._keys_by_offset = {}
        # keys with the value and node references
        self._bisect_nodes = {}
        return header_end, bytes[header_end:]

    def _parse_region(self, offset, data):
        """Parse node data returned from a readv operation.

        :param offset: The byte offset the data starts at.
        :param data: The data to parse.
        """
        # trim the data.
        # end first:
        end = offset + len(data)
        high_parsed = offset
        while True:
            # Trivial test - if the current index's end is within the
            # low-matching parsed range, we're done.
            index = self._parsed_byte_index(high_parsed)
            if end < self._parsed_byte_map[index][1]:
                return
            # print "[%d:%d]" % (offset, end), \
            #     self._parsed_byte_map[index:index + 2]
            high_parsed, last_segment = self._parse_segment(
                offset, data, end, index)
            if last_segment:
                return

    def _parse_segment(self, offset, data, end, index):
        """Parse one segment of data.

        :param offset: Where 'data' begins in the file.
        :param data: Some data to parse a segment of.
        :param end: Where data ends
        :param index: The current index into the parsed bytes map.
        :return: True if the parsed segment is the last possible one in the
            range of data.
        :return: high_parsed_byte, last_segment.
            high_parsed_byte is the location of the highest parsed byte in this
            segment, last_segment is True if the parsed segment is the last
            possible one in the data block.
        """
        # default is to use all data
        trim_end = None
        # accomodate overlap with data before this.
        if offset < self._parsed_byte_map[index][1]:
            # overlaps the lower parsed region
            # skip the parsed data
            trim_start = self._parsed_byte_map[index][1] - offset
            # don't trim the start for \n
            start_adjacent = True
        elif offset == self._parsed_byte_map[index][1]:
            # abuts the lower parsed region
            # use all data
            trim_start = None
            # do not trim anything
            start_adjacent = True
        else:
            # does not overlap the lower parsed region
            # use all data
            trim_start = None
            # but trim the leading \n
            start_adjacent = False
        if end == self._size:
            # lines up to the end of all data:
            # use it all
            trim_end = None
            # do not strip to the last \n
            end_adjacent = True
            last_segment = True
        elif index + 1 == len(self._parsed_byte_map):
            # at the end of the parsed data
            # use it all
            trim_end = None
            # but strip to the last \n
            end_adjacent = False
            last_segment = True
        elif end == self._parsed_byte_map[index + 1][0]:
            # buts up against the next parsed region
            # use it all
            trim_end = None
            # do not strip to the last \n
            end_adjacent = True
            last_segment = True
        elif end > self._parsed_byte_map[index + 1][0]:
            # overlaps into the next parsed region
            # only consider the unparsed data
            trim_end = self._parsed_byte_map[index + 1][0] - offset
            # do not strip to the last \n as we know its an entire record
            end_adjacent = True
            last_segment = end < self._parsed_byte_map[index + 1][1]
        else:
            # does not overlap into the next region
            # use it all
            trim_end = None
            # but strip to the last \n
            end_adjacent = False
            last_segment = True
        # now find bytes to discard if needed
        if not start_adjacent:
            # work around python bug in rfind
            if trim_start is None:
                trim_start = data.find('\n') + 1
            else:
                trim_start = data.find('\n', trim_start) + 1
            if not (trim_start != 0):
                raise AssertionError('no \n was present')
            # print 'removing start', offset, trim_start, repr(data[:trim_start])
        if not end_adjacent:
            # work around python bug in rfind
            if trim_end is None:
                trim_end = data.rfind('\n') + 1
            else:
                trim_end = data.rfind('\n', None, trim_end) + 1
            if not (trim_end != 0):
                raise AssertionError('no \n was present')
            # print 'removing end', offset, trim_end, repr(data[trim_end:])
        # adjust offset and data to the parseable data.
        trimmed_data = data[trim_start:trim_end]
        if not (trimmed_data):
            raise AssertionError('read unneeded data [%d:%d] from [%d:%d]' 
                % (trim_start, trim_end, offset, offset + len(data)))
        if trim_start:
            offset += trim_start
        # print "parsing", repr(trimmed_data)
        # splitlines mangles the \r delimiters.. don't use it.
        lines = trimmed_data.split('\n')
        del lines[-1]
        pos = offset
        first_key, last_key, nodes, _ = self._parse_lines(lines, pos)
        for key, value in nodes:
            self._bisect_nodes[key] = value
        self._parsed_bytes(offset, first_key,
            offset + len(trimmed_data), last_key)
        return offset + len(trimmed_data), last_segment

    def _parse_lines(self, lines, pos):
        key = None
        first_key = None
        trailers = 0
        nodes = []
        for line in lines:
            if line == '':
                # must be at the end
                if self._size:
                    if not (self._size == pos + 1):
                        raise AssertionError("%s %s" % (self._size, pos))
                trailers += 1
                continue
            elements = line.split('\0')
            if len(elements) != self._expected_elements:
                raise errors.BadIndexData(self)
            # keys are tuples. Each element is a string that may occur many
            # times, so we intern them to save space. AB, RC, 200807
            key = tuple([intern(element) for element in elements[:self._key_length]])
            if first_key is None:
                first_key = key
            absent, references, value = elements[-3:]
            ref_lists = []
            for ref_string in references.split('\t'):
                ref_lists.append(tuple([
                    int(ref) for ref in ref_string.split('\r') if ref
                    ]))
            ref_lists = tuple(ref_lists)
            self._keys_by_offset[pos] = (key, absent, ref_lists, value)
            pos += len(line) + 1 # +1 for the \n
            if absent:
                continue
            if self.node_ref_lists:
                node_value = (value, ref_lists)
            else:
                node_value = value
            nodes.append((key, node_value))
            # print "parsed ", key
        return first_key, key, nodes, trailers

    def _parsed_bytes(self, start, start_key, end, end_key):
        """Mark the bytes from start to end as parsed.

        Calling self._parsed_bytes(1,2) will mark one byte (the one at offset
        1) as parsed.

        :param start: The start of the parsed region.
        :param end: The end of the parsed region.
        """
        index = self._parsed_byte_index(start)
        new_value = (start, end)
        new_key = (start_key, end_key)
        if index == -1:
            # first range parsed is always the beginning.
            self._parsed_byte_map.insert(index, new_value)
            self._parsed_key_map.insert(index, new_key)
            return
        # four cases:
        # new region
        # extend lower region
        # extend higher region
        # combine two regions
        if (index + 1 < len(self._parsed_byte_map) and
            self._parsed_byte_map[index][1] == start and
            self._parsed_byte_map[index + 1][0] == end):
            # combine two regions
            self._parsed_byte_map[index] = (self._parsed_byte_map[index][0],
                self._parsed_byte_map[index + 1][1])
            self._parsed_key_map[index] = (self._parsed_key_map[index][0],
                self._parsed_key_map[index + 1][1])
            del self._parsed_byte_map[index + 1]
            del self._parsed_key_map[index + 1]
        elif self._parsed_byte_map[index][1] == start:
            # extend the lower entry
            self._parsed_byte_map[index] = (
                self._parsed_byte_map[index][0], end)
            self._parsed_key_map[index] = (
                self._parsed_key_map[index][0], end_key)
        elif (index + 1 < len(self._parsed_byte_map) and
            self._parsed_byte_map[index + 1][0] == end):
            # extend the higher entry
            self._parsed_byte_map[index + 1] = (
                start, self._parsed_byte_map[index + 1][1])
            self._parsed_key_map[index + 1] = (
                start_key, self._parsed_key_map[index + 1][1])
        else:
            # new entry
            self._parsed_byte_map.insert(index + 1, new_value)
            self._parsed_key_map.insert(index + 1, new_key)

    def _read_and_parse(self, readv_ranges):
        """Read the the ranges and parse the resulting data.

        :param readv_ranges: A prepared readv range list.
        """
        if not readv_ranges:
            return
        if self._nodes is None and self._bytes_read * 2 >= self._size:
            # We've already read more than 50% of the file and we are about to
            # request more data, just _buffer_all() and be done
            self._buffer_all()
            return

        readv_data = self._transport.readv(self._name, readv_ranges, True,
            self._size)
        # parse
        for offset, data in readv_data:
            self._bytes_read += len(data)
            if offset == 0 and len(data) == self._size:
                # We read the whole range, most likely because the
                # Transport upcast our readv ranges into one long request
                # for enough total data to grab the whole index.
                self._buffer_all(StringIO(data))
                return
            if self._bisect_nodes is None:
                # this must be the start
                if not (offset == 0):
                    raise AssertionError()
                offset, data = self._parse_header_from_bytes(data)
            # print readv_ranges, "[%d:%d]" % (offset, offset + len(data))
            self._parse_region(offset, data)

    def _signature(self):
        """The file signature for this index type."""
        return _SIGNATURE

    def validate(self):
        """Validate that everything in the index can be accessed."""
        # iter_all validates completely at the moment, so just do that.
        for node in self.iter_all_entries():
            pass


class CombinedGraphIndex(object):
    """A GraphIndex made up from smaller GraphIndices.
    
    The backing indices must implement GraphIndex, and are presumed to be
    static data.

    Queries against the combined index will be made against the first index,
    and then the second and so on. The order of index's can thus influence
    performance significantly. For example, if one index is on local disk and a
    second on a remote server, the local disk index should be before the other
    in the index list.
    """

    def __init__(self, indices, reload_func=None):
        """Create a CombinedGraphIndex backed by indices.

        :param indices: An ordered list of indices to query for data.
        :param reload_func: A function to call if we find we are missing an
            index. Should have the form reload_func() => True/False to indicate
            if reloading actually changed anything.
        """
        self._indices = indices
        self._reload_func = reload_func

    def __repr__(self):
        return "%s(%s)" % (
                self.__class__.__name__,
                ', '.join(map(repr, self._indices)))

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revision_ids):
        """See graph._StackedParentsProvider.get_parents.
        
        This implementation thunks the graph.Graph.get_parents api across to
        GraphIndex.

        :param revision_ids: An iterable of graph keys for this graph.
        :return: A list of parent details for each key in revision_ids.
            Each parent details will be one of:
             * None when the key was missing
             * (NULL_REVISION,) when the key has no parents.
             * (parent_key, parent_key...) otherwise.
        """
        parent_map = self.get_parent_map(revision_ids)
        return [parent_map.get(r, None) for r in revision_ids]

    def get_parent_map(self, keys):
        """See graph._StackedParentsProvider.get_parent_map"""
        search_keys = set(keys)
        if NULL_REVISION in search_keys:
            search_keys.discard(NULL_REVISION)
            found_parents = {NULL_REVISION:[]}
        else:
            found_parents = {}
        for index, key, value, refs in self.iter_entries(search_keys):
            parents = refs[0]
            if not parents:
                parents = (NULL_REVISION,)
            found_parents[key] = parents
        return found_parents

    has_key = _has_key_from_parent_map

    def insert_index(self, pos, index):
        """Insert a new index in the list of indices to query.

        :param pos: The position to insert the index.
        :param index: The index to insert.
        """
        self._indices.insert(pos, index)

    def iter_all_entries(self):
        """Iterate over all keys within the index

        Duplicate keys across child indices are presumed to have the same
        value and are only reported once.

        :return: An iterable of (index, key, reference_lists, value).
            There is no defined order for the result iteration - it will be in
            the most efficient order for the index.
        """
        seen_keys = set()
        while True:
            try:
                for index in self._indices:
                    for node in index.iter_all_entries():
                        if node[1] not in seen_keys:
                            yield node
                            seen_keys.add(node[1])
                return
            except errors.NoSuchFile:
                self._reload_or_raise()

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        Duplicate keys across child indices are presumed to have the same
        value and are only reported once.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (index, key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index.
        """
        keys = set(keys)
        while True:
            try:
                for index in self._indices:
                    if not keys:
                        return
                    for node in index.iter_entries(keys):
                        keys.remove(node[1])
                        yield node
                return
            except errors.NoSuchFile:
                self._reload_or_raise()

    def iter_entries_prefix(self, keys):
        """Iterate over keys within the index using prefix matching.

        Duplicate keys across child indices are presumed to have the same
        value and are only reported once.

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
        keys = set(keys)
        if not keys:
            return
        seen_keys = set()
        while True:
            try:
                for index in self._indices:
                    for node in index.iter_entries_prefix(keys):
                        if node[1] in seen_keys:
                            continue
                        seen_keys.add(node[1])
                        yield node
                return
            except errors.NoSuchFile:
                self._reload_or_raise()

    def key_count(self):
        """Return an estimate of the number of keys in this index.

        For CombinedGraphIndex this is approximated by the sum of the keys of
        the child indices. As child indices may have duplicate keys this can
        have a maximum error of the number of child indices * largest number of
        keys in any index.
        """
        while True:
            try:
                return sum((index.key_count() for index in self._indices), 0)
            except errors.NoSuchFile:
                self._reload_or_raise()

    missing_keys = _missing_keys_from_parent_map

    def _reload_or_raise(self):
        """We just got a NoSuchFile exception.

        Try to reload the indices, if it fails, just raise the current
        exception.
        """
        if self._reload_func is None:
            raise
        exc_type, exc_value, exc_traceback = sys.exc_info()
        trace.mutter('Trying to reload after getting exception: %s',
                     exc_value)
        if not self._reload_func():
            # We tried to reload, but nothing changed, so we fail anyway
            trace.mutter('_reload_func indicated nothing has changed.'
                         ' Raising original exception.')
            raise exc_type, exc_value, exc_traceback

    def validate(self):
        """Validate that everything in the index can be accessed."""
        while True:
            try:
                for index in self._indices:
                    index.validate()
                return
            except errors.NoSuchFile:
                self._reload_or_raise()


class InMemoryGraphIndex(GraphIndexBuilder):
    """A GraphIndex which operates entirely out of memory and is mutable.

    This is designed to allow the accumulation of GraphIndex entries during a
    single write operation, where the accumulated entries need to be immediately
    available - for example via a CombinedGraphIndex.
    """

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

    def iter_all_entries(self):
        """Iterate over all keys within the index

        :return: An iterable of (index, key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (in this case dictionary hash order).
        """
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(3,
                "iter_all_entries scales with size of history.")
        if self.reference_lists:
            for key, (absent, references, value) in self._nodes.iteritems():
                if not absent:
                    yield self, key, value, references
        else:
            for key, (absent, references, value) in self._nodes.iteritems():
                if not absent:
                    yield self, key, value

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (index, key, value, reference_lists). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (keys iteration order in this case).
        """
        keys = set(keys)
        if self.reference_lists:
            for key in keys.intersection(self._keys):
                node = self._nodes[key]
                if not node[0]:
                    yield self, key, node[2], node[1]
        else:
            for key in keys.intersection(self._keys):
                node = self._nodes[key]
                if not node[0]:
                    yield self, key, node[2]

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
        if self._key_length == 1:
            for key in keys:
                # sanity check
                if key[0] is None:
                    raise errors.BadIndexKey(key)
                if len(key) != self._key_length:
                    raise errors.BadIndexKey(key)
                node = self._nodes[key]
                if node[0]:
                    continue 
                if self.reference_lists:
                    yield self, key, node[2], node[1]
                else:
                    yield self, key, node[2]
            return
        nodes_by_key = self._get_nodes_by_key()
        for key in keys:
            # sanity check
            if key[0] is None:
                raise errors.BadIndexKey(key)
            if len(key) != self._key_length:
                raise errors.BadIndexKey(key)
            # find what it refers to:
            key_dict = nodes_by_key
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

    def key_count(self):
        """Return an estimate of the number of keys in this index.
        
        For InMemoryGraphIndex the estimate is exact.
        """
        return len(self._keys)

    def validate(self):
        """In memory index's have no known corruption at the moment."""


class GraphIndexPrefixAdapter(object):
    """An adapter between GraphIndex with different key lengths.

    Queries against this will emit queries against the adapted Graph with the
    prefix added, queries for all items use iter_entries_prefix. The returned
    nodes will have their keys and node references adjusted to remove the 
    prefix. Finally, an add_nodes_callback can be supplied - when called the
    nodes and references being added will have prefix prepended.
    """

    def __init__(self, adapted, prefix, missing_key_length,
        add_nodes_callback=None):
        """Construct an adapter against adapted with prefix."""
        self.adapted = adapted
        self.prefix_key = prefix + (None,)*missing_key_length
        self.prefix = prefix
        self.prefix_len = len(prefix)
        self.add_nodes_callback = add_nodes_callback

    def add_nodes(self, nodes):
        """Add nodes to the index.

        :param nodes: An iterable of (key, node_refs, value) entries to add.
        """
        # save nodes in case its an iterator
        nodes = tuple(nodes)
        translated_nodes = []
        try:
            # Add prefix_key to each reference node_refs is a tuple of tuples,
            # so split it apart, and add prefix_key to the internal reference
            for (key, value, node_refs) in nodes:
                adjusted_references = (
                    tuple(tuple(self.prefix + ref_node for ref_node in ref_list)
                        for ref_list in node_refs))
                translated_nodes.append((self.prefix + key, value,
                    adjusted_references))
        except ValueError:
            # XXX: TODO add an explicit interface for getting the reference list
            # status, to handle this bit of user-friendliness in the API more 
            # explicitly.
            for (key, value) in nodes:
                translated_nodes.append((self.prefix + key, value))
        self.add_nodes_callback(translated_nodes)

    def add_node(self, key, value, references=()):
        """Add a node to the index.

        :param key: The key. keys are non-empty tuples containing
            as many whitespace-free utf8 bytestrings as the key length
            defined for this index.
        :param references: An iterable of iterables of keys. Each is a
            reference to another key.
        :param value: The value to associate with the key. It may be any
            bytes as long as it does not contain \0 or \n.
        """
        self.add_nodes(((key, value, references), ))

    def _strip_prefix(self, an_iter):
        """Strip prefix data from nodes and return it."""
        for node in an_iter:
            # cross checks
            if node[1][:self.prefix_len] != self.prefix:
                raise errors.BadIndexData(self)
            for ref_list in node[3]:
                for ref_node in ref_list:
                    if ref_node[:self.prefix_len] != self.prefix:
                        raise errors.BadIndexData(self)
            yield node[0], node[1][self.prefix_len:], node[2], (
                tuple(tuple(ref_node[self.prefix_len:] for ref_node in ref_list)
                for ref_list in node[3]))

    def iter_all_entries(self):
        """Iterate over all keys within the index

        iter_all_entries is implemented against the adapted index using
        iter_entries_prefix.

        :return: An iterable of (index, key, reference_lists, value). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (in this case dictionary hash order).
        """
        return self._strip_prefix(self.adapted.iter_entries_prefix([self.prefix_key]))

    def iter_entries(self, keys):
        """Iterate over keys within the index.

        :param keys: An iterable providing the keys to be retrieved.
        :return: An iterable of (index, key, value, reference_lists). There is no
            defined order for the result iteration - it will be in the most
            efficient order for the index (keys iteration order in this case).
        """
        return self._strip_prefix(self.adapted.iter_entries(
            self.prefix + key for key in keys))

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
        return self._strip_prefix(self.adapted.iter_entries_prefix(
            self.prefix + key for key in keys))

    def key_count(self):
        """Return an estimate of the number of keys in this index.
        
        For GraphIndexPrefixAdapter this is relatively expensive - key
        iteration with the prefix is done.
        """
        return len(list(self.iter_all_entries()))

    def validate(self):
        """Call the adapted's validate."""
        self.adapted.validate()
