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

"""Tests for bzr osutils functions performance."""


from bzrlib.benchmarks import Benchmark
import bzrlib.osutils as osutils


class WalkDirsBenchmark(Benchmark):
    """Benchmarks for `bzrlib.osutils.walkdirs`"""

    def test_walkdirs_kernel_like_tree(self):
        """Walking a kernel sized tree is fast!(150ms)."""
        self.make_kernel_like_tree(link_working=True)
        # on roberts machine: this originally took:  157ms/4177ms
        # plain os.walk takes 213ms on this tree
        # with the pyrex readdir module:              77ms/5423ms
        def dowalk():
            for dirblock in osutils.walkdirs('.'):
                if dirblock[0][1] == '.bzr':
                    del dirblock[0]
        self.time(dowalk)
