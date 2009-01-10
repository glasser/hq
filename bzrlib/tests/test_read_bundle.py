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

"""Test read_bundle works properly across various transports."""

import cStringIO
import os

import bzrlib.bundle
from bzrlib.bundle.serializer import write_bundle
import bzrlib.bzrdir
import bzrlib.errors as errors
from bzrlib import tests
from bzrlib.tests.test_transport import TestTransportImplementation
from bzrlib.tests.test_transport_implementations import TransportTestProviderAdapter
import bzrlib.transport
from bzrlib.transport.memory import MemoryTransport
import bzrlib.urlutils


def load_tests(standard_tests, module, loader):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()
    adapter = TransportTestProviderAdapter()
    for test in tests.iter_suite_tests(standard_tests):
        result.addTests(adapter.adapt(test))
    return result


def create_bundle_file(test_case):
    test_case.build_tree(['tree/', 'tree/a', 'tree/subdir/'])

    format = bzrlib.bzrdir.BzrDirFormat.get_default_format()

    bzrdir = format.initialize('tree')
    repo = bzrdir.create_repository()
    branch = repo.bzrdir.create_branch()
    wt = branch.bzrdir.create_workingtree()

    wt.add(['a', 'subdir/'])
    wt.commit('new project', rev_id='commit-1')

    out = cStringIO.StringIO()
    rev_ids = write_bundle(wt.branch.repository,
                           wt.get_parent_ids()[0], 'null:', out)
    out.seek(0)
    return out, wt


class TestReadBundleFromURL(TestTransportImplementation):
    """Test that read_bundle works properly across multiple transports"""

    def get_url(self, relpath=''):
        return bzrlib.urlutils.join(self._server.get_url(), relpath)

    def create_test_bundle(self):
        out, wt = create_bundle_file(self)
        if self.get_transport().is_readonly():
            f = open('test_bundle', 'wb')
            f.write(out.getvalue())
            f.close()
        else:
            self.get_transport().put_file('test_bundle', out)
            self.log('Put to: %s', self.get_url('test_bundle'))
        return wt

    def test_read_bundle_from_url(self):
        self._captureVar('BZR_NO_SMART_VFS', None)
        wt = self.create_test_bundle()
        if wt is None:
            return
        info = bzrlib.bundle.read_bundle_from_url(
                    unicode(self.get_url('test_bundle')))
        revision = info.real_revisions[-1]
        self.assertEqual('commit-1', revision.revision_id)

    def test_read_fail(self):
        # Trying to read from a directory, or non-bundle file
        # should fail with NotABundle
        self._captureVar('BZR_NO_SMART_VFS', None)
        wt = self.create_test_bundle()
        if wt is None:
            return

        self.assertRaises(errors.NotABundle, 
            bzrlib.bundle.read_bundle_from_url, 
            self.get_url('tree'))
        self.assertRaises(errors.NotABundle, 
            bzrlib.bundle.read_bundle_from_url, 
            self.get_url('tree/a'))

    def test_read_mergeable_populates_possible_transports(self):
        self._captureVar('BZR_NO_SMART_VFS', None)
        wt = self.create_test_bundle()
        if wt is None:
            return
        possible_transports = []
        url = unicode(self.get_url('test_bundle'))
        info = bzrlib.bundle.read_mergeable_from_url(url,
            possible_transports=possible_transports)
        self.assertEqual(1, len(possible_transports))
