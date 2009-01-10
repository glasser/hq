# Copyright (C) 2006, 2007, 2008 Canonical Ltd
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

"""Tests for remote bzrdir/branch/repo/etc

These are proxy objects which act on remote objects by sending messages
through a smart client.  The proxies are to be created when attempting to open
the object given a transport that supports smartserver rpc operations. 

These tests correspond to tests.test_smart, which exercises the server side.
"""

import bz2
from cStringIO import StringIO

from bzrlib import (
    bzrdir,
    config,
    errors,
    graph,
    pack,
    remote,
    repository,
    tests,
    urlutils,
    )
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.remote import (
    RemoteBranch,
    RemoteBzrDir,
    RemoteBzrDirFormat,
    RemoteRepository,
    )
from bzrlib.revision import NULL_REVISION
from bzrlib.smart import server, medium
from bzrlib.smart.client import _SmartClient
from bzrlib.symbol_versioning import one_four
from bzrlib.transport import get_transport, http
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.remote import (
    RemoteTransport,
    RemoteSSHTransport,
    RemoteTCPTransport,
)


class BasicRemoteObjectTests(tests.TestCaseWithTransport):

    def setUp(self):
        self.transport_server = server.SmartTCPServer_for_testing
        super(BasicRemoteObjectTests, self).setUp()
        self.transport = self.get_transport()
        # make a branch that can be opened over the smart transport
        self.local_wt = BzrDir.create_standalone_workingtree('.')

    def tearDown(self):
        self.transport.disconnect()
        tests.TestCaseWithTransport.tearDown(self)

    def test_create_remote_bzrdir(self):
        b = remote.RemoteBzrDir(self.transport)
        self.assertIsInstance(b, BzrDir)

    def test_open_remote_branch(self):
        # open a standalone branch in the working directory
        b = remote.RemoteBzrDir(self.transport)
        branch = b.open_branch()
        self.assertIsInstance(branch, Branch)

    def test_remote_repository(self):
        b = BzrDir.open_from_transport(self.transport)
        repo = b.open_repository()
        revid = u'\xc823123123'.encode('utf8')
        self.assertFalse(repo.has_revision(revid))
        self.local_wt.commit(message='test commit', rev_id=revid)
        self.assertTrue(repo.has_revision(revid))

    def test_remote_branch_revision_history(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertEqual([], b.revision_history())
        r1 = self.local_wt.commit('1st commit')
        r2 = self.local_wt.commit('1st commit', rev_id=u'\xc8'.encode('utf8'))
        self.assertEqual([r1, r2], b.revision_history())

    def test_find_correct_format(self):
        """Should open a RemoteBzrDir over a RemoteTransport"""
        fmt = BzrDirFormat.find_format(self.transport)
        self.assertTrue(RemoteBzrDirFormat
                        in BzrDirFormat._control_server_formats)
        self.assertIsInstance(fmt, remote.RemoteBzrDirFormat)

    def test_open_detected_smart_format(self):
        fmt = BzrDirFormat.find_format(self.transport)
        d = fmt.open(self.transport)
        self.assertIsInstance(d, BzrDir)

    def test_remote_branch_repr(self):
        b = BzrDir.open_from_transport(self.transport).open_branch()
        self.assertStartsWith(str(b), 'RemoteBranch(')


class FakeRemoteTransport(object):
    """This class provides the minimum support for use in place of a RemoteTransport.
    
    It doesn't actually transmit requests, but rather expects them to be
    handled by a FakeClient which holds canned responses.  It does not allow
    any vfs access, therefore is not suitable for testing any operation that
    will fallback to vfs access.  Backing the test by an instance of this
    class guarantees that it's - done using non-vfs operations.
    """

    _default_url = 'fakeremotetransport://host/path/'

    def __init__(self, url=None):
        if url is None:
            url = self._default_url
        self.base = url

    def __repr__(self):
        return "%r(%r)" % (self.__class__.__name__,
            self.base)

    def clone(self, relpath):
        return FakeRemoteTransport(urlutils.join(self.base, relpath))

    def get(self, relpath):
        # only get is specifically stubbed out, because it's usually the first
        # thing we do.  anything else will fail with an AttributeError.
        raise AssertionError("%r doesn't support file access to %r"
            % (self, relpath))



class FakeProtocol(object):
    """Lookalike SmartClientRequestProtocolOne allowing body reading tests."""

    def __init__(self, body, fake_client):
        self.body = body
        self._body_buffer = None
        self._fake_client = fake_client

    def read_body_bytes(self, count=-1):
        if self._body_buffer is None:
            self._body_buffer = StringIO(self.body)
        bytes = self._body_buffer.read(count)
        if self._body_buffer.tell() == len(self._body_buffer.getvalue()):
            self._fake_client.expecting_body = False
        return bytes

    def cancel_read_body(self):
        self._fake_client.expecting_body = False

    def read_streamed_body(self):
        return self.body


class FakeClient(_SmartClient):
    """Lookalike for _SmartClient allowing testing."""
    
    def __init__(self, fake_medium_base='fake base'):
        """Create a FakeClient."""
        self.responses = []
        self._calls = []
        self.expecting_body = False
        # if non-None, this is the list of expected calls, with only the
        # method name and arguments included.  the body might be hard to
        # compute so is not included
        self._expected_calls = None
        _SmartClient.__init__(self, FakeMedium(self._calls, fake_medium_base))

    def add_expected_call(self, call_name, call_args, response_type,
        response_args, response_body=None):
        if self._expected_calls is None:
            self._expected_calls = []
        self._expected_calls.append((call_name, call_args))
        self.responses.append((response_type, response_args, response_body))

    def add_success_response(self, *args):
        self.responses.append(('success', args, None))

    def add_success_response_with_body(self, body, *args):
        self.responses.append(('success', args, body))

    def add_error_response(self, *args):
        self.responses.append(('error', args))

    def add_unknown_method_response(self, verb):
        self.responses.append(('unknown', verb))

    def finished_test(self):
        if self._expected_calls:
            raise AssertionError("%r finished but was still expecting %r"
                % (self, self._expected_calls[0]))

    def _get_next_response(self):
        try:
            response_tuple = self.responses.pop(0)
        except IndexError, e:
            raise AssertionError("%r didn't expect any more calls"
                % (self,))
        if response_tuple[0] == 'unknown':
            raise errors.UnknownSmartMethod(response_tuple[1])
        elif response_tuple[0] == 'error':
            raise errors.ErrorFromSmartServer(response_tuple[1])
        return response_tuple

    def _check_call(self, method, args):
        if self._expected_calls is None:
            # the test should be updated to say what it expects
            return
        try:
            next_call = self._expected_calls.pop(0)
        except IndexError:
            raise AssertionError("%r didn't expect any more calls "
                "but got %r%r"
                % (self, method, args,))
        if method != next_call[0] or args != next_call[1]:
            raise AssertionError("%r expected %r%r "
                "but got %r%r"
                % (self, next_call[0], next_call[1], method, args,))

    def call(self, method, *args):
        self._check_call(method, args)
        self._calls.append(('call', method, args))
        return self._get_next_response()[1]

    def call_expecting_body(self, method, *args):
        self._check_call(method, args)
        self._calls.append(('call_expecting_body', method, args))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)

    def call_with_body_bytes_expecting_body(self, method, args, body):
        self._check_call(method, args)
        self._calls.append(('call_with_body_bytes_expecting_body', method,
            args, body))
        result = self._get_next_response()
        self.expecting_body = True
        return result[1], FakeProtocol(result[2], self)


class FakeMedium(medium.SmartClientMedium):

    def __init__(self, client_calls, base):
        medium.SmartClientMedium.__init__(self, base)
        self._client_calls = client_calls

    def disconnect(self):
        self._client_calls.append(('disconnect medium',))


class TestVfsHas(tests.TestCase):

    def test_unicode_path(self):
        client = FakeClient('/')
        client.add_success_response('yes',)
        transport = RemoteTransport('bzr://localhost/', _client=client)
        filename = u'/hell\u00d8'.encode('utf8')
        result = transport.has(filename)
        self.assertEqual(
            [('call', 'has', (filename,))],
            client._calls)
        self.assertTrue(result)


class Test_ClientMedium_remote_path_from_transport(tests.TestCase):
    """Tests for the behaviour of client_medium.remote_path_from_transport."""

    def assertRemotePath(self, expected, client_base, transport_base):
        """Assert that the result of
        SmartClientMedium.remote_path_from_transport is the expected value for
        a given client_base and transport_base.
        """
        client_medium = medium.SmartClientMedium(client_base)
        transport = get_transport(transport_base)
        result = client_medium.remote_path_from_transport(transport)
        self.assertEqual(expected, result)

    def test_remote_path_from_transport(self):
        """SmartClientMedium.remote_path_from_transport calculates a URL for
        the given transport relative to the root of the client base URL.
        """
        self.assertRemotePath('xyz/', 'bzr://host/path', 'bzr://host/xyz')
        self.assertRemotePath(
            'path/xyz/', 'bzr://host/path', 'bzr://host/path/xyz')

    def assertRemotePathHTTP(self, expected, transport_base, relpath):
        """Assert that the result of
        HttpTransportBase.remote_path_from_transport is the expected value for
        a given transport_base and relpath of that transport.  (Note that
        HttpTransportBase is a subclass of SmartClientMedium)
        """
        base_transport = get_transport(transport_base)
        client_medium = base_transport.get_smart_medium()
        cloned_transport = base_transport.clone(relpath)
        result = client_medium.remote_path_from_transport(cloned_transport)
        self.assertEqual(expected, result)
        
    def test_remote_path_from_transport_http(self):
        """Remote paths for HTTP transports are calculated differently to other
        transports.  They are just relative to the client base, not the root
        directory of the host.
        """
        for scheme in ['http:', 'https:', 'bzr+http:', 'bzr+https:']:
            self.assertRemotePathHTTP(
                '../xyz/', scheme + '//host/path', '../xyz/')
            self.assertRemotePathHTTP(
                'xyz/', scheme + '//host/path', 'xyz/')


class Test_ClientMedium_remote_is_at_least(tests.TestCase):
    """Tests for the behaviour of client_medium.remote_is_at_least."""

    def test_initially_unlimited(self):
        """A fresh medium assumes that the remote side supports all
        versions.
        """
        client_medium = medium.SmartClientMedium('dummy base')
        self.assertFalse(client_medium._is_remote_before((99, 99)))
    
    def test__remember_remote_is_before(self):
        """Calling _remember_remote_is_before ratchets down the known remote
        version.
        """
        client_medium = medium.SmartClientMedium('dummy base')
        # Mark the remote side as being less than 1.6.  The remote side may
        # still be 1.5.
        client_medium._remember_remote_is_before((1, 6))
        self.assertTrue(client_medium._is_remote_before((1, 6)))
        self.assertFalse(client_medium._is_remote_before((1, 5)))
        # Calling _remember_remote_is_before again with a lower value works.
        client_medium._remember_remote_is_before((1, 5))
        self.assertTrue(client_medium._is_remote_before((1, 5)))
        # You cannot call _remember_remote_is_before with a larger value.
        self.assertRaises(
            AssertionError, client_medium._remember_remote_is_before, (1, 9))


class TestBzrDirOpenBranch(tests.TestCase):

    def test_branch_present(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_expected_call(
            'BzrDir.open_branch', ('quack/',),
            'success', ('ok', ''))
        client.add_expected_call(
            'BzrDir.find_repositoryV2', ('quack/',),
            'success', ('ok', '', 'no', 'no', 'no'))
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('quack/',),
            'error', ('NotStacked',))
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_branch()
        self.assertIsInstance(result, RemoteBranch)
        self.assertEqual(bzrdir, result.bzrdir)
        client.finished_test()

    def test_branch_missing(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_error_response('nobranch')
        bzrdir = RemoteBzrDir(transport, _client=client)
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch)
        self.assertEqual(
            [('call', 'BzrDir.open_branch', ('quack/',))],
            client._calls)

    def test__get_tree_branch(self):
        # _get_tree_branch is a form of open_branch, but it should only ask for
        # branch opening, not any other network requests.
        calls = []
        def open_branch():
            calls.append("Called")
            return "a-branch"
        transport = MemoryTransport()
        # no requests on the network - catches other api calls being made.
        client = FakeClient(transport.base)
        bzrdir = RemoteBzrDir(transport, _client=client)
        # patch the open_branch call to record that it was called.
        bzrdir.open_branch = open_branch
        self.assertEqual((None, "a-branch"), bzrdir._get_tree_branch())
        self.assertEqual(["Called"], calls)
        self.assertEqual([], client._calls)

    def test_url_quoting_of_path(self):
        # Relpaths on the wire should not be URL-escaped.  So "~" should be
        # transmitted as "~", not "%7E".
        transport = RemoteTCPTransport('bzr://localhost/~hello/')
        client = FakeClient(transport.base)
        client.add_expected_call(
            'BzrDir.open_branch', ('~hello/',),
            'success', ('ok', ''))
        client.add_expected_call(
            'BzrDir.find_repositoryV2', ('~hello/',),
            'success', ('ok', '', 'no', 'no', 'no'))
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('~hello/',),
            'error', ('NotStacked',))
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_branch()
        client.finished_test()

    def check_open_repository(self, rich_root, subtrees, external_lookup='no'):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        if rich_root:
            rich_response = 'yes'
        else:
            rich_response = 'no'
        if subtrees:
            subtree_response = 'yes'
        else:
            subtree_response = 'no'
        client = FakeClient(transport.base)
        client.add_success_response(
            'ok', '', rich_response, subtree_response, external_lookup)
        bzrdir = RemoteBzrDir(transport, _client=client)
        result = bzrdir.open_repository()
        self.assertEqual(
            [('call', 'BzrDir.find_repositoryV2', ('quack/',))],
            client._calls)
        self.assertIsInstance(result, RemoteRepository)
        self.assertEqual(bzrdir, result.bzrdir)
        self.assertEqual(rich_root, result._format.rich_root_data)
        self.assertEqual(subtrees, result._format.supports_tree_reference)

    def test_open_repository_sets_format_attributes(self):
        self.check_open_repository(True, True)
        self.check_open_repository(False, True)
        self.check_open_repository(True, False)
        self.check_open_repository(False, False)
        self.check_open_repository(False, False, 'yes')

    def test_old_server(self):
        """RemoteBzrDirFormat should fail to probe if the server version is too
        old.
        """
        self.assertRaises(errors.NotBranchError,
            RemoteBzrDirFormat.probe_transport, OldServerTransport())


class TestBzrDirOpenRepository(tests.TestCase):

    def test_backwards_compat_1_2(self):
        transport = MemoryTransport()
        transport.mkdir('quack')
        transport = transport.clone('quack')
        client = FakeClient(transport.base)
        client.add_unknown_method_response('RemoteRepository.find_repositoryV2')
        client.add_success_response('ok', '', 'no', 'no')
        bzrdir = RemoteBzrDir(transport, _client=client)
        repo = bzrdir.open_repository()
        self.assertEqual(
            [('call', 'BzrDir.find_repositoryV2', ('quack/',)),
             ('call', 'BzrDir.find_repository', ('quack/',))],
            client._calls)


class OldSmartClient(object):
    """A fake smart client for test_old_version that just returns a version one
    response to the 'hello' (query version) command.
    """

    def get_request(self):
        input_file = StringIO('ok\x011\n')
        output_file = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input_file, output_file)
        return medium.SmartClientStreamMediumRequest(client_medium)

    def protocol_version(self):
        return 1


class OldServerTransport(object):
    """A fake transport for test_old_server that reports it's smart server
    protocol version as version one.
    """

    def __init__(self):
        self.base = 'fake:'

    def get_smart_client(self):
        return OldSmartClient()


class RemoteBranchTestCase(tests.TestCase):

    def make_remote_branch(self, transport, client):
        """Make a RemoteBranch using 'client' as its _SmartClient.
        
        A RemoteBzrDir and RemoteRepository will also be created to fill out
        the RemoteBranch, albeit with stub values for some of their attributes.
        """
        # we do not want bzrdir to make any remote calls, so use False as its
        # _client.  If it tries to make a remote call, this will fail
        # immediately.
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return RemoteBranch(bzrdir, repo, _client=client)


class TestBranchLastRevisionInfo(RemoteBranchTestCase):

    def test_empty_branch(self):
        # in an empty branch we decode the response properly
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('quack/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.last_revision_info', ('quack/',),
            'success', ('ok', '0', 'null:'))
        transport.mkdir('quack')
        transport = transport.clone('quack')
        branch = self.make_remote_branch(transport, client)
        result = branch.last_revision_info()
        client.finished_test()
        self.assertEqual((0, NULL_REVISION), result)

    def test_non_empty_branch(self):
        # in a non-empty branch we also decode the response properly
        revid = u'\xc8'.encode('utf8')
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('kwaak/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.last_revision_info', ('kwaak/',),
            'success', ('ok', '2', revid))
        transport.mkdir('kwaak')
        transport = transport.clone('kwaak')
        branch = self.make_remote_branch(transport, client)
        result = branch.last_revision_info()
        self.assertEqual((2, revid), result)


class TestBranch_get_stacked_on_url(tests.TestCaseWithMemoryTransport):
    """Test Branch._get_stacked_on_url rpc"""

    def test_get_stacked_on_invalid_url(self):
        raise tests.KnownFailure('opening a branch requires the server to open the fallback repository')
        transport = FakeRemoteTransport('fakeremotetransport:///')
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('.',),
            'success', ('ok', 'file:///stacked/on'))
        bzrdir = RemoteBzrDir(transport, _client=client)
        branch = RemoteBranch(bzrdir, None, _client=client)
        result = branch.get_stacked_on_url()
        self.assertEqual(
            'file:///stacked/on', result)

    def test_backwards_compatible(self):
        # like with bzr1.6 with no Branch.get_stacked_on_url rpc
        base_branch = self.make_branch('base', format='1.6')
        stacked_branch = self.make_branch('stacked', format='1.6')
        stacked_branch.set_stacked_on_url('../base')
        client = FakeClient(self.get_url())
        client.add_expected_call(
            'BzrDir.open_branch', ('stacked/',),
            'success', ('ok', ''))
        client.add_expected_call(
            'BzrDir.find_repositoryV2', ('stacked/',),
            'success', ('ok', '', 'no', 'no', 'no'))
        # called twice, once from constructor and then again by us
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('stacked/',),
            'unknown', ('Branch.get_stacked_on_url',))
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('stacked/',),
            'unknown', ('Branch.get_stacked_on_url',))
        # this will also do vfs access, but that goes direct to the transport
        # and isn't seen by the FakeClient.
        bzrdir = RemoteBzrDir(self.get_transport('stacked'), _client=client)
        branch = bzrdir.open_branch()
        result = branch.get_stacked_on_url()
        self.assertEqual('../base', result)
        client.finished_test()
        # it's in the fallback list both for the RemoteRepository and its vfs
        # repository
        self.assertEqual(1, len(branch.repository._fallback_repositories))
        self.assertEqual(1,
            len(branch.repository._real_repository._fallback_repositories))

    def test_get_stacked_on_real_branch(self):
        base_branch = self.make_branch('base', format='1.6')
        stacked_branch = self.make_branch('stacked', format='1.6')
        stacked_branch.set_stacked_on_url('../base')
        client = FakeClient(self.get_url())
        client.add_expected_call(
            'BzrDir.open_branch', ('stacked/',),
            'success', ('ok', ''))
        client.add_expected_call(
            'BzrDir.find_repositoryV2', ('stacked/',),
            'success', ('ok', '', 'no', 'no', 'no'))
        # called twice, once from constructor and then again by us
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('stacked/',),
            'success', ('ok', '../base'))
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('stacked/',),
            'success', ('ok', '../base'))
        bzrdir = RemoteBzrDir(self.get_transport('stacked'), _client=client)
        branch = bzrdir.open_branch()
        result = branch.get_stacked_on_url()
        self.assertEqual('../base', result)
        client.finished_test()
        # it's in the fallback list both for the RemoteRepository and its vfs
        # repository
        self.assertEqual(1, len(branch.repository._fallback_repositories))
        self.assertEqual(1,
            len(branch.repository._real_repository._fallback_repositories))


class TestBranchSetLastRevision(RemoteBranchTestCase):

    def test_set_empty(self):
        # set_revision_history([]) is translated to calling
        # Branch.set_last_revision(path, '') on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('branch/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.lock_write', ('branch/', '', ''),
            'success', ('ok', 'branch token', 'repo token'))
        client.add_expected_call(
            'Branch.set_last_revision', ('branch/', 'branch token', 'repo token', 'null:',),
            'success', ('ok',))
        client.add_expected_call(
            'Branch.unlock', ('branch/', 'branch token', 'repo token'),
            'success', ('ok',))
        branch = self.make_remote_branch(transport, client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        branch.lock_write()
        result = branch.set_revision_history([])
        branch.unlock()
        self.assertEqual(None, result)
        client.finished_test()

    def test_set_nonempty(self):
        # set_revision_history([rev-id1, ..., rev-idN]) is translated to calling
        # Branch.set_last_revision(path, rev-idN) on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')

        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('branch/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.lock_write', ('branch/', '', ''),
            'success', ('ok', 'branch token', 'repo token'))
        client.add_expected_call(
            'Branch.set_last_revision', ('branch/', 'branch token', 'repo token', 'rev-id2',),
            'success', ('ok',))
        client.add_expected_call(
            'Branch.unlock', ('branch/', 'branch token', 'repo token'),
            'success', ('ok',))
        branch = self.make_remote_branch(transport, client)
        # This is a hack to work around the problem that RemoteBranch currently
        # unnecessarily invokes _ensure_real upon a call to lock_write.
        branch._ensure_real = lambda: None
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        result = branch.set_revision_history(['rev-id1', 'rev-id2'])
        branch.unlock()
        self.assertEqual(None, result)
        client.finished_test()

    def test_no_such_revision(self):
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        # A response of 'NoSuchRevision' is translated into an exception.
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('branch/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.lock_write', ('branch/', '', ''),
            'success', ('ok', 'branch token', 'repo token'))
        client.add_expected_call(
            'Branch.set_last_revision', ('branch/', 'branch token', 'repo token', 'rev-id',),
            'error', ('NoSuchRevision', 'rev-id'))
        client.add_expected_call(
            'Branch.unlock', ('branch/', 'branch token', 'repo token'),
            'success', ('ok',))

        branch = self.make_remote_branch(transport, client)
        branch.lock_write()
        self.assertRaises(
            errors.NoSuchRevision, branch.set_revision_history, ['rev-id'])
        branch.unlock()
        client.finished_test()

    def test_tip_change_rejected(self):
        """TipChangeRejected responses cause a TipChangeRejected exception to
        be raised.
        """
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        rejection_msg_unicode = u'rejection message\N{INTERROBANG}'
        rejection_msg_utf8 = rejection_msg_unicode.encode('utf8')
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('branch/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.lock_write', ('branch/', '', ''),
            'success', ('ok', 'branch token', 'repo token'))
        client.add_expected_call(
            'Branch.set_last_revision', ('branch/', 'branch token', 'repo token', 'rev-id',),
            'error', ('TipChangeRejected', rejection_msg_utf8))
        client.add_expected_call(
            'Branch.unlock', ('branch/', 'branch token', 'repo token'),
            'success', ('ok',))
        branch = self.make_remote_branch(transport, client)
        branch._ensure_real = lambda: None
        branch.lock_write()
        self.addCleanup(branch.unlock)
        # The 'TipChangeRejected' error response triggered by calling
        # set_revision_history causes a TipChangeRejected exception.
        err = self.assertRaises(
            errors.TipChangeRejected, branch.set_revision_history, ['rev-id'])
        # The UTF-8 message from the response has been decoded into a unicode
        # object.
        self.assertIsInstance(err.msg, unicode)
        self.assertEqual(rejection_msg_unicode, err.msg)
        branch.unlock()
        client.finished_test()


class TestBranchSetLastRevisionInfo(RemoteBranchTestCase):

    def test_set_last_revision_info(self):
        # set_last_revision_info(num, 'rev-id') is translated to calling
        # Branch.set_last_revision_info(num, 'rev-id') on the wire.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response('NotStacked')
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_success_response('ok')
        # unlock
        client.add_success_response('ok')

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []
        result = branch.set_last_revision_info(1234, 'a-revision-id')
        self.assertEqual(
            [('call', 'Branch.set_last_revision_info',
                ('branch/', 'branch token', 'repo token',
                 '1234', 'a-revision-id'))],
            client._calls)
        self.assertEqual(None, result)

    def test_no_such_revision(self):
        # A response of 'NoSuchRevision' is translated into an exception.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response('NotStacked')
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('NoSuchRevision', 'revid')
        # unlock
        client.add_success_response('ok')

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        self.assertRaises(
            errors.NoSuchRevision, branch.set_last_revision_info, 123, 'revid')
        branch.unlock()

    def lock_remote_branch(self, branch):
        """Trick a RemoteBranch into thinking it is locked."""
        branch._lock_mode = 'w'
        branch._lock_count = 2
        branch._lock_token = 'branch token'
        branch._repo_lock_token = 'repo token'
        branch.repository._lock_mode = 'w'
        branch.repository._lock_count = 2
        branch.repository._lock_token = 'repo token'

    def test_backwards_compatibility(self):
        """If the server does not support the Branch.set_last_revision_info
        verb (which is new in 1.4), then the client falls back to VFS methods.
        """
        # This test is a little messy.  Unlike most tests in this file, it
        # doesn't purely test what a Remote* object sends over the wire, and
        # how it reacts to responses from the wire.  It instead relies partly
        # on asserting that the RemoteBranch will call
        # self._real_branch.set_last_revision_info(...).

        # First, set up our RemoteBranch with a FakeClient that raises
        # UnknownSmartMethod, and a StubRealBranch that logs how it is called.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('branch/',),
            'error', ('NotStacked',))
        client.add_expected_call(
            'Branch.set_last_revision_info',
            ('branch/', 'branch token', 'repo token', '1234', 'a-revision-id',),
            'unknown', 'Branch.set_last_revision_info')

        branch = self.make_remote_branch(transport, client)
        class StubRealBranch(object):
            def __init__(self):
                self.calls = []
            def set_last_revision_info(self, revno, revision_id):
                self.calls.append(
                    ('set_last_revision_info', revno, revision_id))
            def _clear_cached_state(self):
                pass
        real_branch = StubRealBranch()
        branch._real_branch = real_branch
        self.lock_remote_branch(branch)

        # Call set_last_revision_info, and verify it behaved as expected.
        result = branch.set_last_revision_info(1234, 'a-revision-id')
        self.assertEqual(
            [('set_last_revision_info', 1234, 'a-revision-id')],
            real_branch.calls)
        client.finished_test()

    def test_unexpected_error(self):
        # If the server sends an error the client doesn't understand, it gets
        # turned into an UnknownErrorFromSmartServer, which is presented as a
        # non-internal error to the user.
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response('NotStacked')
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('UnexpectedError')
        # unlock
        client.add_success_response('ok')

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        client._calls = []

        err = self.assertRaises(
            errors.UnknownErrorFromSmartServer,
            branch.set_last_revision_info, 123, 'revid')
        self.assertEqual(('UnexpectedError',), err.error_tuple)
        branch.unlock()

    def test_tip_change_rejected(self):
        """TipChangeRejected responses cause a TipChangeRejected exception to
        be raised.
        """
        transport = MemoryTransport()
        transport.mkdir('branch')
        transport = transport.clone('branch')
        client = FakeClient(transport.base)
        # get_stacked_on_url
        client.add_error_response('NotStacked')
        # lock_write
        client.add_success_response('ok', 'branch token', 'repo token')
        # set_last_revision
        client.add_error_response('TipChangeRejected', 'rejection message')
        # unlock
        client.add_success_response('ok')

        branch = self.make_remote_branch(transport, client)
        # Lock the branch, reset the record of remote calls.
        branch.lock_write()
        self.addCleanup(branch.unlock)
        client._calls = []

        # The 'TipChangeRejected' error response triggered by calling
        # set_last_revision_info causes a TipChangeRejected exception.
        err = self.assertRaises(
            errors.TipChangeRejected,
            branch.set_last_revision_info, 123, 'revid')
        self.assertEqual('rejection message', err.msg)


class TestBranchControlGetBranchConf(tests.TestCaseWithMemoryTransport):
    """Getting the branch configuration should use an abstract method not vfs.
    """

    def test_get_branch_conf(self):
        raise tests.KnownFailure('branch.conf is not retrieved by get_config_file')
        ## # We should see that branch.get_config() does a single rpc to get the
        ## # remote configuration file, abstracting away where that is stored on
        ## # the server.  However at the moment it always falls back to using the
        ## # vfs, and this would need some changes in config.py.

        ## # in an empty branch we decode the response properly
        ## client = FakeClient([(('ok', ), '# config file body')], self.get_url())
        ## # we need to make a real branch because the remote_branch.control_files
        ## # will trigger _ensure_real.
        ## branch = self.make_branch('quack')
        ## transport = branch.bzrdir.root_transport
        ## # we do not want bzrdir to make any remote calls
        ## bzrdir = RemoteBzrDir(transport, _client=False)
        ## branch = RemoteBranch(bzrdir, None, _client=client)
        ## config = branch.get_config()
        ## self.assertEqual(
        ##     [('call_expecting_body', 'Branch.get_config_file', ('quack/',))],
        ##     client._calls)


class TestBranchLockWrite(RemoteBranchTestCase):

    def test_lock_write_unlockable(self):
        transport = MemoryTransport()
        client = FakeClient(transport.base)
        client.add_expected_call(
            'Branch.get_stacked_on_url', ('quack/',),
            'error', ('NotStacked',),)
        client.add_expected_call(
            'Branch.lock_write', ('quack/', '', ''),
            'error', ('UnlockableTransport',))
        transport.mkdir('quack')
        transport = transport.clone('quack')
        branch = self.make_remote_branch(transport, client)
        self.assertRaises(errors.UnlockableTransport, branch.lock_write)
        client.finished_test()


class TestTransportIsReadonly(tests.TestCase):

    def test_true(self):
        client = FakeClient()
        client.add_success_response('yes')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(True, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)

    def test_false(self):
        client = FakeClient()
        client.add_success_response('no')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)

    def test_error_from_old_server(self):
        """bzr 0.15 and earlier servers don't recognise the is_readonly verb.
        
        Clients should treat it as a "no" response, because is_readonly is only
        advisory anyway (a transport could be read-write, but then the
        underlying filesystem could be readonly anyway).
        """
        client = FakeClient()
        client.add_unknown_method_response('Transport.is_readonly')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        self.assertEqual(False, transport.is_readonly())
        self.assertEqual(
            [('call', 'Transport.is_readonly', ())],
            client._calls)


class TestTransportMkdir(tests.TestCase):

    def test_permissiondenied(self):
        client = FakeClient()
        client.add_error_response('PermissionDenied', 'remote path', 'extra')
        transport = RemoteTransport('bzr://example.com/', medium=False,
                                    _client=client)
        exc = self.assertRaises(
            errors.PermissionDenied, transport.mkdir, 'client path')
        expected_error = errors.PermissionDenied('/client path', 'extra')
        self.assertEqual(expected_error, exc)


class TestRemoteSSHTransportAuthentication(tests.TestCaseInTempDir):

    def test_defaults_to_none(self):
        t = RemoteSSHTransport('bzr+ssh://example.com')
        self.assertIs(None, t._get_credentials()[0])

    def test_uses_authentication_config(self):
        conf = config.AuthenticationConfig()
        conf._get_config().update(
            {'bzr+sshtest': {'scheme': 'ssh', 'user': 'bar', 'host':
            'example.com'}})
        conf._save()
        t = RemoteSSHTransport('bzr+ssh://example.com')
        self.assertEqual('bar', t._get_credentials()[0])


class TestRemoteRepository(tests.TestCase):
    """Base for testing RemoteRepository protocol usage.
    
    These tests contain frozen requests and responses.  We want any changes to 
    what is sent or expected to be require a thoughtful update to these tests
    because they might break compatibility with different-versioned servers.
    """

    def setup_fake_client_and_repository(self, transport_path):
        """Create the fake client and repository for testing with.
        
        There's no real server here; we just have canned responses sent
        back one by one.
        
        :param transport_path: Path below the root of the MemoryTransport
            where the repository will be created.
        """
        transport = MemoryTransport()
        transport.mkdir(transport_path)
        client = FakeClient(transport.base)
        transport = transport.clone(transport_path)
        # we do not want bzrdir to make any remote calls
        bzrdir = RemoteBzrDir(transport, _client=False)
        repo = RemoteRepository(bzrdir, None, _client=client)
        return repo, client


class TestRepositoryGatherStats(TestRemoteRepository):

    def test_revid_none(self):
        # ('ok',), body with revisions and size
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(
            'revisions: 2\nsize: 18\n', 'ok')
        result = repo.gather_stats(None)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
             ('quack/','','no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18}, result)

    def test_revid_no_committers(self):
        # ('ok',), body without committers
        body = ('firstrev: 123456.300 3600\n'
                'latestrev: 654231.400 0\n'
                'revisions: 2\n'
                'size: 18\n')
        transport_path = 'quick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, 'ok')
        result = repo.gather_stats(revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('quick/', revid, 'no'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)

    def test_revid_with_committers(self):
        # ('ok',), body with committers
        body = ('committers: 128\n'
                'firstrev: 123456.300 3600\n'
                'latestrev: 654231.400 0\n'
                'revisions: 2\n'
                'size: 18\n')
        transport_path = 'buick'
        revid = u'\xc8'.encode('utf8')
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(body, 'ok')
        result = repo.gather_stats(revid, True)
        self.assertEqual(
            [('call_expecting_body', 'Repository.gather_stats',
              ('buick/', revid, 'yes'))],
            client._calls)
        self.assertEqual({'revisions': 2, 'size': 18,
                          'committers': 128,
                          'firstrev': (123456.300, 3600),
                          'latestrev': (654231.400, 0),},
                         result)


class TestRepositoryGetGraph(TestRemoteRepository):

    def test_get_graph(self):
        # get_graph returns a graph with a custom parents provider.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        graph = repo.get_graph()
        self.assertNotEqual(graph._parents_provider, repo)


class TestRepositoryGetParentMap(TestRemoteRepository):

    def test_get_parent_map_caching(self):
        # get_parent_map returns from cache until unlock()
        # setup a reponse with two revisions
        r1 = u'\u0e33'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r1]), r1]
        encoded_body = bz2.compress('\n'.join(lines))

        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        client.add_success_response_with_body(encoded_body, 'ok')
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r2])
        self.assertEqual({r2: (r1,)}, parents)
        # locking and unlocking deeper should not reset
        repo.lock_read()
        repo.unlock()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r2), '\n\n0')],
            client._calls)
        repo.unlock()
        # now we call again, and it should use the second response.
        repo.lock_read()
        graph = repo.get_graph()
        parents = graph.get_parent_map([r1])
        self.assertEqual({r1: (NULL_REVISION,)}, parents)
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r2), '\n\n0'),
             ('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', r1), '\n\n0'),
            ],
            client._calls)
        repo.unlock()

    def test_get_parent_map_reconnects_if_unknown_method(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_unknown_method_response('Repository,get_parent_map')
        client.add_success_response_with_body('', 'ok')
        self.assertFalse(client._medium._is_remote_before((1, 2)))
        rev_id = 'revision-id'
        expected_deprecations = [
            'bzrlib.remote.RemoteRepository.get_revision_graph was deprecated '
            'in version 1.4.']
        parents = self.callDeprecated(
            expected_deprecations, repo.get_parent_map, [rev_id])
        self.assertEqual(
            [('call_with_body_bytes_expecting_body',
              'Repository.get_parent_map', ('quack/', rev_id), '\n\n0'),
             ('disconnect medium',),
             ('call_expecting_body', 'Repository.get_revision_graph',
              ('quack/', ''))],
            client._calls)
        # The medium is now marked as being connected to an older server
        self.assertTrue(client._medium._is_remote_before((1, 2)))

    def test_get_parent_map_fallback_parentless_node(self):
        """get_parent_map falls back to get_revision_graph on old servers.  The
        results from get_revision_graph are tweaked to match the get_parent_map
        API.

        Specifically, a {key: ()} result from get_revision_graph means "no
        parents" for that key, which in get_parent_map results should be
        represented as {key: ('null:',)}.

        This is the test for https://bugs.launchpad.net/bzr/+bug/214894
        """
        rev_id = 'revision-id'
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(rev_id, 'ok')
        client._medium._remember_remote_is_before((1, 2))
        expected_deprecations = [
            'bzrlib.remote.RemoteRepository.get_revision_graph was deprecated '
            'in version 1.4.']
        parents = self.callDeprecated(
            expected_deprecations, repo.get_parent_map, [rev_id])
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('quack/', ''))],
            client._calls)
        self.assertEqual({rev_id: ('null:',)}, parents)

    def test_get_parent_map_unexpected_response(self):
        repo, client = self.setup_fake_client_and_repository('path')
        client.add_success_response('something unexpected!')
        self.assertRaises(
            errors.UnexpectedSmartServerResponse,
            repo.get_parent_map, ['a-revision-id'])


class TestRepositoryGetRevisionGraph(TestRemoteRepository):
    
    def test_null_revision(self):
        # a null revision has the predictable result {}, we should have no wire
        # traffic when calling it with this argument
        transport_path = 'empty'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('notused')
        result = self.applyDeprecated(one_four, repo.get_revision_graph,
            NULL_REVISION)
        self.assertEqual([], client._calls)
        self.assertEqual({}, result)

    def test_none_revision(self):
        # with none we want the entire graph
        r1 = u'\u0e33'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r1]), r1]
        encoded_body = '\n'.join(lines)

        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        result = self.applyDeprecated(one_four, repo.get_revision_graph)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', ''))],
            client._calls)
        self.assertEqual({r1: (), r2: (r1, )}, result)

    def test_specific_revision(self):
        # with a specific revision we want the graph for that
        # with none we want the entire graph
        r11 = u'\u0e33'.encode('utf8')
        r12 = u'\xc9'.encode('utf8')
        r2 = u'\u0dab'.encode('utf8')
        lines = [' '.join([r2, r11, r12]), r11, r12]
        encoded_body = '\n'.join(lines)

        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(encoded_body, 'ok')
        result = self.applyDeprecated(one_four, repo.get_revision_graph, r2)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', r2))],
            client._calls)
        self.assertEqual({r11: (), r12: (), r2: (r11, r12), }, result)

    def test_no_such_revision(self):
        revid = '123'
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('nosuchrevision', revid)
        # also check that the right revision is reported in the error
        self.assertRaises(errors.NoSuchRevision,
            self.applyDeprecated, one_four, repo.get_revision_graph, revid)
        self.assertEqual(
            [('call_expecting_body', 'Repository.get_revision_graph',
             ('sinhala/', revid))],
            client._calls)

    def test_unexpected_error(self):
        revid = '123'
        transport_path = 'sinhala'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('AnUnexpectedError')
        e = self.assertRaises(errors.UnknownErrorFromSmartServer,
            self.applyDeprecated, one_four, repo.get_revision_graph, revid)
        self.assertEqual(('AnUnexpectedError',), e.error_tuple)

        
class TestRepositoryIsShared(TestRemoteRepository):

    def test_is_shared(self):
        # ('yes', ) for Repository.is_shared -> 'True'.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('yes')
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('quack/',))],
            client._calls)
        self.assertEqual(True, result)

    def test_is_not_shared(self):
        # ('no', ) for Repository.is_shared -> 'False'.
        transport_path = 'qwack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('no')
        result = repo.is_shared()
        self.assertEqual(
            [('call', 'Repository.is_shared', ('qwack/',))],
            client._calls)
        self.assertEqual(False, result)


class TestRepositoryLockWrite(TestRemoteRepository):

    def test_lock_write(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        result = repo.lock_write()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)
        self.assertEqual('a token', result)

    def test_lock_write_already_locked(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('LockContention')
        self.assertRaises(errors.LockContention, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)

    def test_lock_write_unlockable(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_error_response('UnlockableTransport')
        self.assertRaises(errors.UnlockableTransport, repo.lock_write)
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', ''))],
            client._calls)


class TestRepositoryUnlock(TestRemoteRepository):

    def test_unlock(self):
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        client.add_success_response('ok')
        repo.lock_write()
        repo.unlock()
        self.assertEqual(
            [('call', 'Repository.lock_write', ('quack/', '')),
             ('call', 'Repository.unlock', ('quack/', 'a token'))],
            client._calls)

    def test_unlock_wrong_token(self):
        # If somehow the token is wrong, unlock will raise TokenMismatch.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response('ok', 'a token')
        client.add_error_response('TokenMismatch')
        repo.lock_write()
        self.assertRaises(errors.TokenMismatch, repo.unlock)


class TestRepositoryHasRevision(TestRemoteRepository):

    def test_none(self):
        # repo.has_revision(None) should not cause any traffic.
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)

        # The null revision is always there, so has_revision(None) == True.
        self.assertEqual(True, repo.has_revision(NULL_REVISION))

        # The remote repo shouldn't be accessed.
        self.assertEqual([], client._calls)


class TestRepositoryTarball(TestRemoteRepository):

    # This is a canned tarball reponse we can validate against
    tarball_content = (
        'QlpoOTFBWSZTWdGkj3wAAWF/k8aQACBIB//A9+8cIX/v33AACEAYABAECEACNz'
        'JqsgJJFPTSnk1A3qh6mTQAAAANPUHkagkSTEkaA09QaNAAAGgAAAcwCYCZGAEY'
        'mJhMJghpiaYBUkKammSHqNMZQ0NABkNAeo0AGneAevnlwQoGzEzNVzaYxp/1Uk'
        'xXzA1CQX0BJMZZLcPBrluJir5SQyijWHYZ6ZUtVqqlYDdB2QoCwa9GyWwGYDMA'
        'OQYhkpLt/OKFnnlT8E0PmO8+ZNSo2WWqeCzGB5fBXZ3IvV7uNJVE7DYnWj6qwB'
        'k5DJDIrQ5OQHHIjkS9KqwG3mc3t+F1+iujb89ufyBNIKCgeZBWrl5cXxbMGoMs'
        'c9JuUkg5YsiVcaZJurc6KLi6yKOkgCUOlIlOpOoXyrTJjK8ZgbklReDdwGmFgt'
        'dkVsAIslSVCd4AtACSLbyhLHryfb14PKegrVDba+U8OL6KQtzdM5HLjAc8/p6n'
        '0lgaWU8skgO7xupPTkyuwheSckejFLK5T4ZOo0Gda9viaIhpD1Qn7JqqlKAJqC'
        'QplPKp2nqBWAfwBGaOwVrz3y1T+UZZNismXHsb2Jq18T+VaD9k4P8DqE3g70qV'
        'JLurpnDI6VS5oqDDPVbtVjMxMxMg4rzQVipn2Bv1fVNK0iq3Gl0hhnnHKm/egy'
        'nWQ7QH/F3JFOFCQ0aSPfA='
        ).decode('base64')

    def test_repository_tarball(self):
        # Test that Repository.tarball generates the right operations
        transport_path = 'repo'
        expected_calls = [('call_expecting_body', 'Repository.tarball',
                           ('repo/', 'bz2',),),
            ]
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_success_response_with_body(self.tarball_content, 'ok')
        # Now actually ask for the tarball
        tarball_file = repo._get_tarball('bz2')
        try:
            self.assertEqual(expected_calls, client._calls)
            self.assertEqual(self.tarball_content, tarball_file.read())
        finally:
            tarball_file.close()


class TestRemoteRepositoryCopyContent(tests.TestCaseWithTransport):
    """RemoteRepository.copy_content_into optimizations"""

    def test_copy_content_remote_to_local(self):
        self.transport_server = server.SmartTCPServer_for_testing
        src_repo = self.make_repository('repo1')
        src_repo = repository.Repository.open(self.get_url('repo1'))
        # At the moment the tarball-based copy_content_into can't write back
        # into a smart server.  It would be good if it could upload the
        # tarball; once that works we'd have to create repositories of
        # different formats. -- mbp 20070410
        dest_url = self.get_vfs_only_url('repo2')
        dest_bzrdir = BzrDir.create(dest_url)
        dest_repo = dest_bzrdir.create_repository()
        self.assertFalse(isinstance(dest_repo, RemoteRepository))
        self.assertTrue(isinstance(src_repo, RemoteRepository))
        src_repo.copy_content_into(dest_repo)


class _StubRealPackRepository(object):

    def __init__(self, calls):
        self._pack_collection = _StubPackCollection(calls)


class _StubPackCollection(object):

    def __init__(self, calls):
        self.calls = calls

    def autopack(self):
        self.calls.append(('pack collection autopack',))

    def reload_pack_names(self):
        self.calls.append(('pack collection reload_pack_names',))

    
class TestRemotePackRepositoryAutoPack(TestRemoteRepository):
    """Tests for RemoteRepository.autopack implementation."""

    def test_ok(self):
        """When the server returns 'ok' and there's no _real_repository, then
        nothing else happens: the autopack method is done.
        """
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            'PackRepository.autopack', ('quack/',), 'success', ('ok',))
        repo.autopack()
        client.finished_test()

    def test_ok_with_real_repo(self):
        """When the server returns 'ok' and there is a _real_repository, then
        the _real_repository's reload_pack_name's method will be called.
        """
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_expected_call(
            'PackRepository.autopack', ('quack/',),
            'success', ('ok',))
        repo._real_repository = _StubRealPackRepository(client._calls)
        repo.autopack()
        self.assertEqual(
            [('call', 'PackRepository.autopack', ('quack/',)),
             ('pack collection reload_pack_names',)],
            client._calls)
        
    def test_backwards_compatibility(self):
        """If the server does not recognise the PackRepository.autopack verb,
        fallback to the real_repository's implementation.
        """
        transport_path = 'quack'
        repo, client = self.setup_fake_client_and_repository(transport_path)
        client.add_unknown_method_response('PackRepository.autopack')
        def stub_ensure_real():
            client._calls.append(('_ensure_real',))
            repo._real_repository = _StubRealPackRepository(client._calls)
        repo._ensure_real = stub_ensure_real
        repo.autopack()
        self.assertEqual(
            [('call', 'PackRepository.autopack', ('quack/',)),
             ('_ensure_real',),
             ('pack collection autopack',)],
            client._calls)


class TestErrorTranslationBase(tests.TestCaseWithMemoryTransport):
    """Base class for unit tests for bzrlib.remote._translate_error."""

    def translateTuple(self, error_tuple, **context):
        """Call _translate_error with an ErrorFromSmartServer built from the
        given error_tuple.

        :param error_tuple: A tuple of a smart server response, as would be
            passed to an ErrorFromSmartServer.
        :kwargs context: context items to call _translate_error with.

        :returns: The error raised by _translate_error.
        """
        # Raise the ErrorFromSmartServer before passing it as an argument,
        # because _translate_error may need to re-raise it with a bare 'raise'
        # statement.
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(
            server_error, **context)
        return translated_error

    def translateErrorFromSmartServer(self, error_object, **context):
        """Like translateTuple, but takes an already constructed
        ErrorFromSmartServer rather than a tuple.
        """
        try:
            raise error_object
        except errors.ErrorFromSmartServer, server_error:
            translated_error = self.assertRaises(
                errors.BzrError, remote._translate_error, server_error,
                **context)
        return translated_error


class TestErrorTranslationSuccess(TestErrorTranslationBase):
    """Unit tests for bzrlib.remote._translate_error.
    
    Given an ErrorFromSmartServer (which has an error tuple from a smart
    server) and some context, _translate_error raises more specific errors from
    bzrlib.errors.

    This test case covers the cases where _translate_error succeeds in
    translating an ErrorFromSmartServer to something better.  See
    TestErrorTranslationRobustness for other cases.
    """

    def test_NoSuchRevision(self):
        branch = self.make_branch('')
        revid = 'revid'
        translated_error = self.translateTuple(
            ('NoSuchRevision', revid), branch=branch)
        expected_error = errors.NoSuchRevision(branch, revid)
        self.assertEqual(expected_error, translated_error)

    def test_nosuchrevision(self):
        repository = self.make_repository('')
        revid = 'revid'
        translated_error = self.translateTuple(
            ('nosuchrevision', revid), repository=repository)
        expected_error = errors.NoSuchRevision(repository, revid)
        self.assertEqual(expected_error, translated_error)

    def test_nobranch(self):
        bzrdir = self.make_bzrdir('')
        translated_error = self.translateTuple(('nobranch',), bzrdir=bzrdir)
        expected_error = errors.NotBranchError(path=bzrdir.root_transport.base)
        self.assertEqual(expected_error, translated_error)

    def test_LockContention(self):
        translated_error = self.translateTuple(('LockContention',))
        expected_error = errors.LockContention('(remote lock)')
        self.assertEqual(expected_error, translated_error)

    def test_UnlockableTransport(self):
        bzrdir = self.make_bzrdir('')
        translated_error = self.translateTuple(
            ('UnlockableTransport',), bzrdir=bzrdir)
        expected_error = errors.UnlockableTransport(bzrdir.root_transport)
        self.assertEqual(expected_error, translated_error)

    def test_LockFailed(self):
        lock = 'str() of a server lock'
        why = 'str() of why'
        translated_error = self.translateTuple(('LockFailed', lock, why))
        expected_error = errors.LockFailed(lock, why)
        self.assertEqual(expected_error, translated_error)

    def test_TokenMismatch(self):
        token = 'a lock token'
        translated_error = self.translateTuple(('TokenMismatch',), token=token)
        expected_error = errors.TokenMismatch(token, '(remote token)')
        self.assertEqual(expected_error, translated_error)

    def test_Diverged(self):
        branch = self.make_branch('a')
        other_branch = self.make_branch('b')
        translated_error = self.translateTuple(
            ('Diverged',), branch=branch, other_branch=other_branch)
        expected_error = errors.DivergedBranches(branch, other_branch)
        self.assertEqual(expected_error, translated_error)

    def test_ReadError_no_args(self):
        path = 'a path'
        translated_error = self.translateTuple(('ReadError',), path=path)
        expected_error = errors.ReadError(path)
        self.assertEqual(expected_error, translated_error)

    def test_ReadError(self):
        path = 'a path'
        translated_error = self.translateTuple(('ReadError', path))
        expected_error = errors.ReadError(path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_no_args(self):
        path = 'a path'
        translated_error = self.translateTuple(('PermissionDenied',), path=path)
        expected_error = errors.PermissionDenied(path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_one_arg(self):
        path = 'a path'
        translated_error = self.translateTuple(('PermissionDenied', path))
        expected_error = errors.PermissionDenied(path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_one_arg_and_context(self):
        """Given a choice between a path from the local context and a path on
        the wire, _translate_error prefers the path from the local context.
        """
        local_path = 'local path'
        remote_path = 'remote path'
        translated_error = self.translateTuple(
            ('PermissionDenied', remote_path), path=local_path)
        expected_error = errors.PermissionDenied(local_path)
        self.assertEqual(expected_error, translated_error)

    def test_PermissionDenied_two_args(self):
        path = 'a path'
        extra = 'a string with extra info'
        translated_error = self.translateTuple(
            ('PermissionDenied', path, extra))
        expected_error = errors.PermissionDenied(path, extra)
        self.assertEqual(expected_error, translated_error)


class TestErrorTranslationRobustness(TestErrorTranslationBase):
    """Unit tests for bzrlib.remote._translate_error's robustness.
    
    TestErrorTranslationSuccess is for cases where _translate_error can
    translate successfully.  This class about how _translate_err behaves when
    it fails to translate: it re-raises the original error.
    """

    def test_unrecognised_server_error(self):
        """If the error code from the server is not recognised, the original
        ErrorFromSmartServer is propagated unmodified.
        """
        error_tuple = ('An unknown error tuple',)
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        expected_error = errors.UnknownErrorFromSmartServer(server_error)
        self.assertEqual(expected_error, translated_error)

    def test_context_missing_a_key(self):
        """In case of a bug in the client, or perhaps an unexpected response
        from a server, _translate_error returns the original error tuple from
        the server and mutters a warning.
        """
        # To translate a NoSuchRevision error _translate_error needs a 'branch'
        # in the context dict.  So let's give it an empty context dict instead
        # to exercise its error recovery.
        empty_context = {}
        error_tuple = ('NoSuchRevision', 'revid')
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        self.assertEqual(server_error, translated_error)
        # In addition to re-raising ErrorFromSmartServer, some debug info has
        # been muttered to the log file for developer to look at.
        self.assertContainsRe(
            self._get_log(keep_log_file=True),
            "Missing key 'branch' in context")
        
    def test_path_missing(self):
        """Some translations (PermissionDenied, ReadError) can determine the
        'path' variable from either the wire or the local context.  If neither
        has it, then an error is raised.
        """
        error_tuple = ('ReadError',)
        server_error = errors.ErrorFromSmartServer(error_tuple)
        translated_error = self.translateErrorFromSmartServer(server_error)
        self.assertEqual(server_error, translated_error)
        # In addition to re-raising ErrorFromSmartServer, some debug info has
        # been muttered to the log file for developer to look at.
        self.assertContainsRe(
            self._get_log(keep_log_file=True), "Missing key 'path' in context")


class TestStacking(tests.TestCaseWithTransport):
    """Tests for operations on stacked remote repositories.
    
    The underlying format type must support stacking.
    """

    def test_access_stacked_remote(self):
        # based on <http://launchpad.net/bugs/261315>
        # make a branch stacked on another repository containing an empty
        # revision, then open it over hpss - we should be able to see that
        # revision.
        base_transport = self.get_transport()
        base_builder = self.make_branch_builder('base', format='1.6')
        base_builder.start_series()
        base_revid = base_builder.build_snapshot('rev-id', None,
            [('add', ('', None, 'directory', None))],
            'message')
        base_builder.finish_series()
        stacked_branch = self.make_branch('stacked', format='1.6')
        stacked_branch.set_stacked_on_url('../base')
        # start a server looking at this
        smart_server = server.SmartTCPServer_for_testing()
        smart_server.setUp()
        self.addCleanup(smart_server.tearDown)
        remote_bzrdir = BzrDir.open(smart_server.get_url() + '/stacked')
        # can get its branch and repository
        remote_branch = remote_bzrdir.open_branch()
        remote_repo = remote_branch.repository
        remote_repo.lock_read()
        try:
            # it should have an appropriate fallback repository, which should also
            # be a RemoteRepository
            self.assertEquals(len(remote_repo._fallback_repositories), 1)
            self.assertIsInstance(remote_repo._fallback_repositories[0],
                RemoteRepository)
            # and it has the revision committed to the underlying repository;
            # these have varying implementations so we try several of them
            self.assertTrue(remote_repo.has_revisions([base_revid]))
            self.assertTrue(remote_repo.has_revision(base_revid))
            self.assertEqual(remote_repo.get_revision(base_revid).message,
                'message')
        finally:
            remote_repo.unlock()

    def prepare_stacked_remote_branch(self):
        smart_server = server.SmartTCPServer_for_testing()
        smart_server.setUp()
        self.addCleanup(smart_server.tearDown)
        tree1 = self.make_branch_and_tree('tree1')
        tree1.commit('rev1', rev_id='rev1')
        tree2 = self.make_branch_and_tree('tree2', format='1.6')
        tree2.branch.set_stacked_on_url(tree1.branch.base)
        branch2 = Branch.open(smart_server.get_url() + '/tree2')
        branch2.lock_read()
        self.addCleanup(branch2.unlock)
        return branch2

    def test_stacked_get_parent_map(self):
        # the public implementation of get_parent_map obeys stacking
        branch = self.prepare_stacked_remote_branch()
        repo = branch.repository
        self.assertEqual(['rev1'], repo.get_parent_map(['rev1']).keys())

    def test_stacked__get_parent_map(self):
        # the private variant of _get_parent_map ignores stacking
        branch = self.prepare_stacked_remote_branch()
        repo = branch.repository
        self.assertEqual([], repo._get_parent_map(['rev1']).keys())


class TestRemoteBranchEffort(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestRemoteBranchEffort, self).setUp()
        # Create a smart server that publishes whatever the backing VFS server
        # does.
        self.smart_server = server.SmartTCPServer_for_testing()
        self.smart_server.setUp(self.get_server())
        self.addCleanup(self.smart_server.tearDown)
        # Log all HPSS calls into self.hpss_calls.
        _SmartClient.hooks.install_named_hook(
            'call', self.capture_hpss_call, None)
        self.hpss_calls = []

    def capture_hpss_call(self, params):
        self.hpss_calls.append(params.method)

    def test_copy_content_into_avoids_revision_history(self):
        local = self.make_branch('local')
        remote_backing_tree = self.make_branch_and_tree('remote')
        remote_backing_tree.commit("Commit.")
        remote_branch_url = self.smart_server.get_url() + 'remote'
        remote_branch = bzrdir.BzrDir.open(remote_branch_url).open_branch()
        local.repository.fetch(remote_branch.repository)
        self.hpss_calls = []
        remote_branch.copy_content_into(local)
        self.assertFalse('Branch.revision_history' in self.hpss_calls)
