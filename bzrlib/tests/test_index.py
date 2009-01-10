# Copyright (C) 2007 Canonical Ltd
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

"""Tests for indices."""

from bzrlib import errors
from bzrlib.index import *
from bzrlib.tests import TestCaseWithMemoryTransport
from bzrlib.transport import get_transport


class TestGraphIndexBuilder(TestCaseWithMemoryTransport):

    def test_build_index_empty(self):
        builder = GraphIndexBuilder()
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=0\n\n",
            contents)

    def test_build_index_empty_two_element_keys(self):
        builder = GraphIndexBuilder(key_elements=2)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=0\n\n",
            contents)

    def test_build_index_one_reference_list_empty(self):
        builder = GraphIndexBuilder(reference_lists=1)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=0\n\n",
            contents)

    def test_build_index_two_reference_list_empty(self):
        builder = GraphIndexBuilder(reference_lists=2)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=0\n\n",
            contents)

    def test_build_index_one_node_no_refs(self):
        builder = GraphIndexBuilder()
        builder.add_node(('akey', ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            "akey\x00\x00\x00data\n\n", contents)

    def test_build_index_one_node_no_refs_accepts_empty_reflist(self):
        builder = GraphIndexBuilder()
        builder.add_node(('akey', ), 'data', ())
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            "akey\x00\x00\x00data\n\n", contents)

    def test_build_index_one_node_2_element_keys(self):
        # multipart keys are separated by \x00 - because they are fixed length,
        # not variable this does not cause any issues, and seems clearer to the
        # author.
        builder = GraphIndexBuilder(key_elements=2)
        builder.add_node(('akey', 'secondpart'), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=1\n"
            "akey\x00secondpart\x00\x00\x00data\n\n", contents)

    def test_add_node_empty_value(self):
        builder = GraphIndexBuilder()
        builder.add_node(('akey', ), '')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=1\n"
            "akey\x00\x00\x00\n\n", contents)

    def test_build_index_nodes_sorted(self):
        # the highest sorted node comes first.
        builder = GraphIndexBuilder()
        # use three to have a good chance of glitching dictionary hash
        # lookups etc. Insert in randomish order that is not correct
        # and not the reverse of the correct order.
        builder.add_node(('2002', ), 'data')
        builder.add_node(('2000', ), 'data')
        builder.add_node(('2001', ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=1\nlen=3\n"
            "2000\x00\x00\x00data\n"
            "2001\x00\x00\x00data\n"
            "2002\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_2_element_key_nodes_sorted(self):
        # multiple element keys are sorted first-key, second-key.
        builder = GraphIndexBuilder(key_elements=2)
        # use three values of each key element, to have a good chance of
        # glitching dictionary hash lookups etc. Insert in randomish order that
        # is not correct and not the reverse of the correct order.
        builder.add_node(('2002', '2002'), 'data')
        builder.add_node(('2002', '2000'), 'data')
        builder.add_node(('2002', '2001'), 'data')
        builder.add_node(('2000', '2002'), 'data')
        builder.add_node(('2000', '2000'), 'data')
        builder.add_node(('2000', '2001'), 'data')
        builder.add_node(('2001', '2002'), 'data')
        builder.add_node(('2001', '2000'), 'data')
        builder.add_node(('2001', '2001'), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=0\nkey_elements=2\nlen=9\n"
            "2000\x002000\x00\x00\x00data\n"
            "2000\x002001\x00\x00\x00data\n"
            "2000\x002002\x00\x00\x00data\n"
            "2001\x002000\x00\x00\x00data\n"
            "2001\x002001\x00\x00\x00data\n"
            "2001\x002002\x00\x00\x00data\n"
            "2002\x002000\x00\x00\x00data\n"
            "2002\x002001\x00\x00\x00data\n"
            "2002\x002002\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_reference_lists_are_included_one(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node(('key', ), 'data', ([], ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            "key\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_reference_lists_with_2_element_keys(self):
        builder = GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.add_node(('key', 'key2'), 'data', ([], ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=2\nlen=1\n"
            "key\x00key2\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_reference_lists_are_included_two(self):
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node(('key', ), 'data', ([], []))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=1\n"
            "key\x00\x00\t\x00data\n"
            "\n", contents)

    def test_node_references_are_byte_offsets(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node(('reference', ), 'data', ([], ))
        builder.add_node(('key', ), 'data', ([('reference', )], ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=2\n"
            "key\x00\x0072\x00data\n"
            "reference\x00\x00\x00data\n"
            "\n", contents)

    def test_node_references_are_cr_delimited(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node(('reference', ), 'data', ([], ))
        builder.add_node(('reference2', ), 'data', ([], ))
        builder.add_node(('key', ), 'data', ([('reference', ), ('reference2', )], ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=3\n"
            "key\x00\x00077\r094\x00data\n"
            "reference\x00\x00\x00data\n"
            "reference2\x00\x00\x00data\n"
            "\n", contents)

    def test_multiple_reference_lists_are_tab_delimited(self):
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node(('keference', ), 'data', ([], []))
        builder.add_node(('rey', ), 'data', ([('keference', )], [('keference', )]))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=2\n"
            "keference\x00\x00\t\x00data\n"
            "rey\x00\x0059\t59\x00data\n"
            "\n", contents)

    def test_add_node_referencing_missing_key_makes_absent(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node(('rey', ), 'data', ([('beference', ), ('aeference2', )], ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            "aeference2\x00a\x00\x00\n"
            "beference\x00a\x00\x00\n"
            "rey\x00\x00074\r059\x00data\n"
            "\n", contents)

    def test_node_references_three_digits(self):
        # test the node digit expands as needed.
        builder = GraphIndexBuilder(reference_lists=1)
        references = [(str(val), ) for val in reversed(range(9))]
        builder.add_node(('2-key', ), '', (references, ))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=1\nkey_elements=1\nlen=1\n"
            "0\x00a\x00\x00\n"
            "1\x00a\x00\x00\n"
            "2\x00a\x00\x00\n"
            "2-key\x00\x00151\r145\r139\r133\r127\r121\r071\r065\r059\x00\n"
            "3\x00a\x00\x00\n"
            "4\x00a\x00\x00\n"
            "5\x00a\x00\x00\n"
            "6\x00a\x00\x00\n"
            "7\x00a\x00\x00\n"
            "8\x00a\x00\x00\n"
            "\n", contents)

    def test_absent_has_no_reference_overhead(self):
        # the offsets after an absent record should be correct when there are
        # >1 reference lists.
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node(('parent', ), '', ([('aail', ), ('zther', )], []))
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual(
            "Bazaar Graph Index 1\nnode_ref_lists=2\nkey_elements=1\nlen=1\n"
            "aail\x00a\x00\x00\n"
            "parent\x00\x0059\r84\t\x00\n"
            "zther\x00a\x00\x00\n"
            "\n", contents)

    def test_add_node_bad_key(self):
        builder = GraphIndexBuilder()
        for bad_char in '\t\n\x0b\x0c\r\x00 ':
            self.assertRaises(errors.BadIndexKey, builder.add_node,
                ('a%skey' % bad_char, ), 'data')
        self.assertRaises(errors.BadIndexKey, builder.add_node,
                ('', ), 'data')
        self.assertRaises(errors.BadIndexKey, builder.add_node,
                'not-a-tuple', 'data')
        # not enough length
        self.assertRaises(errors.BadIndexKey, builder.add_node,
                (), 'data')
        # too long
        self.assertRaises(errors.BadIndexKey, builder.add_node,
                ('primary', 'secondary'), 'data')
        # secondary key elements get checked too:
        builder = GraphIndexBuilder(key_elements=2)
        for bad_char in '\t\n\x0b\x0c\r\x00 ':
            self.assertRaises(errors.BadIndexKey, builder.add_node,
                ('prefix', 'a%skey' % bad_char), 'data')

    def test_add_node_bad_data(self):
        builder = GraphIndexBuilder()
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data\naa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data\x00aa')

    def test_add_node_bad_mismatched_ref_lists_length(self):
        builder = GraphIndexBuilder()
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa', ([], ))
        builder = GraphIndexBuilder(reference_lists=1)
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa', (), )
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa', ([], []))
        builder = GraphIndexBuilder(reference_lists=2)
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa', ([], ))
        self.assertRaises(errors.BadIndexValue, builder.add_node, ('akey', ),
            'data aa', ([], [], []))

    def test_add_node_bad_key_in_reference_lists(self):
        # first list, first key - trivial
        builder = GraphIndexBuilder(reference_lists=1)
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', ([('a key', )], ))
        # references keys must be tuples too
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', (['not-a-tuple'], ))
        # not enough length
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', ([()], ))
        # too long
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', ([('primary', 'secondary')], ))
        # need to check more than the first key in the list
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', ([('agoodkey', ), ('that is a bad key', )], ))
        # and if there is more than one list it should be getting checked
        # too
        builder = GraphIndexBuilder(reference_lists=2)
        self.assertRaises(errors.BadIndexKey, builder.add_node, ('akey', ),
            'data aa', ([], ['a bad key']))

    def test_add_duplicate_key(self):
        builder = GraphIndexBuilder()
        builder.add_node(('key', ), 'data')
        self.assertRaises(errors.BadIndexDuplicateKey, builder.add_node, ('key', ),
            'data')

    def test_add_duplicate_key_2_elements(self):
        builder = GraphIndexBuilder(key_elements=2)
        builder.add_node(('key', 'key'), 'data')
        self.assertRaises(errors.BadIndexDuplicateKey, builder.add_node,
            ('key', 'key'), 'data')

    def test_add_key_after_referencing_key(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node(('key', ), 'data', ([('reference', )], ))
        builder.add_node(('reference', ), 'data', ([],))

    def test_add_key_after_referencing_key_2_elements(self):
        builder = GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.add_node(('k', 'ey'), 'data', ([('reference', 'tokey')], ))
        builder.add_node(('reference', 'tokey'), 'data', ([],))

    def test_set_optimize(self):
        builder = GraphIndexBuilder(reference_lists=1, key_elements=2)
        builder.set_optimize(for_size=True)
        self.assertTrue(builder._optimize_for_size)
        builder.set_optimize(for_size=False)
        self.assertFalse(builder._optimize_for_size)


class TestGraphIndex(TestCaseWithMemoryTransport):

    def make_key(self, number):
        return (str(number) + 'X'*100,)

    def make_value(self, number):
            return str(number) + 'Y'*100

    def make_nodes(self, count=64):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        nodes = []
        for counter in range(count):
            nodes.append((self.make_key(counter), self.make_value(counter), ()))
        return nodes

    def make_index(self, ref_lists=0, key_elements=1, nodes=[]):
        builder = GraphIndexBuilder(ref_lists, key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = get_transport('trace+' + self.get_url())
        size = trans.put_file('index', stream)
        return GraphIndex(trans, 'index', size)

    def test_open_bad_index_no_error(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index = GraphIndex(trans, 'name', 13)

    def test_open_sets_parsed_map_empty(self):
        index = self.make_index()
        self.assertEqual([], index._parsed_byte_map)
        self.assertEqual([], index._parsed_key_map)

    def test_key_count_buffers(self):
        index = self.make_index(nodes=self.make_nodes(2))
        # reset the transport log
        del index._transport._activity[:]
        self.assertEqual(2, index.key_count())
        # We should have requested reading the header bytes
        self.assertEqual([
            ('readv', 'index', [(0, 200)], True, index._size),
            ],
            index._transport._activity)
        # And that should have been enough to trigger reading the whole index
        # with buffering
        self.assertIsNot(None, index._nodes)

    def test_lookup_key_via_location_buffers(self):
        index = self.make_index()
        # reset the transport log
        del index._transport._activity[:]
        # do a _lookup_keys_via_location call for the middle of the file, which
        # is what bisection uses.
        result = index._lookup_keys_via_location(
            [(index._size // 2, ('missing', ))])
        # this should have asked for a readv request, with adjust_for_latency,
        # and two regions: the header, and half-way into the file.
        self.assertEqual([
            ('readv', 'index', [(30, 30), (0, 200)], True, 60),
            ],
            index._transport._activity)
        # and the result should be that the key cannot be present, because this
        # is a trivial index.
        self.assertEqual([((index._size // 2, ('missing', )), False)],
            result)
        # And this should have caused the file to be fully buffered
        self.assertIsNot(None, index._nodes)
        self.assertEqual([], index._parsed_byte_map)

    def test_first_lookup_key_via_location(self):
        # We need enough data so that the _HEADER_READV doesn't consume the
        # whole file. We always read 800 bytes for every key, and the local
        # transport natural expansion is 4096 bytes. So we have to have >8192
        # bytes or we will trigger "buffer_all".
        # We also want the 'missing' key to fall within the range that *did*
        # read
        nodes = []
        index = self.make_index(nodes=self.make_nodes(64))
        # reset the transport log
        del index._transport._activity[:]
        # do a _lookup_keys_via_location call for the middle of the file, which
        # is what bisection uses.
        start_lookup = index._size // 2
        result = index._lookup_keys_via_location(
            [(start_lookup, ('40missing', ))])
        # this should have asked for a readv request, with adjust_for_latency,
        # and two regions: the header, and half-way into the file.
        self.assertEqual([
            ('readv', 'index',
             [(start_lookup, 800), (0, 200)], True, index._size),
            ],
            index._transport._activity)
        # and the result should be that the key cannot be present, because this
        # is a trivial index.
        self.assertEqual([((start_lookup, ('40missing', )), False)],
            result)
        # And this should not have caused the file to be fully buffered
        self.assertIs(None, index._nodes)
        # And the regions of the file that have been parsed should be in the
        # parsed_byte_map and the parsed_key_map
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
                         index._parsed_key_map)

    def test_parsing_non_adjacent_data_trims(self):
        index = self.make_index(nodes=self.make_nodes(64))
        result = index._lookup_keys_via_location(
            [(index._size // 2, ('40', ))])
        # and the result should be that the key cannot be present, because key is
        # in the middle of the observed data from a 4K read - the smallest transport
        # will do today with this api.
        self.assertEqual([((index._size // 2, ('40', )), False)],
            result)
        # and we should have a parse map that includes the header and the
        # region that was parsed after trimming.
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
            index._parsed_key_map)

    def test_parsing_data_handles_parsed_contained_regions(self):
        # the following patten creates a parsed region that is wholly within a
        # single result from the readv layer:
        # .... single-read (readv-minimum-size) ...
        # which then trims the start and end so the parsed size is < readv
        # miniumum.
        # then a dual lookup (or a reference lookup for that matter) which
        # abuts or overlaps the parsed region on both sides will need to
        # discard the data in the middle, but parse the end as well.
        #
        # we test this by doing a single lookup to seed the data, then
        # a lookup for two keys that are present, and adjacent -
        # we except both to be found, and the parsed byte map to include the
        # locations of both keys.
        index = self.make_index(nodes=self.make_nodes(128))
        result = index._lookup_keys_via_location(
            [(index._size // 2, ('40', ))])
        # and we should have a parse map that includes the header and the
        # region that was parsed after trimming.
        self.assertEqual([(0, 4045), (11759, 15707)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(116)),
                          (self.make_key(35), self.make_key(51))],
            index._parsed_key_map)
        # now ask for two keys, right before and after the parsed region
        result = index._lookup_keys_via_location(
            [(11450, self.make_key(34)), (15707, self.make_key(52))])
        self.assertEqual([
            ((11450, self.make_key(34)),
             (index, self.make_key(34), self.make_value(34))),
            ((15707, self.make_key(52)),
             (index, self.make_key(52), self.make_value(52))),
            ],
            result)
        self.assertEqual([(0, 4045), (9889, 17993)], index._parsed_byte_map)

    def test_lookup_missing_key_answers_without_io_when_map_permits(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # lookup the keys in the middle of the file
        result =index._lookup_keys_via_location(
            [(index._size // 2, ('40', ))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
            index._parsed_key_map)
        # reset the transport log
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # not create a new transport request, and should return False (cannot
        # be in the index) - even when the byte location we ask for is outside
        # the parsed region
        result = index._lookup_keys_via_location(
            [(4000, ('40', ))])
        self.assertEqual([((4000, ('40', )), False)],
            result)
        self.assertEqual([], index._transport._activity)

    def test_lookup_present_key_answers_without_io_when_map_permits(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # lookup the keys in the middle of the file
        result =index._lookup_keys_via_location(
            [(index._size // 2, ('40', ))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
            index._parsed_key_map)
        # reset the transport log
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # not create a new transport request, and should return False (cannot
        # be in the index) - even when the byte location we ask for is outside
        # the parsed region
        # 
        result = index._lookup_keys_via_location([(4000, self.make_key(40))])
        self.assertEqual(
            [((4000, self.make_key(40)),
              (index, self.make_key(40), self.make_value(40)))],
            result)
        self.assertEqual([], index._transport._activity)

    def test_lookup_key_below_probed_area(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # ask for the key in the middle, but a key that is located in the
        # unparsed region before the middle.
        result =index._lookup_keys_via_location(
            [(index._size // 2, ('30', ))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
            index._parsed_key_map)
        self.assertEqual([((index._size // 2, ('30', )), -1)],
            result)

    def test_lookup_key_above_probed_area(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        index = self.make_index(nodes=self.make_nodes(64))
        # ask for the key in the middle, but a key that is located in the
        # unparsed region after the middle.
        result =index._lookup_keys_via_location(
            [(index._size // 2, ('50', ))])
        # check the parse map, this determines the test validity
        self.assertEqual([(0, 4008), (5046, 8996)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(26)),
                          (self.make_key(31), self.make_key(48))],
            index._parsed_key_map)
        self.assertEqual([((index._size // 2, ('50', )), +1)],
            result)

    def test_lookup_key_resolves_references(self):
        # generate a big enough index that we only read some of it on a typical
        # bisection lookup.
        nodes = []
        for counter in range(99):
            nodes.append((self.make_key(counter), self.make_value(counter),
                ((self.make_key(counter + 20),),)  ))
        index = self.make_index(ref_lists=1, nodes=nodes)
        # lookup a key in the middle that does not exist, so that when we can
        # check that the referred-to-keys are not accessed automatically.
        index_size = index._size
        index_center = index_size // 2
        result = index._lookup_keys_via_location(
            [(index_center, ('40', ))])
        # check the parse map - only the start and middle should have been
        # parsed.
        self.assertEqual([(0, 4027), (10198, 14028)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(17)),
                          (self.make_key(44), self.make_key(5))],
            index._parsed_key_map)
        # and check the transport activity likewise.
        self.assertEqual(
            [('readv', 'index', [(index_center, 800), (0, 200)], True,
                                  index_size)],
            index._transport._activity)
        # reset the transport log for testing the reference lookup
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # only perform IO to resolve its key references.
        result = index._lookup_keys_via_location([(11000, self.make_key(45))])
        self.assertEqual(
            [((11000, self.make_key(45)),
              (index, self.make_key(45), self.make_value(45),
               ((self.make_key(65),),)))],
            result)
        self.assertEqual([('readv', 'index', [(15093, 800)], True, index_size)],
            index._transport._activity)

    def test_lookup_key_can_buffer_all(self):
        nodes = []
        for counter in range(64):
            nodes.append((self.make_key(counter), self.make_value(counter),
                ((self.make_key(counter + 20),),)  ))
        index = self.make_index(ref_lists=1, nodes=nodes)
        # lookup a key in the middle that does not exist, so that when we can
        # check that the referred-to-keys are not accessed automatically.
        index_size = index._size
        index_center = index_size // 2
        result = index._lookup_keys_via_location([(index_center, ('40', ))])
        # check the parse map - only the start and middle should have been
        # parsed.
        self.assertEqual([(0, 3890), (6444, 10274)], index._parsed_byte_map)
        self.assertEqual([(None, self.make_key(25)),
                          (self.make_key(37), self.make_key(52))],
            index._parsed_key_map)
        # and check the transport activity likewise.
        self.assertEqual(
            [('readv', 'index', [(index_center, 800), (0, 200)], True,
                                  index_size)],
            index._transport._activity)
        # reset the transport log for testing the reference lookup
        del index._transport._activity[:]
        # now looking up a key in the portion of the file already parsed should
        # only perform IO to resolve its key references.
        result = index._lookup_keys_via_location([(7000, self.make_key(40))])
        self.assertEqual(
            [((7000, self.make_key(40)),
              (index, self.make_key(40), self.make_value(40),
               ((self.make_key(60),),)))],
            result)
        # Resolving the references would have required more data read, and we
        # are already above the 50% threshold, so it triggered a _buffer_all
        self.assertEqual([('get', 'index')], index._transport._activity)

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[(('name', ), 'data', ())])
        self.assertEqual([(index, ('name', ), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_simple_2_elements(self):
        index = self.make_index(key_elements=2,
            nodes=[(('name', 'surname'), 'data', ())])
        self.assertEqual([(index, ('name', 'surname'), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_references_resolved(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_all_entries()))

    def test_iter_entries_buffers_once(self):
        index = self.make_index(nodes=self.make_nodes(2))
        # reset the transport log
        del index._transport._activity[:]
        self.assertEqual(set([(index, self.make_key(1), self.make_value(1))]),
                         set(index.iter_entries([self.make_key(1)])))
        # We should have requested reading the header bytes
        # But not needed any more than that because it would have triggered a
        # buffer all
        self.assertEqual([
            ('readv', 'index', [(0, 200)], True, index._size),
            ],
            index._transport._activity)
        # And that should have been enough to trigger reading the whole index
        # with buffering
        self.assertIsNot(None, index._nodes)

    def test_iter_entries_buffers_by_bytes_read(self):
        index = self.make_index(nodes=self.make_nodes(64))
        list(index.iter_entries([self.make_key(10)]))
        # The first time through isn't enough to trigger a buffer all
        self.assertIs(None, index._nodes)
        self.assertEqual(4096, index._bytes_read)
        # Grabbing a key in that same page won't trigger a buffer all, as we
        # still haven't read 50% of the file
        list(index.iter_entries([self.make_key(11)]))
        self.assertIs(None, index._nodes)
        self.assertEqual(4096, index._bytes_read)
        # We haven't read more data, so reading outside the range won't trigger
        # a buffer all right away
        list(index.iter_entries([self.make_key(40)]))
        self.assertIs(None, index._nodes)
        self.assertEqual(8192, index._bytes_read)
        # On the next pass, we will not trigger buffer all if the key is
        # available without reading more
        list(index.iter_entries([self.make_key(32)]))
        self.assertIs(None, index._nodes)
        # But if we *would* need to read more to resolve it, then we will
        # buffer all.
        list(index.iter_entries([self.make_key(60)]))
        self.assertIsNot(None, index._nodes)

    def test_iter_entries_references_resolved(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', ), ('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),('ref',)),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name',), ('ref',)])))

    def test_iter_entries_references_2_refs_resolved(self):
        index = self.make_index(2, nodes=[
            (('name', ), 'data', ([('ref', )], [('ref', )])),
            (('ref', ), 'refdata', ([], []))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),), (('ref',),))),
            (index, ('ref', ), 'refdata', ((), ()))]),
            set(index.iter_entries([('name',), ('ref',)])))

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),))]),
            set(index.iter_all_entries()))
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),))]),
            set(index.iter_entries([('name', )])))
        self.assertEqual([], list(index.iter_entries([('ref', )])))

    def test_iteration_absent_skipped_2_element_keys(self):
        index = self.make_index(1, key_elements=2, nodes=[
            (('name', 'fin'), 'data', ([('ref', 'erence')], ))])
        self.assertEqual(set([(index, ('name', 'fin'), 'data', ((('ref', 'erence'),),))]),
            set(index.iter_all_entries()))
        self.assertEqual(set([(index, ('name', 'fin'), 'data', ((('ref', 'erence'),),))]),
            set(index.iter_entries([('name', 'fin')])))
        self.assertEqual([], list(index.iter_entries([('ref', 'erence')])))

    def test_iter_all_keys(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name', ), ('ref', )])))

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([('a', )])))

    def test_iter_missing_entry_empty_no_size(self):
        index = self.make_index()
        index = GraphIndex(index._transport, 'index', None)
        self.assertEqual([], list(index.iter_entries([('a', )])))

    def test_iter_key_prefix_1_element_key_None(self):
        index = self.make_index()
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([(None, )]))

    def test_iter_key_prefix_wrong_length(self):
        index = self.make_index()
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', None)]))
        index = self.make_index(key_elements=2)
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', )]))
        self.assertRaises(errors.BadIndexKey, list,
            index.iter_entries_prefix([('foo', None, None)]))

    def test_iter_key_prefix_1_key_element_no_refs(self):
        index = self.make_index( nodes=[
            (('name', ), 'data', ()),
            (('ref', ), 'refdata', ())])
        self.assertEqual(set([(index, ('name', ), 'data'),
            (index, ('ref', ), 'refdata')]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_1_key_element_refs(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_2_key_element_no_refs(self):
        index = self.make_index(key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ()),
            (('name', 'fin2'), 'beta', ()),
            (('ref', 'erence'), 'refdata', ())])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('ref', 'erence'), 'refdata')]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('name', 'fin2'), 'beta')]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_iter_key_prefix_2_key_element_refs(self):
        index = self.make_index(1, key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ([('ref', 'erence')], )),
            (('name', 'fin2'), 'beta', ([], )),
            (('ref', 'erence'), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('ref', 'erence'), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('name', 'fin2'), 'beta', ((), ))]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_key_count_empty(self):
        index = self.make_index()
        self.assertEqual(0, index.key_count())

    def test_key_count_one(self):
        index = self.make_index(nodes=[(('name', ), '', ())])
        self.assertEqual(1, index.key_count())

    def test_key_count_two(self):
        index = self.make_index(nodes=[
            (('name', ), '', ()), (('foo', ), '', ())])
        self.assertEqual(2, index.key_count())

    def test_read_and_parse_tracks_real_read_value(self):
        index = self.make_index(nodes=self.make_nodes(10))
        del index._transport._activity[:]
        index._read_and_parse([(0, 200)])
        self.assertEqual([
            ('readv', 'index', [(0, 200)], True, index._size),
            ],
            index._transport._activity)
        # The readv expansion code will expand the initial request to 4096
        # bytes, which is more than enough to read the entire index, and we
        # will track the fact that we read that many bytes.
        self.assertEqual(index._size, index._bytes_read)

    def test_read_and_parse_triggers_buffer_all(self):
        index = self.make_index(key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ()),
            (('name', 'fin2'), 'beta', ()),
            (('ref', 'erence'), 'refdata', ())])
        self.assertTrue(index._size > 0)
        self.assertIs(None, index._nodes)
        index._read_and_parse([(0, index._size)])
        self.assertIsNot(None, index._nodes)

    def test_validate_bad_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index = GraphIndex(trans, 'name', 13)
        self.assertRaises(errors.BadIndexFormatSignature, index.validate)

    def test_validate_bad_node_refs(self):
        index = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # change the options line to end with a rather than a parseable number
        new_content = content[:-2] + 'a\n\n'
        trans.put_bytes('index', new_content)
        self.assertRaises(errors.BadIndexOptions, index.validate)

    def test_validate_missing_end_line_empty(self):
        index = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # truncate the last byte
        trans.put_bytes('index', content[:-1])
        self.assertRaises(errors.BadIndexData, index.validate)

    def test_validate_missing_end_line_nonempty(self):
        index = self.make_index(2, nodes=[(('key', ), '', ([], []))])
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # truncate the last byte
        trans.put_bytes('index', content[:-1])
        self.assertRaises(errors.BadIndexData, index.validate)

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[(('key', ), 'value', ())])
        index.validate()


class TestCombinedGraphIndex(TestCaseWithMemoryTransport):

    def make_index(self, name, ref_lists=0, key_elements=1, nodes=[]):
        builder = GraphIndexBuilder(ref_lists, key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def make_combined_index_with_missing(self, missing=['1', '2']):
        """Create a CombinedGraphIndex which will have missing indexes.

        This creates a CGI which thinks it has 2 indexes, however they have
        been deleted. If CGI._reload_func() is called, then it will repopulate
        with a new index.

        :param missing: The underlying indexes to delete
        :return: (CombinedGraphIndex, reload_counter)
        """
        index1 = self.make_index('1', nodes=[(('1',), '', ())])
        index2 = self.make_index('2', nodes=[(('2',), '', ())])
        index3 = self.make_index('3', nodes=[
            (('1',), '', ()),
            (('2',), '', ())])

        # total_reloads, num_changed, num_unchanged
        reload_counter = [0, 0, 0]
        def reload():
            reload_counter[0] += 1
            new_indices = [index3]
            if index._indices == new_indices:
                reload_counter[2] += 1
                return False
            reload_counter[1] += 1
            index._indices[:] = new_indices
            return True
        index = CombinedGraphIndex([index1, index2], reload_func=reload)
        trans = self.get_transport()
        for fname in missing:
            trans.delete(fname)
        return index, reload_counter

    def test_open_missing_index_no_error(self):
        trans = self.get_transport()
        index1 = GraphIndex(trans, 'missing', 100)
        index = CombinedGraphIndex([index1])

    def test_add_index(self):
        index = CombinedGraphIndex([])
        index1 = self.make_index('name', 0, nodes=[(('key', ), '', ())])
        index.insert_index(0, index1)
        self.assertEqual([(index1, ('key', ), '')], list(index.iter_all_entries()))

    def test_iter_all_entries_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_children_empty(self):
        index1 = self.make_index('name')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index1 = self.make_index('name', nodes=[(('name', ), 'data', ())])
        index = CombinedGraphIndex([index1])
        self.assertEqual([(index1, ('name', ), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_two_indices(self):
        index1 = self.make_index('name1', nodes=[(('name', ), 'data', ())])
        index2 = self.make_index('name2', nodes=[(('2', ), '', ())])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([(index1, ('name', ), 'data'),
            (index2, ('2', ), '')],
            list(index.iter_all_entries()))

    def test_iter_entries_two_indices_dup_key(self):
        index1 = self.make_index('name1', nodes=[(('name', ), 'data', ())])
        index2 = self.make_index('name2', nodes=[(('name', ), 'data', ())])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([(index1, ('name', ), 'data')],
            list(index.iter_entries([('name', )])))

    def test_iter_all_entries_two_indices_dup_key(self):
        index1 = self.make_index('name1', nodes=[(('name', ), 'data', ())])
        index2 = self.make_index('name2', nodes=[(('name', ), 'data', ())])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([(index1, ('name', ), 'data')],
            list(index.iter_all_entries()))

    def test_iter_key_prefix_2_key_element_refs(self):
        index1 = self.make_index('1', 1, key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ([('ref', 'erence')], ))])
        index2 = self.make_index('2', 1, key_elements=2, nodes=[
            (('name', 'fin2'), 'beta', ([], )),
            (('ref', 'erence'), 'refdata', ([], ))])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(set([(index1, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index2, ('ref', 'erence'), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index1, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index2, ('name', 'fin2'), 'beta', ((), ))]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_iter_nothing_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_nothing_children_empty(self):
        index1 = self.make_index('name')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_all_keys(self):
        index1 = self.make_index('1', 1, nodes=[
            (('name', ), 'data', ([('ref', )], ))])
        index2 = self.make_index('2', 1, nodes=[
            (('ref', ), 'refdata', ((), ))])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(set([(index1, ('name', ), 'data', ((('ref', ), ), )),
            (index2, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name', ), ('ref', )])))
 
    def test_iter_all_keys_dup_entry(self):
        index1 = self.make_index('1', 1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        index2 = self.make_index('2', 1, nodes=[
            (('ref', ), 'refdata', ([], ))])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(set([(index1, ('name', ), 'data', ((('ref',),),)),
            (index1, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name', ), ('ref', )])))
 
    def test_iter_missing_entry_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_entries([('a', )])))

    def test_iter_missing_entry_one_index(self):
        index1 = self.make_index('1')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_entries([('a', )])))

    def test_iter_missing_entry_two_index(self):
        index1 = self.make_index('1')
        index2 = self.make_index('2')
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([], list(index.iter_entries([('a', )])))
 
    def test_iter_entry_present_one_index_only(self):
        index1 = self.make_index('1', nodes=[(('key', ), '', ())])
        index2 = self.make_index('2', nodes=[])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([(index1, ('key', ), '')],
            list(index.iter_entries([('key', )])))
        # and in the other direction
        index = CombinedGraphIndex([index2, index1])
        self.assertEqual([(index1, ('key', ), '')],
            list(index.iter_entries([('key', )])))

    def test_key_count_empty(self):
        index1 = self.make_index('1', nodes=[])
        index2 = self.make_index('2', nodes=[])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(0, index.key_count())

    def test_key_count_sums_index_keys(self):
        index1 = self.make_index('1', nodes=[
            (('1',), '', ()),
            (('2',), '', ())])
        index2 = self.make_index('2', nodes=[(('1',), '', ())])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(3, index.key_count())

    def test_validate_bad_child_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index1 = GraphIndex(trans, 'name', 13)
        index = CombinedGraphIndex([index1])
        self.assertRaises(errors.BadIndexFormatSignature, index.validate)

    def test_validate_empty(self):
        index = CombinedGraphIndex([])
        index.validate()

    def test_key_count_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        self.assertEqual(2, index.key_count())
        self.assertEqual([1, 1, 0], reload_counter)

    def test_key_count_no_reload(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        # Without a _reload_func we just raise the exception
        self.assertRaises(errors.NoSuchFile, index.key_count)

    def test_key_count_reloads_and_fails(self):
        # We have deleted all underlying indexes, so we will try to reload, but
        # still fail. This is mostly to test we don't get stuck in an infinite
        # loop trying to reload
        index, reload_counter = self.make_combined_index_with_missing(
                                    ['1', '2', '3'])
        self.assertRaises(errors.NoSuchFile, index.key_count)
        self.assertEqual([2, 1, 1], reload_counter)

    def test_iter_entries_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_entries([('1',), ('2',), ('3',)]))
        index3 = index._indices[0]
        self.assertEqual([(index3, ('1',), ''), (index3, ('2',), '')],
                         result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_reloads_midway(self):
        # The first index still looks present, so we get interrupted mid-way
        # through
        index, reload_counter = self.make_combined_index_with_missing(['2'])
        index1, index2 = index._indices
        result = list(index.iter_entries([('1',), ('2',), ('3',)]))
        index3 = index._indices[0]
        # We had already yielded '1', so we just go on to the next, we should
        # not yield '1' twice.
        self.assertEqual([(index1, ('1',), ''), (index3, ('2',), '')],
                         result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_no_reload(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        # Without a _reload_func we just raise the exception
        self.assertListRaises(errors.NoSuchFile, index.iter_entries, [('3',)])

    def test_iter_entries_reloads_and_fails(self):
        index, reload_counter = self.make_combined_index_with_missing(
                                    ['1', '2', '3'])
        self.assertListRaises(errors.NoSuchFile, index.iter_entries, [('3',)])
        self.assertEqual([2, 1, 1], reload_counter)

    def test_iter_all_entries_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_all_entries())
        index3 = index._indices[0]
        self.assertEqual([(index3, ('1',), ''), (index3, ('2',), '')],
                         result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_all_entries_reloads_midway(self):
        index, reload_counter = self.make_combined_index_with_missing(['2'])
        index1, index2 = index._indices
        result = list(index.iter_all_entries())
        index3 = index._indices[0]
        # We had already yielded '1', so we just go on to the next, we should
        # not yield '1' twice.
        self.assertEqual([(index1, ('1',), ''), (index3, ('2',), '')],
                         result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_all_entries_no_reload(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        self.assertListRaises(errors.NoSuchFile, index.iter_all_entries)

    def test_iter_all_entries_reloads_and_fails(self):
        index, reload_counter = self.make_combined_index_with_missing(
                                    ['1', '2', '3'])
        self.assertListRaises(errors.NoSuchFile, index.iter_all_entries)

    def test_iter_entries_prefix_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        result = list(index.iter_entries_prefix([('1',)]))
        index3 = index._indices[0]
        self.assertEqual([(index3, ('1',), '')], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_prefix_reloads_midway(self):
        index, reload_counter = self.make_combined_index_with_missing(['2'])
        index1, index2 = index._indices
        result = list(index.iter_entries_prefix([('1',)]))
        index3 = index._indices[0]
        # We had already yielded '1', so we just go on to the next, we should
        # not yield '1' twice.
        self.assertEqual([(index1, ('1',), '')], result)
        self.assertEqual([1, 1, 0], reload_counter)

    def test_iter_entries_prefix_no_reload(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        self.assertListRaises(errors.NoSuchFile, index.iter_entries_prefix,
                                                 [('1',)])

    def test_iter_entries_prefix_reloads_and_fails(self):
        index, reload_counter = self.make_combined_index_with_missing(
                                    ['1', '2', '3'])
        self.assertListRaises(errors.NoSuchFile, index.iter_entries_prefix,
                                                 [('1',)])

    def test_validate_reloads(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index.validate()
        self.assertEqual([1, 1, 0], reload_counter)

    def test_validate_reloads_midway(self):
        index, reload_counter = self.make_combined_index_with_missing(['2'])
        index.validate()

    def test_validate_no_reload(self):
        index, reload_counter = self.make_combined_index_with_missing()
        index._reload_func = None
        self.assertRaises(errors.NoSuchFile, index.validate)

    def test_validate_reloads_and_fails(self):
        index, reload_counter = self.make_combined_index_with_missing(
                                    ['1', '2', '3'])
        self.assertRaises(errors.NoSuchFile, index.validate)


class TestInMemoryGraphIndex(TestCaseWithMemoryTransport):

    def make_index(self, ref_lists=0, key_elements=1, nodes=[]):
        result = InMemoryGraphIndex(ref_lists, key_elements=key_elements)
        result.add_nodes(nodes)
        return result

    def test_add_nodes_no_refs(self):
        index = self.make_index(0)
        index.add_nodes([(('name', ), 'data')])
        index.add_nodes([(('name2', ), ''), (('name3', ), '')])
        self.assertEqual(set([
            (index, ('name', ), 'data'),
            (index, ('name2', ), ''),
            (index, ('name3', ), ''),
            ]), set(index.iter_all_entries()))

    def test_add_nodes(self):
        index = self.make_index(1)
        index.add_nodes([(('name', ), 'data', ([],))])
        index.add_nodes([(('name2', ), '', ([],)), (('name3', ), '', ([('r', )],))])
        self.assertEqual(set([
            (index, ('name', ), 'data', ((),)),
            (index, ('name2', ), '', ((),)),
            (index, ('name3', ), '', ((('r', ), ), )),
            ]), set(index.iter_all_entries()))

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[(('name', ), 'data')])
        self.assertEqual([(index, ('name', ), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_references(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref', ),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_all_entries()))

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),))]),
            set(index.iter_all_entries()))
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),))]),
            set(index.iter_entries([('name', )])))
        self.assertEqual([], list(index.iter_entries([('ref', )])))

    def test_iter_all_keys(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name', ), ('ref', )])))

    def test_iter_key_prefix_1_key_element_no_refs(self):
        index = self.make_index( nodes=[
            (('name', ), 'data'),
            (('ref', ), 'refdata')])
        self.assertEqual(set([(index, ('name', ), 'data'),
            (index, ('ref', ), 'refdata')]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_1_key_element_refs(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', ), ('ref', )])))

    def test_iter_key_prefix_2_key_element_no_refs(self):
        index = self.make_index(key_elements=2, nodes=[
            (('name', 'fin1'), 'data'),
            (('name', 'fin2'), 'beta'),
            (('ref', 'erence'), 'refdata')])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('ref', 'erence'), 'refdata')]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data'),
            (index, ('name', 'fin2'), 'beta')]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_iter_key_prefix_2_key_element_refs(self):
        index = self.make_index(1, key_elements=2, nodes=[
            (('name', 'fin1'), 'data', ([('ref', 'erence')], )),
            (('name', 'fin2'), 'beta', ([], )),
            (('ref', 'erence'), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('ref', 'erence'), 'refdata', ((), ))]),
            set(index.iter_entries_prefix([('name', 'fin1'), ('ref', 'erence')])))
        self.assertEqual(set([(index, ('name', 'fin1'), 'data', ((('ref', 'erence'),),)),
            (index, ('name', 'fin2'), 'beta', ((), ))]),
            set(index.iter_entries_prefix([('name', None)])))

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries(['a'])))

    def test_key_count_empty(self):
        index = self.make_index()
        self.assertEqual(0, index.key_count())

    def test_key_count_one(self):
        index = self.make_index(nodes=[(('name', ), '')])
        self.assertEqual(1, index.key_count())

    def test_key_count_two(self):
        index = self.make_index(nodes=[(('name', ), ''), (('foo', ), '')])
        self.assertEqual(2, index.key_count())

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[(('key', ), 'value')])
        index.validate()


class TestGraphIndexPrefixAdapter(TestCaseWithMemoryTransport):

    def make_index(self, ref_lists=1, key_elements=2, nodes=[], add_callback=False):
        result = InMemoryGraphIndex(ref_lists, key_elements=key_elements)
        result.add_nodes(nodes)
        if add_callback:
            add_nodes_callback = result.add_nodes
        else:
            add_nodes_callback = None
        adapter = GraphIndexPrefixAdapter(result, ('prefix', ), key_elements - 1,
            add_nodes_callback=add_nodes_callback)
        return result, adapter

    def test_add_node(self):
        index, adapter = self.make_index(add_callback=True)
        adapter.add_node(('key',), 'value', ((('ref',),),))
        self.assertEqual(set([(index, ('prefix', 'key'), 'value', ((('prefix', 'ref'),),))]),
            set(index.iter_all_entries()))

    def test_add_nodes(self):
        index, adapter = self.make_index(add_callback=True)
        adapter.add_nodes((
            (('key',), 'value', ((('ref',),),)),
            (('key2',), 'value2', ((),)),
            ))
        self.assertEqual(set([
            (index, ('prefix', 'key2'), 'value2', ((),)),
            (index, ('prefix', 'key'), 'value', ((('prefix', 'ref'),),))
            ]),
            set(index.iter_all_entries()))

    def test_construct(self):
        index = InMemoryGraphIndex()
        adapter = GraphIndexPrefixAdapter(index, ('prefix', ), 1)

    def test_construct_with_callback(self):
        index = InMemoryGraphIndex()
        adapter = GraphIndexPrefixAdapter(index, ('prefix', ), 1, index.add_nodes)

    def test_iter_all_entries_cross_prefix_map_errors(self):
        index, adapter = self.make_index(nodes=[
            (('prefix', 'key1'), 'data1', ((('prefixaltered', 'key2'),),))])
        self.assertRaises(errors.BadIndexData, list, adapter.iter_all_entries())

    def test_iter_all_entries(self):
        index, adapter = self.make_index(nodes=[
            (('notprefix', 'key1'), 'data', ((), )),
            (('prefix', 'key1'), 'data1', ((), )),
            (('prefix', 'key2'), 'data2', ((('prefix', 'key1'),),))])
        self.assertEqual(set([(index, ('key1', ), 'data1', ((),)),
            (index, ('key2', ), 'data2', ((('key1',),),))]),
            set(adapter.iter_all_entries()))

    def test_iter_entries(self):
        index, adapter = self.make_index(nodes=[
            (('notprefix', 'key1'), 'data', ((), )),
            (('prefix', 'key1'), 'data1', ((), )),
            (('prefix', 'key2'), 'data2', ((('prefix', 'key1'),),))])
        # ask for many - get all
        self.assertEqual(set([(index, ('key1', ), 'data1', ((),)),
            (index, ('key2', ), 'data2', ((('key1', ),),))]),
            set(adapter.iter_entries([('key1', ), ('key2', )])))
        # ask for one, get one
        self.assertEqual(set([(index, ('key1', ), 'data1', ((),))]),
            set(adapter.iter_entries([('key1', )])))
        # ask for missing, get none
        self.assertEqual(set(),
            set(adapter.iter_entries([('key3', )])))

    def test_iter_entries_prefix(self):
        index, adapter = self.make_index(key_elements=3, nodes=[
            (('notprefix', 'foo', 'key1'), 'data', ((), )),
            (('prefix', 'prefix2', 'key1'), 'data1', ((), )),
            (('prefix', 'prefix2', 'key2'), 'data2', ((('prefix', 'prefix2', 'key1'),),))])
        # ask for a prefix, get the results for just that prefix, adjusted.
        self.assertEqual(set([(index, ('prefix2', 'key1', ), 'data1', ((),)),
            (index, ('prefix2', 'key2', ), 'data2', ((('prefix2', 'key1', ),),))]),
            set(adapter.iter_entries_prefix([('prefix2', None)])))

    def test_key_count_no_matching_keys(self):
        index, adapter = self.make_index(nodes=[
            (('notprefix', 'key1'), 'data', ((), ))])
        self.assertEqual(0, adapter.key_count())

    def test_key_count_some_keys(self):
        index, adapter = self.make_index(nodes=[
            (('notprefix', 'key1'), 'data', ((), )),
            (('prefix', 'key1'), 'data1', ((), )),
            (('prefix', 'key2'), 'data2', ((('prefix', 'key1'),),))])
        self.assertEqual(2, adapter.key_count())

    def test_validate(self):
        index, adapter = self.make_index()
        calls = []
        def validate():
            calls.append('called')
        index.validate = validate
        adapter.validate()
        self.assertEqual(['called'], calls)
