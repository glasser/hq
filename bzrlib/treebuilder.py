# Copyright (C) 2006 Canonical Ltd
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

"""TreeBuilder helper class.

TreeBuilders are used to build trees of various shapres or properties. This 
can be extremely useful in testing for instance.
"""

from bzrlib import errors


class TreeBuilder(object):
    """A TreeBuilder allows the creation of specific content in one tree at a
    time.
    """

    def __init__(self):
        """Construct a TreeBuilder."""
        self._tree = None
        self._root_done = False

    def build(self, recipe):
        """Build recipe into the current tree.

        :param recipe: A sequence of paths. For each path, the corresponding
            path in the current tree is created and added. If the path ends in
            '/' then a directory is added, otherwise a regular file is added.
        """
        self._ensure_building()
        if not self._root_done:
            self._tree.add('', 'root-id', 'directory')
            self._root_done = True
        for name in recipe:
            if name[-1] == '/':
                self._tree.mkdir(name[:-1])
            else:
                end = '\n'
                content = "contents of %s%s" % (name.encode('utf-8'), end)
                self._tree.add(name, None, 'file')
                file_id = self._tree.path2id(name)
                self._tree.put_file_bytes_non_atomic(file_id, content)

    def _ensure_building(self):
        """Raise NotBuilding if there is no current tree being built."""
        if self._tree is None:
            raise errors.NotBuilding
            
    def finish_tree(self):
        """Finish building the current tree."""
        self._ensure_building()
        tree = self._tree
        self._tree = None
        tree.unlock()

    def start_tree(self, tree):
        """Start building on tree.
        
        :param tree: A tree to start building on. It must provide the 
            MutableTree interface.
        """
        if self._tree is not None:
            raise errors.AlreadyBuilding
        self._tree = tree
        self._tree.lock_tree_write()
