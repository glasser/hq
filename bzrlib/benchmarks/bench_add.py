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

"""Tests for bzr add performance."""


from bzrlib.benchmarks import Benchmark


class AddBenchmark(Benchmark):
    """Benchmarks for 'bzr add'"""

    def test_one_add_kernel_like_tree(self):
        """Adding a kernel sized tree should be bearable (<5secs) fast.""" 
        self.make_kernel_like_tree(link_working=True)
        # on roberts machine: this originally took:  25936ms/32244ms
        # after making smart_add use the parent_ie:   5033ms/ 9368ms
        # plain os.walk takes 213ms on this tree
        self.time(self.run_bzr, 'add')
