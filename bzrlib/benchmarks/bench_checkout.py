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

"""Tests for bzr tree building (checkout) performance."""


from bzrlib.benchmarks import Benchmark


class CheckoutBenchmark(Benchmark):
    """Benchmarks for ``'bzr checkout'`` performance."""

    def test_build_kernel_like_tree(self):
        """Checkout of a clean kernel sized tree should be (<10secs)."""
        self.make_kernel_like_committed_tree(link_bzr=True)
        self.time(self.run_bzr, ['checkout', '--lightweight', '.', 'acheckout'])
