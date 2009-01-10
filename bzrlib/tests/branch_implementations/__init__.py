# Copyright (C) 2006, 2007 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
#          and others
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


"""Branch implementation tests for bzr.

These test the conformance of all the branch variations to the expected API.
Specific tests for individual formats are in the tests/test_branch file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.branch import (BranchFormat,
                           _legacy_formats,
                           )
from bzrlib.remote import RemoteBranchFormat, RemoteBzrDirFormat
from bzrlib.smart.server import (
    ReadonlySmartTCPServer_for_testing,
    ReadonlySmartTCPServer_for_testing_v2_only,
    SmartTCPServer_for_testing,
    SmartTCPServer_for_testing_v2_only,
    )
from bzrlib.tests.bzrdir_implementations.test_bzrdir import TestCaseWithBzrDir
from bzrlib.transport.memory import MemoryServer


class BranchTestProviderAdapter(tests.TestScenarioApplier):
    """A tool to generate a suite testing multiple branch formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and branch_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats,
        vfs_transport_factory=None, name_suffix=''):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._name_suffix = name_suffix
        self.scenarios = self.formats_to_scenarios(formats)
    
    def formats_to_scenarios(self, formats):
        """Transform the input formats to a list of scenarios.

        :param formats: A list of (branch_format, bzrdir_format).
        """
        result = []
        for branch_format, bzrdir_format in formats:
            # some branches don't have separate format objects.
            # so we have a conditional here to handle them.
            scenario_name = getattr(branch_format, '__name__',
                branch_format.__class__.__name__)
            scenario_name += self._name_suffix
            scenario = (scenario_name, {
                "transport_server":self._transport_server,
                "transport_readonly_server":self._transport_readonly_server,
                "bzrdir_format":bzrdir_format,
                "branch_format":branch_format,
                    })
            result.append(scenario)
        return result


class TestCaseWithBranch(TestCaseWithBzrDir):
    """This helper will be adapted for each branch_implementation test."""

    def setUp(self):
        super(TestCaseWithBranch, self).setUp()
        self.branch = None

    def get_branch(self):
        if self.branch is None:
            self.branch = self.make_branch('')
        return self.branch

    def make_branch(self, relpath, format=None):
        repo = self.make_repository(relpath, format=format)
        # fixme RBC 20060210 this isnt necessarily a fixable thing,
        # Skipped is the wrong exception to raise.
        try:
            return self.branch_format.initialize(repo.bzrdir)
        except errors.UninitializableFormat:
            raise tests.TestSkipped('Uninitializable branch format')

    def make_repository(self, relpath, shared=False, format=None):
        made_control = self.make_bzrdir(relpath, format=format)
        return made_control.create_repository(shared=shared)

    def create_tree_with_merge(self):
        """Create a branch with a simple ancestry.

        The graph should look like:
            digraph H {
                "rev-1" -> "rev-2" -> "rev-3";
                "rev-1" -> "rev-1.1.1" -> "rev-3";
            }

        Or in ASCII:
            1
            |\
            2 1.1.1
            |/
            3
        """
        tree = self.make_branch_and_memory_tree('tree')
        tree.lock_write()
        try:
            tree.add('')
            tree.commit('first', rev_id='rev-1')
            tree.commit('second', rev_id='rev-1.1.1')
            # Uncommit that last commit and switch to the other line
            tree.branch.set_last_revision_info(1, 'rev-1')
            tree.set_parent_ids(['rev-1'])
            tree.commit('alt-second', rev_id='rev-2')
            tree.set_parent_ids(['rev-2', 'rev-1.1.1'])
            tree.commit('third', rev_id='rev-3')
        finally:
            tree.unlock()

        return tree


def load_tests(basic_tests, module, loader):
    result = loader.suiteClass()
    # add the tests for this module
    result.addTests(basic_tests)

    test_branch_implementations = [
        'bzrlib.tests.branch_implementations.test_bound_sftp',
        'bzrlib.tests.branch_implementations.test_branch',
        'bzrlib.tests.branch_implementations.test_break_lock',
        'bzrlib.tests.branch_implementations.test_check',
        'bzrlib.tests.branch_implementations.test_create_checkout',
        'bzrlib.tests.branch_implementations.test_commit',
        'bzrlib.tests.branch_implementations.test_get_revision_id_to_revno_map',
        'bzrlib.tests.branch_implementations.test_hooks',
        'bzrlib.tests.branch_implementations.test_http',
        'bzrlib.tests.branch_implementations.test_last_revision_info',
        'bzrlib.tests.branch_implementations.test_locking',
        'bzrlib.tests.branch_implementations.test_parent',
        'bzrlib.tests.branch_implementations.test_permissions',
        'bzrlib.tests.branch_implementations.test_pull',
        'bzrlib.tests.branch_implementations.test_push',
        'bzrlib.tests.branch_implementations.test_reconcile',
        'bzrlib.tests.branch_implementations.test_revision_history',
        'bzrlib.tests.branch_implementations.test_revision_id_to_revno',
        'bzrlib.tests.branch_implementations.test_sprout',
        'bzrlib.tests.branch_implementations.test_stacking',
        'bzrlib.tests.branch_implementations.test_tags',
        'bzrlib.tests.branch_implementations.test_uncommit',
        'bzrlib.tests.branch_implementations.test_update',
        ]
    # Generate a list of branch formats and their associated bzrdir formats to
    # use.
    combinations = [(format, format._matchingbzrdir) for format in 
         BranchFormat._formats.values() + _legacy_formats]
    adapter = BranchTestProviderAdapter(
        # None here will cause the default vfs transport server to be used.
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        combinations)
    # add the tests for the sub modules
    tests.adapt_modules(test_branch_implementations, adapter, loader, result)

    # Add RemoteBranch tests, which need a special server.
    adapt_to_smart_server = BranchTestProviderAdapter(
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBranchFormat(), RemoteBzrDirFormat())],
        MemoryServer,
        name_suffix='-default')
    tests.adapt_modules(test_branch_implementations,
                        adapt_to_smart_server,
                        loader,
                        result)

    # Also add tests for RemoteBranch with HPSS protocol v2 (i.e. bzr <1.6)
    # server.
    adapt_to_smart_server = BranchTestProviderAdapter(
        SmartTCPServer_for_testing_v2_only,
        ReadonlySmartTCPServer_for_testing_v2_only,
        [(RemoteBranchFormat(), RemoteBzrDirFormat())],
        MemoryServer,
        name_suffix='-v2')
    tests.adapt_modules(test_branch_implementations,
                        adapt_to_smart_server,
                        loader,
                        result)

    return result
