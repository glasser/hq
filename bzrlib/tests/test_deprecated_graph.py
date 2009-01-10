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

from bzrlib.tests import TestCase
from bzrlib.deprecated_graph import node_distances, nodes_by_distance, Graph


class TestBase(TestCase):

    def edge_add(self, *args):
        for start, end in zip(args[:-1], args[1:]):
            if start not in self.graph:
                self.graph[start] = {}
            if end not in self.graph:
                self.graph[end] = {}
            self.graph[start][end] = 1

    def setUp(self):
        TestCase.setUp(self)
        self.graph = {}
        self.edge_add('A', 'B', 'C', 'D')
        self.edge_add('A', 'E', 'F', 'C')
        self.edge_add('A', 'G', 'H', 'I', 'B')
        self.edge_add('A', 'J', 'K', 'L', 'M', 'N')
        self.edge_add('O', 'N')

    def node_descendants(self):
        descendants = {'A':set()}
        for node in self.graph:
            for ancestor in self.graph[node]:
                if ancestor not in descendants:
                    descendants[ancestor] = set()
                descendants[ancestor].add(node)
        return descendants
    
    def test_distances(self):
        descendants = self.node_descendants()
        distances = node_distances(self.graph, descendants, 'A')
        nodes = nodes_by_distance(distances)
        self.assertEqual(nodes[0], 'D')
        self.assert_(nodes[1] in ('N', 'C'))
        self.assert_(nodes[2] in ('N', 'C'))
        self.assert_(nodes[3] in ('B', 'M'))
        self.assert_(nodes[4] in ('B', 'M'))

        #Ensure we don't shortcut through B when there's only a difference of
        # 1 in distance
        self.graph = {}
        self.edge_add('A', 'B', 'C')
        self.edge_add('A', 'D', 'E', 'C')
        descendants = self.node_descendants()
        distances = node_distances(self.graph, descendants, 'A')
        self.assertEqual(distances['C'], 3)


class TestGraph(TestCase):

    def test_get_descendants(self):
        # Graph objects let you get a descendants graph in 
        # node: {direct-children:distance} which contains
        # known children, including ghost children
        graph = Graph()
        graph.add_ghost('ghost')
        graph.add_node('rev1', ['ghost'])
        # check the result contains ghosts:
        self.assertEqual({'ghost': {'rev1': 1}, 'rev1': {}},
                         graph.get_descendants())
