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

"""Tests for btree indices."""

import pprint
import zlib

from bzrlib import (
    btree_index,
    errors,
    tests,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    TestScenarioApplier,
    adapt_tests,
    condition_isinstance,
    split_suite_by_condition,
    )
from bzrlib.transport import get_transport


def load_tests(standard_tests, module, loader):
    # parameterise the TestBTreeNodes tests
    node_tests, others = split_suite_by_condition(standard_tests,
        condition_isinstance(TestBTreeNodes))
    applier = TestScenarioApplier()
    import bzrlib._btree_serializer_py as py_module
    applier.scenarios = [('python', {'parse_btree': py_module})]
    if CompiledBtreeParserFeature.available():
        # Is there a way to do this that gets missing feature failures rather
        # than no indication to the user?
        import bzrlib._btree_serializer_c as c_module
        applier.scenarios.append(('C', {'parse_btree': c_module}))
    adapt_tests(node_tests, applier, others)
    return others


class _CompiledBtreeParserFeature(tests.Feature):
    def _probe(self):
        try:
            import bzrlib._btree_serializer_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._btree_serializer_c'

CompiledBtreeParserFeature = _CompiledBtreeParserFeature()


class BTreeTestCase(TestCaseWithTransport):
    # test names here are suffixed by the key length and reference list count
    # that they test.

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self._original_header = btree_index._RESERVED_HEADER_BYTES
        def restore():
            btree_index._RESERVED_HEADER_BYTES = self._original_header
        self.addCleanup(restore)
        btree_index._RESERVED_HEADER_BYTES = 100

    def make_nodes(self, count, key_elements, reference_lists):
        """Generate count*key_elements sample nodes."""
        keys = []
        for prefix_pos in range(key_elements):
            if key_elements - 1:
                prefix = (str(prefix_pos) * 40,)
            else:
                prefix = ()
            for pos in xrange(count):
                # TODO: This creates odd keys. When count == 100,000, it
                #       creates a 240 byte key
                key = prefix + (str(pos) * 40,)
                value = "value:%s" % pos
                if reference_lists:
                    # generate some references
                    refs = []
                    for list_pos in range(reference_lists):
                        # as many keys in each list as its index + the key depth
                        # mod 2 - this generates both 0 length lists and
                        # ones slightly longer than the number of lists.
                        # It also ensures we have non homogeneous lists.
                        refs.append([])
                        for ref_pos in range(list_pos + pos % 2):
                            if pos % 2:
                                # refer to a nearby key
                                refs[-1].append(prefix + ("ref" + str(pos - 1) * 40,))
                            else:
                                # serial of this ref in the ref list
                                refs[-1].append(prefix + ("ref" + str(ref_pos) * 40,))
                        refs[-1] = tuple(refs[-1])
                    refs = tuple(refs)
                else:
                    refs = ()
                keys.append((key, value, refs))
        return keys

    def shrink_page_size(self):
        """Shrink the default page size so that less fits in a page."""
        old_page_size = btree_index._PAGE_SIZE
        def cleanup():
            btree_index._PAGE_SIZE = old_page_size
        self.addCleanup(cleanup)
        btree_index._PAGE_SIZE = 2048


class TestBTreeBuilder(BTreeTestCase):

    def test_empty_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=0\n"
            "row_lengths=\n",
            content)

    def test_empty_2_1(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=1)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=1\nkey_elements=2\nlen=0\n"
            "row_lengths=\n",
            content)

    def test_root_leaf_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(5, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(158, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=5\n"
            "row_lengths=1\n",
            content[:73])
        node_content = content[73:]
        node_bytes = zlib.decompress(node_content)
        expected_node = ("type=leaf\n"
            "0000000000000000000000000000000000000000\x00\x00value:0\n"
            "1111111111111111111111111111111111111111\x00\x00value:1\n"
            "2222222222222222222222222222222222222222\x00\x00value:2\n"
            "3333333333333333333333333333333333333333\x00\x00value:3\n"
            "4444444444444444444444444444444444444444\x00\x00value:4\n")
        self.assertEqual(expected_node, node_bytes)

    def test_root_leaf_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(5, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(264, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=10\n"
            "row_lengths=1\n",
            content[:74])
        node_content = content[74:]
        node_bytes = zlib.decompress(node_content)
        expected_node = (
            "type=leaf\n"
            "0000000000000000000000000000000000000000\x000000000000000000000000000000000000000000\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            "0000000000000000000000000000000000000000\x001111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\r0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            "0000000000000000000000000000000000000000\x002222222222222222222222222222222222222222\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            "0000000000000000000000000000000000000000\x003333333333333333333333333333333333333333\x000000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\t0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\r0000000000000000000000000000000000000000\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            "0000000000000000000000000000000000000000\x004444444444444444444444444444444444444444\x00\t0000000000000000000000000000000000000000\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            "1111111111111111111111111111111111111111\x000000000000000000000000000000000000000000\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:0\n"
            "1111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x001111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\r1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:1\n"
            "1111111111111111111111111111111111111111\x002222222222222222222222222222222222222222\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:2\n"
            "1111111111111111111111111111111111111111\x003333333333333333333333333333333333333333\x001111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\t1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\r1111111111111111111111111111111111111111\x00ref2222222222222222222222222222222222222222\x00value:3\n"
            "1111111111111111111111111111111111111111\x004444444444444444444444444444444444444444\x00\t1111111111111111111111111111111111111111\x00ref0000000000000000000000000000000000000000\x00value:4\n"
            ""
            )
        self.assertEqual(expected_node, node_bytes)

    def test_2_leaves_1_0(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(400, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(9283, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=400\n"
            "row_lengths=1,2\n",
            content[:77])
        root = content[77:4096]
        leaf1 = content[4096:8192]
        leaf2 = content[8192:]
        root_bytes = zlib.decompress(root)
        expected_root = (
            "type=internal\n"
            "offset=0\n"
            ) + ("307" * 40) + "\n"
        self.assertEqual(expected_root, root_bytes)
        # We already know serialisation works for leaves, check key selection:
        leaf1_bytes = zlib.decompress(leaf1)
        sorted_node_keys = sorted(node[0] for node in nodes)
        node = btree_index._LeafNode(leaf1_bytes, 1, 0)
        self.assertEqual(231, len(node.keys))
        self.assertEqual(sorted_node_keys[:231], sorted(node.keys))
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(400 - 231, len(node.keys))
        self.assertEqual(sorted_node_keys[231:], sorted(node.keys))

    def test_last_page_rounded_1_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(10, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(181, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=10\n"
            "row_lengths=1\n",
            content[:74])
        # Check thelast page is well formed
        leaf2 = content[74:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(10, len(node.keys))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys, sorted(node.keys))

    def test_last_page_not_rounded_2_layer(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        nodes = self.make_nodes(400, 1, 0)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(9283, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=0\nkey_elements=1\nlen=400\n"
            "row_lengths=1,2\n",
            content[:77])
        # Check the last page is well formed
        leaf2 = content[8192:]
        leaf2_bytes = zlib.decompress(leaf2)
        node = btree_index._LeafNode(leaf2_bytes, 1, 0)
        self.assertEqual(400 - 231, len(node.keys))
        sorted_node_keys = sorted(node[0] for node in nodes)
        self.assertEqual(sorted_node_keys[231:], sorted(node.keys))

    def test_three_level_tree_details(self):
        # The left most pointer in the second internal node in a row should
        # pointer to the second node that the internal node is for, _not_
        # the first, otherwise the first node overlaps with the last node of
        # the prior internal node on that row.
        self.shrink_page_size()
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 40K nodes is enough to create a two internal nodes on the second
        # level, with a 2K page size
        nodes = self.make_nodes(20000, 2, 2)

        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', self.time(builder.finish))
        del builder
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        # Seed the metadata, we're using internal calls now.
        index.key_count()
        self.assertEqual(3, len(index._row_lengths),
            "Not enough rows: %r" % index._row_lengths)
        self.assertEqual(4, len(index._row_offsets))
        self.assertEqual(sum(index._row_lengths), index._row_offsets[-1])
        internal_nodes = index._get_internal_nodes([0, 1, 2])
        root_node = internal_nodes[0]
        internal_node1 = internal_nodes[1]
        internal_node2 = internal_nodes[2]
        # The left most node node2 points at should be one after the right most
        # node pointed at by node1.
        self.assertEqual(internal_node2.offset, 1 + len(internal_node1.keys))
        # The left most key of the second node pointed at by internal_node2
        # should be its first key. We can check this by looking for its first key
        # in the second node it points at
        pos = index._row_offsets[2] + internal_node2.offset + 1
        leaf = index._get_leaf_nodes([pos])[pos]
        self.assertTrue(internal_node2.keys[0] in leaf.keys)

    def test_2_leaves_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(100, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        # NamedTemporaryFile dies on builder.finish().read(). weird.
        temp_file = builder.finish()
        content = temp_file.read()
        del temp_file
        self.assertEqual(12643, len(content))
        self.assertEqual(
            "B+Tree Graph Index 2\nnode_ref_lists=2\nkey_elements=2\nlen=200\n"
            "row_lengths=1,3\n",
            content[:77])
        root = content[77:4096]
        leaf1 = content[4096:8192]
        leaf2 = content[8192:12288]
        leaf3 = content[12288:]
        root_bytes = zlib.decompress(root)
        expected_root = (
            "type=internal\n"
            "offset=0\n"
            + ("0" * 40) + "\x00" + ("91" * 40) + "\n"
            + ("1" * 40) + "\x00" + ("81" * 40) + "\n"
            )
        self.assertEqual(expected_root, root_bytes)
        # We assume the other leaf nodes have been written correctly - layering
        # FTW.

    def test_spill_index_stress_1_1(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._nodes))
        self.assertEqual(1, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertEqual(1, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # Next spill combines
        builder.add_node(*nodes[6])
        builder.add_node(*nodes[7])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        # And so forth - counting up in binary.
        builder.add_node(*nodes[8])
        builder.add_node(*nodes[9])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[10])
        builder.add_node(*nodes[11])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[12])
        # Test that memory and disk are both used for query methods; and that
        # None is skipped over happily.
        self.assertEqual([(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()))
        # Two nodes - one memory one disk
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])))
        self.assertEqual(13, builder.key_count())
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])))
        builder.add_node(*nodes[13])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[14])
        builder.add_node(*nodes[15])
        self.assertEqual(4, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(None, builder._backing_indices[2])
        self.assertEqual(16, builder._backing_indices[3].key_count())
        # Now finish, and check we got a correctly ordered tree
        transport = self.get_transport('')
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_set_optimize(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        builder.set_optimize(for_size=True)
        self.assertTrue(builder._optimize_for_size)
        builder.set_optimize(for_size=False)
        self.assertFalse(builder._optimize_for_size)

    def test_spill_index_stress_2_2(self):
        # test that references and longer keys don't confuse things.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2,
            spill_at=2)
        nodes = self.make_nodes(16, 2, 2)
        builder.add_node(*nodes[0])
        # Test the parts of the index that take up memory are doing so
        # predictably.
        self.assertEqual(1, len(builder._keys))
        self.assertEqual(1, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        builder.add_node(*nodes[1])
        self.assertEqual(0, len(builder._keys))
        self.assertEqual(0, len(builder._nodes))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(1, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        # now back to memory
        old = dict(builder._get_nodes_by_key()) #Build up the nodes by key dict
        builder.add_node(*nodes[2])
        self.assertEqual(1, len(builder._nodes))
        self.assertEqual(1, len(builder._keys))
        self.assertIsNot(None, builder._nodes_by_key)
        self.assertNotEqual({}, builder._nodes_by_key)
        # We should have a new entry
        self.assertNotEqual(old, builder._nodes_by_key)
        # And spills to a second backing index combing all
        builder.add_node(*nodes[3])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # The next spills to the 2-len slot
        builder.add_node(*nodes[4])
        builder.add_node(*nodes[5])
        self.assertEqual(0, len(builder._nodes))
        self.assertEqual(0, len(builder._keys))
        self.assertIs(None, builder._nodes_by_key)
        self.assertEqual(2, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        # Next spill combines
        builder.add_node(*nodes[6])
        builder.add_node(*nodes[7])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        # And so forth - counting up in binary.
        builder.add_node(*nodes[8])
        builder.add_node(*nodes[9])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[10])
        builder.add_node(*nodes[11])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[12])
        # Test that memory and disk are both used for query methods; and that
        # None is skipped over happily.
        self.assertEqual([(builder,) + node for node in sorted(nodes[:13])],
            list(builder.iter_all_entries()))
        # Two nodes - one memory one disk
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries([nodes[12][0], nodes[11][0]])))
        self.assertEqual(13, builder.key_count())
        self.assertEqual(set([(builder,) + node for node in nodes[11:13]]),
            set(builder.iter_entries_prefix([nodes[12][0], nodes[11][0]])))
        builder.add_node(*nodes[13])
        self.assertEqual(3, len(builder._backing_indices))
        self.assertEqual(2, builder._backing_indices[0].key_count())
        self.assertEqual(4, builder._backing_indices[1].key_count())
        self.assertEqual(8, builder._backing_indices[2].key_count())
        builder.add_node(*nodes[14])
        builder.add_node(*nodes[15])
        self.assertEqual(4, len(builder._backing_indices))
        self.assertEqual(None, builder._backing_indices[0])
        self.assertEqual(None, builder._backing_indices[1])
        self.assertEqual(None, builder._backing_indices[2])
        self.assertEqual(16, builder._backing_indices[3].key_count())
        # Now finish, and check we got a correctly ordered tree
        transport = self.get_transport('')
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        nodes = list(index.iter_all_entries())
        self.assertEqual(sorted(nodes), nodes)
        self.assertEqual(16, len(nodes))

    def test_spill_index_duplicate_key_caught_on_finish(self):
        builder = btree_index.BTreeBuilder(key_elements=1, spill_at=2)
        nodes = [node[0:2] for node in self.make_nodes(16, 1, 0)]
        builder.add_node(*nodes[0])
        builder.add_node(*nodes[1])
        builder.add_node(*nodes[0])
        self.assertRaises(errors.BadIndexDuplicateKey, builder.finish)


class TestBTreeIndex(BTreeTestCase):

    def make_index(self, ref_lists=0, key_elements=1, nodes=[]):
        builder = btree_index.BTreeBuilder(reference_lists=ref_lists,
            key_elements=key_elements)
        for key, value, references in nodes:
            builder.add_node(key, value, references)
        stream = builder.finish()
        trans = get_transport('trace+' + self.get_url())
        size = trans.put_file('index', stream)
        return btree_index.BTreeGraphIndex(trans, 'index', size)

    def test_trivial_constructor(self):
        transport = get_transport('trace+' + self.get_url(''))
        index = btree_index.BTreeGraphIndex(transport, 'index', None)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], transport._activity)

    def test_with_size_constructor(self):
        transport = get_transport('trace+' + self.get_url(''))
        index = btree_index.BTreeGraphIndex(transport, 'index', 1)
        # Checks the page size at load, but that isn't logged yet.
        self.assertEqual([], transport._activity)

    def test_empty_key_count_no_size(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        transport = get_transport('trace+' + self.get_url(''))
        transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', None)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been requested (as we generally have the
        # size available, and doing many small readvs is inappropriate).
        # We can't tell how much was actually read here, but - check the code.
        self.assertEqual([('get', 'index')], transport._activity)

    def test_empty_key_count(self):
        builder = btree_index.BTreeBuilder(key_elements=1, reference_lists=0)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(72, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(0, index.key_count())
        # The entire index should have been read, as 4K > size
        self.assertEqual([('readv', 'index', [(0, 72)], False, None)],
            transport._activity)

    def test_non_empty_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(35, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(70, index.key_count())
        # The entire index should have been read, as it is one page long.
        self.assertEqual([('readv', 'index', [(0, size)], False, None)],
            transport._activity)
        self.assertEqual(1199, size)

    def test__read_nodes_no_size_one_page_reads_once(self):
        self.make_index(nodes=[(('key',), 'value', ())])
        trans = get_transport('trace+' + self.get_url())
        index = btree_index.BTreeGraphIndex(trans, 'index', None)
        del trans._activity[:]
        nodes = dict(index._read_nodes([0]))
        self.assertEqual([0], nodes.keys())
        node = nodes[0]
        self.assertEqual([('key',)], node.keys.keys())
        self.assertEqual([('get', 'index')], trans._activity)

    def test__read_nodes_no_size_multiple_pages(self):
        index = self.make_index(2, 2, nodes=self.make_nodes(160, 2, 2))
        index.key_count()
        num_pages = index._row_offsets[-1]
        # Reopen with a traced transport and no size
        trans = get_transport('trace+' + self.get_url())
        index = btree_index.BTreeGraphIndex(trans, 'index', None)
        del trans._activity[:]
        nodes = dict(index._read_nodes([0]))
        self.assertEqual(range(num_pages), nodes.keys())

    def test_2_levels_key_count_2_2(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(17692, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        self.assertEqual(320, index.key_count())
        # The entire index should not have been read.
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None)],
            transport._activity)

    def test_validate_one_page(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(45, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        index.validate()
        # The entire index should have been read linearly.
        self.assertEqual([('readv', 'index', [(0, size)], False, None)],
            transport._activity)
        self.assertEqual(1514, size)

    def test_validate_two_pages(self):
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        nodes = self.make_nodes(80, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        # Root page, 2 leaf pages
        self.assertEqual(9339, size)
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        index.validate()
        # The entire index should have been read linearly.
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None),
            ('readv', 'index', [(4096, 4096), (8192, 1147)], False, None)],
            transport._activity)
        # XXX: TODO: write some badly-ordered nodes, and some pointers-to-wrong
        # node and make validate find them.

    def test_eq_ne(self):
        # two indices are equal when constructed with the same parameters:
        transport1 = get_transport('trace+' + self.get_url(''))
        transport2 = get_transport(self.get_url(''))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', None) ==
            btree_index.BTreeGraphIndex(transport1, 'index', None))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) ==
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) ==
            btree_index.BTreeGraphIndex(transport2, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'inde1', 20) ==
            btree_index.BTreeGraphIndex(transport1, 'inde2', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 10) ==
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', None) !=
            btree_index.BTreeGraphIndex(transport1, 'index', None))
        self.assertFalse(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) !=
            btree_index.BTreeGraphIndex(transport1, 'index', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 20) !=
            btree_index.BTreeGraphIndex(transport2, 'index', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'inde1', 20) !=
            btree_index.BTreeGraphIndex(transport1, 'inde2', 20))
        self.assertTrue(
            btree_index.BTreeGraphIndex(transport1, 'index', 10) !=
            btree_index.BTreeGraphIndex(transport1, 'index', 20))

    def test_iter_all_only_root_no_size(self):
        self.make_index(nodes=[(('key',), 'value', ())])
        trans = get_transport('trace+' + self.get_url(''))
        index = btree_index.BTreeGraphIndex(trans, 'index', None)
        del trans._activity[:]
        self.assertEqual([(('key',), 'value')],
                         [x[1:] for x in index.iter_all_entries()])
        self.assertEqual([('get', 'index')], trans._activity)

    def test_iter_all_entries_reads(self):
        # iterating all entries reads the header, then does a linear
        # read.
        self.shrink_page_size()
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 20k nodes is enough to create a two internal nodes on the second
        # level, with a 2K page size
        nodes = self.make_nodes(10000, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        self.assertEqual(1303220, size, 'number of expected bytes in the'
                                        ' output changed')
        page_size = btree_index._PAGE_SIZE
        del builder
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        found_nodes = self.time(list, index.iter_all_entries())
        bare_nodes = []
        for node in found_nodes:
            self.assertTrue(node[0] is index)
            bare_nodes.append(node[1:])
        self.assertEqual(3, len(index._row_lengths),
            "Not enough rows: %r" % index._row_lengths)
        # Should be as long as the nodes we supplied
        self.assertEqual(20000, len(found_nodes))
        # Should have the same content
        self.assertEqual(set(nodes), set(bare_nodes))
        # Should have done linear scan IO up the index, ignoring
        # the internal nodes:
        # The entire index should have been read
        total_pages = sum(index._row_lengths)
        self.assertEqual(total_pages, index._row_offsets[-1])
        self.assertEqual(1303220, size)
        # The start of the leaves
        first_byte = index._row_offsets[-2] * page_size
        readv_request = []
        for offset in range(first_byte, size, page_size):
            readv_request.append((offset, page_size))
        # The last page is truncated
        readv_request[-1] = (readv_request[-1][0], 1303220 % page_size)
        expected = [('readv', 'index', [(0, page_size)], False, None),
             ('readv',  'index', readv_request, False, None)]
        if expected != transport._activity:
            self.assertEqualDiff(pprint.pformat(expected),
                                 pprint.pformat(transport._activity))

    def _test_iter_entries_references_resolved(self):
        index = self.make_index(1, nodes=[
            (('name', ), 'data', ([('ref', ), ('ref', )], )),
            (('ref', ), 'refdata', ([], ))])
        self.assertEqual(set([(index, ('name', ), 'data', ((('ref',),('ref',)),)),
            (index, ('ref', ), 'refdata', ((), ))]),
            set(index.iter_entries([('name',), ('ref',)])))

    def test_iter_entries_references_2_refs_resolved(self):
        # iterating some entries reads just the pages needed. For now, to
        # get it working and start measuring, only 4K pages are read.
        builder = btree_index.BTreeBuilder(key_elements=2, reference_lists=2)
        # 80 nodes is enough to create a two-level index.
        nodes = self.make_nodes(160, 2, 2)
        for node in nodes:
            builder.add_node(*node)
        transport = get_transport('trace+' + self.get_url(''))
        size = transport.put_file('index', builder.finish())
        del builder
        index = btree_index.BTreeGraphIndex(transport, 'index', size)
        del transport._activity[:]
        self.assertEqual([], transport._activity)
        # search for one key
        found_nodes = list(index.iter_entries([nodes[30][0]]))
        bare_nodes = []
        for node in found_nodes:
            self.assertTrue(node[0] is index)
            bare_nodes.append(node[1:])
        # Should be as long as the nodes we supplied
        self.assertEqual(1, len(found_nodes))
        # Should have the same content
        self.assertEqual(nodes[30], bare_nodes[0])
        # Should have read the root node, then one leaf page:
        self.assertEqual([('readv', 'index', [(0, 4096)], False, None),
             ('readv',  'index', [(8192, 4096), ], False, None)],
            transport._activity)

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


class TestBTreeNodes(BTreeTestCase):

    def restore_parser(self):
        btree_index._btree_serializer = self.saved_parser

    def setUp(self):
        BTreeTestCase.setUp(self)
        self.saved_parser = btree_index._btree_serializer
        self.addCleanup(self.restore_parser)
        btree_index._btree_serializer = self.parse_btree

    def test_LeafNode_1_0(self):
        node_bytes = ("type=leaf\n"
            "0000000000000000000000000000000000000000\x00\x00value:0\n"
            "1111111111111111111111111111111111111111\x00\x00value:1\n"
            "2222222222222222222222222222222222222222\x00\x00value:2\n"
            "3333333333333333333333333333333333333333\x00\x00value:3\n"
            "4444444444444444444444444444444444444444\x00\x00value:4\n")
        node = btree_index._LeafNode(node_bytes, 1, 0)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ("0000000000000000000000000000000000000000",): ("value:0", ()),
            ("1111111111111111111111111111111111111111",): ("value:1", ()),
            ("2222222222222222222222222222222222222222",): ("value:2", ()),
            ("3333333333333333333333333333333333333333",): ("value:3", ()),
            ("4444444444444444444444444444444444444444",): ("value:4", ()),
            }, node.keys)

    def test_LeafNode_2_2(self):
        node_bytes = ("type=leaf\n"
            "00\x0000\x00\t00\x00ref00\x00value:0\n"
            "00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n"
            "11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n"
            "11\x0044\x00\t11\x00ref00\x00value:4\n"
            ""
            )
        node = btree_index._LeafNode(node_bytes, 2, 2)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ('00', '00'): ('value:0', ((), (('00', 'ref00'),))),
            ('00', '11'): ('value:1',
                ((('00', 'ref00'),), (('00', 'ref00'), ('01', 'ref01')))),
            ('11', '33'): ('value:3',
                ((('11', 'ref22'),), (('11', 'ref22'), ('11', 'ref22')))),
            ('11', '44'): ('value:4', ((), (('11', 'ref00'),)))
            }, node.keys)

    def test_InternalNode_1(self):
        node_bytes = ("type=internal\n"
            "offset=1\n"
            "0000000000000000000000000000000000000000\n"
            "1111111111111111111111111111111111111111\n"
            "2222222222222222222222222222222222222222\n"
            "3333333333333333333333333333333333333333\n"
            "4444444444444444444444444444444444444444\n"
            )
        node = btree_index._InternalNode(node_bytes)
        # We want to bisect to find the right children from this node, so a
        # vector is most useful.
        self.assertEqual([
            ("0000000000000000000000000000000000000000",),
            ("1111111111111111111111111111111111111111",),
            ("2222222222222222222222222222222222222222",),
            ("3333333333333333333333333333333333333333",),
            ("4444444444444444444444444444444444444444",),
            ], node.keys)
        self.assertEqual(1, node.offset)

    def test_LeafNode_2_2(self):
        node_bytes = ("type=leaf\n"
            "00\x0000\x00\t00\x00ref00\x00value:0\n"
            "00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n"
            "11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n"
            "11\x0044\x00\t11\x00ref00\x00value:4\n"
            ""
            )
        node = btree_index._LeafNode(node_bytes, 2, 2)
        # We do direct access, or don't care about order, to leaf nodes most of
        # the time, so a dict is useful:
        self.assertEqual({
            ('00', '00'): ('value:0', ((), (('00', 'ref00'),))),
            ('00', '11'): ('value:1',
                ((('00', 'ref00'),), (('00', 'ref00'), ('01', 'ref01')))),
            ('11', '33'): ('value:3',
                ((('11', 'ref22'),), (('11', 'ref22'), ('11', 'ref22')))),
            ('11', '44'): ('value:4', ((), (('11', 'ref00'),)))
            }, node.keys)

    def assertFlattened(self, expected, key, value, refs):
        flat_key, flat_line = self.parse_btree._flatten_node(
            (None, key, value, refs), bool(refs))
        self.assertEqual('\x00'.join(key), flat_key)
        self.assertEqual(expected, flat_line)

    def test__flatten_node(self):
        self.assertFlattened('key\0\0value\n', ('key',), 'value', [])
        self.assertFlattened('key\0tuple\0\0value str\n',
                             ('key', 'tuple'), 'value str', [])
        self.assertFlattened('key\0tuple\0triple\0\0value str\n',
                             ('key', 'tuple', 'triple'), 'value str', [])
        self.assertFlattened('k\0t\0s\0ref\0value str\n',
                             ('k', 't', 's'), 'value str', [[('ref',)]])
        self.assertFlattened('key\0tuple\0ref\0key\0value str\n',
                             ('key', 'tuple'), 'value str', [[('ref', 'key')]])
        self.assertFlattened("00\x0000\x00\t00\x00ref00\x00value:0\n",
            ('00', '00'), 'value:0', ((), (('00', 'ref00'),)))
        self.assertFlattened(
            "00\x0011\x0000\x00ref00\t00\x00ref00\r01\x00ref01\x00value:1\n",
            ('00', '11'), 'value:1',
                ((('00', 'ref00'),), (('00', 'ref00'), ('01', 'ref01'))))
        self.assertFlattened(
            "11\x0033\x0011\x00ref22\t11\x00ref22\r11\x00ref22\x00value:3\n",
            ('11', '33'), 'value:3',
                ((('11', 'ref22'),), (('11', 'ref22'), ('11', 'ref22'))))
        self.assertFlattened(
            "11\x0044\x00\t11\x00ref00\x00value:4\n",
            ('11', '44'), 'value:4', ((), (('11', 'ref00'),)))


class TestCompiledBtree(tests.TestCase):

    def test_exists(self):
        # This is just to let the user know if they don't have the feature
        # available
        self.requireFeature(CompiledBtreeParserFeature)


class TestMultiBisectRight(tests.TestCase):

    def assertMultiBisectRight(self, offsets, search_keys, fixed_keys):
        self.assertEqual(offsets,
                         btree_index.BTreeGraphIndex._multi_bisect_right(
                            search_keys, fixed_keys))

    def test_after(self):
        self.assertMultiBisectRight([(1, ['b'])], ['b'], ['a'])
        self.assertMultiBisectRight([(3, ['e', 'f', 'g'])],
                                    ['e', 'f', 'g'], ['a', 'b', 'c'])

    def test_before(self):
        self.assertMultiBisectRight([(0, ['a'])], ['a'], ['b'])
        self.assertMultiBisectRight([(0, ['a', 'b', 'c', 'd'])],
                                    ['a', 'b', 'c', 'd'], ['e', 'f', 'g'])

    def test_exact(self):
        self.assertMultiBisectRight([(1, ['a'])], ['a'], ['a'])
        self.assertMultiBisectRight([(1, ['a']), (2, ['b'])], ['a', 'b'], ['a', 'b'])
        self.assertMultiBisectRight([(1, ['a']), (3, ['c'])],
                                    ['a', 'c'], ['a', 'b', 'c'])

    def test_inbetween(self):
        self.assertMultiBisectRight([(1, ['b'])], ['b'], ['a', 'c'])
        self.assertMultiBisectRight([(1, ['b', 'c', 'd']), (2, ['f', 'g'])],
                                    ['b', 'c', 'd', 'f', 'g'], ['a', 'e', 'h'])

    def test_mixed(self):
        self.assertMultiBisectRight([(0, ['a', 'b']), (2, ['d', 'e']),
                                     (4, ['g', 'h'])],
                                    ['a', 'b', 'd', 'e', 'g', 'h'],
                                    ['c', 'd', 'f', 'g'])


class TestExpandOffsets(tests.TestCase):

    def make_index(self, size, recommended_pages=None):
        """Make an index with a generic size.

        This doesn't actually create anything on disk, it just primes a
        BTreeGraphIndex with the recommended information.
        """
        index = btree_index.BTreeGraphIndex(get_transport('memory:///'),
                                            'test-index', size=size)
        if recommended_pages is not None:
            index._recommended_pages = recommended_pages
        return index

    def set_cached_offsets(self, index, cached_offsets):
        """Monkeypatch to give a canned answer for _get_offsets_for...()."""
        def _get_offsets_to_cached_pages():
            cached = set(cached_offsets)
            return cached
        index._get_offsets_to_cached_pages = _get_offsets_to_cached_pages

    def prepare_index(self, index, node_ref_lists, key_length, key_count,
                      row_lengths, cached_offsets):
        """Setup the BTreeGraphIndex with some pre-canned information."""
        index.node_ref_lists = node_ref_lists
        index._key_length = key_length
        index._key_count = key_count
        index._row_lengths = row_lengths
        index._compute_row_offsets()
        index._root_node = btree_index._InternalNode('internal\noffset=0\n')
        self.set_cached_offsets(index, cached_offsets)

    def make_100_node_index(self):
        index = self.make_index(4096*100, 6)
        # Consider we've already made a single request at the middle
        self.prepare_index(index, node_ref_lists=0, key_length=1,
                           key_count=1000, row_lengths=[1, 99],
                           cached_offsets=[0, 50])
        return index

    def make_1000_node_index(self):
        index = self.make_index(4096*1000, 6)
        # Pretend we've already made a single request in the middle
        self.prepare_index(index, node_ref_lists=0, key_length=1,
                           key_count=90000, row_lengths=[1, 9, 990],
                           cached_offsets=[0, 5, 500])
        return index

    def assertNumPages(self, expected_pages, index, size):
        index._size = size
        self.assertEqual(expected_pages, index._compute_total_pages_in_index())

    def assertExpandOffsets(self, expected, index, offsets):
        self.assertEqual(expected, index._expand_offsets(offsets),
                         'We did not get the expected value after expanding'
                         ' %s' % (offsets,))

    def test_default_recommended_pages(self):
        index = self.make_index(None)
        # local transport recommends 4096 byte reads, which is 1 page
        self.assertEqual(1, index._recommended_pages)

    def test__compute_total_pages_in_index(self):
        index = self.make_index(None)
        self.assertNumPages(1, index, 1024)
        self.assertNumPages(1, index, 4095)
        self.assertNumPages(1, index, 4096)
        self.assertNumPages(2, index, 4097)
        self.assertNumPages(2, index, 8192)
        self.assertNumPages(76, index, 4096*75 + 10)

    def test__find_layer_start_and_stop(self):
        index = self.make_1000_node_index()
        self.assertEqual((0, 1), index._find_layer_first_and_end(0))
        self.assertEqual((1, 10), index._find_layer_first_and_end(1))
        self.assertEqual((1, 10), index._find_layer_first_and_end(9))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(10))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(99))
        self.assertEqual((10, 1000), index._find_layer_first_and_end(999))

    def test_unknown_size(self):
        # We should not expand if we don't know the file size
        index = self.make_index(None, 10)
        self.assertExpandOffsets([0], index, [0])
        self.assertExpandOffsets([1, 4, 9], index, [1, 4, 9])

    def test_more_than_recommended(self):
        index = self.make_index(4096*100, 2)
        self.assertExpandOffsets([1, 10], index, [1, 10])
        self.assertExpandOffsets([1, 10, 20], index, [1, 10, 20])

    def test_read_all_from_root(self):
        index = self.make_index(4096*10, 20)
        self.assertExpandOffsets(range(10), index, [0])

    def test_read_all_when_cached(self):
        # We've read enough that we can grab all the rest in a single request
        index = self.make_index(4096*10, 5)
        self.prepare_index(index, node_ref_lists=0, key_length=1,
                           key_count=1000, row_lengths=[1, 9],
                           cached_offsets=[0, 1, 2, 5, 6])
        # It should fill the remaining nodes, regardless of the one requested
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [3])
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [8])
        self.assertExpandOffsets([3, 4, 7, 8, 9], index, [9])

    def test_no_root_node(self):
        index = self.make_index(4096*10, 5)
        self.assertExpandOffsets([0], index, [0])

    def test_include_neighbors(self):
        index = self.make_100_node_index()
        # We expand in both directions, until we have at least 'recommended'
        # pages
        self.assertExpandOffsets([9, 10, 11, 12, 13, 14, 15], index, [12])
        self.assertExpandOffsets([88, 89, 90, 91, 92, 93, 94], index, [91])
        # If we hit an 'edge' we continue in the other direction
        self.assertExpandOffsets([1, 2, 3, 4, 5, 6], index, [2])
        self.assertExpandOffsets([94, 95, 96, 97, 98, 99], index, [98])

        # Requesting many nodes will expand all locations equally
        self.assertExpandOffsets([1, 2, 3, 80, 81, 82], index, [2, 81])
        self.assertExpandOffsets([1, 2, 3, 9, 10, 11, 80, 81, 82], index,
                               [2, 10, 81])

    def test_stop_at_cached(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0, 10, 19])
        self.assertExpandOffsets([11, 12, 13, 14, 15, 16], index, [11])
        self.assertExpandOffsets([11, 12, 13, 14, 15, 16], index, [12])
        self.assertExpandOffsets([12, 13, 14, 15, 16, 17, 18], index, [15])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [16])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [17])
        self.assertExpandOffsets([13, 14, 15, 16, 17, 18], index, [18])

    def test_cannot_fully_expand(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0, 10, 12])
        # We don't go into an endless loop if we are bound by cached nodes
        self.assertExpandOffsets([11], index, [11])

    def test_overlap(self):
        index = self.make_100_node_index()
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [12, 13])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [11, 14])

    def test_stay_within_layer(self):
        index = self.make_1000_node_index()
        # When expanding a request, we won't read nodes from the next layer
        self.assertExpandOffsets([1, 2, 3, 4], index, [2])
        self.assertExpandOffsets([6, 7, 8, 9], index, [6])
        self.assertExpandOffsets([6, 7, 8, 9], index, [9])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15], index, [10])
        self.assertExpandOffsets([10, 11, 12, 13, 14, 15, 16], index, [13])

        self.set_cached_offsets(index, [0, 4, 12])
        self.assertExpandOffsets([5, 6, 7, 8, 9], index, [7])
        self.assertExpandOffsets([10, 11], index, [11])

    def test_small_requests_unexpanded(self):
        index = self.make_100_node_index()
        self.set_cached_offsets(index, [0])
        self.assertExpandOffsets([1], index, [1])
        self.assertExpandOffsets([50], index, [50])
        # If we request more than one node, then we'll expand
        self.assertExpandOffsets([49, 50, 51, 59, 60, 61], index, [50, 60])

        # The first pass does not expand
        index = self.make_1000_node_index()
        self.set_cached_offsets(index, [0])
        self.assertExpandOffsets([1], index, [1])
        self.set_cached_offsets(index, [0, 1])
        self.assertExpandOffsets([100], index, [100])
        self.set_cached_offsets(index, [0, 1, 100])
        # But after the first depth, we will expand
        self.assertExpandOffsets([2, 3, 4, 5, 6, 7], index, [2])
        self.assertExpandOffsets([2, 3, 4, 5, 6, 7], index, [4])
        self.set_cached_offsets(index, [0, 1, 2, 3, 4, 5, 6, 7, 100])
        self.assertExpandOffsets([102, 103, 104, 105, 106, 107, 108], index,
                                 [105])
