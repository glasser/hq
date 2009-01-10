# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

"""Tests for the BzrDir facility and any format specific tests.

For interface contract tests, see tests/bzr_dir_implementations.
"""

import os
import os.path
from StringIO import StringIO
import subprocess
import sys

from bzrlib import (
    bzrdir,
    errors,
    help_topics,
    repository,
    osutils,
    symbol_versioning,
    urlutils,
    win32utils,
    workingtree,
    )
import bzrlib.branch
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnsupportedFormatError,
                           )
from bzrlib.tests import (
    TestCase,
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    TestSkipped,
    test_sftp_transport
    )
from bzrlib.tests.http_server import HttpServer
from bzrlib.tests.http_utils import (
    TestCaseWithTwoWebservers,
    HTTPServerRedirecting,
    )
from bzrlib.tests.test_http import TestWithTransport_pycurl
from bzrlib.transport import get_transport
from bzrlib.transport.http._urllib import HttpTransport_urllib
from bzrlib.transport.memory import MemoryServer
from bzrlib.repofmt import knitrepo, weaverepo


class TestDefaultFormat(TestCase):

    def test_get_set_default_format(self):
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # default is BzrDirFormat6
        self.failUnless(isinstance(old_format, bzrdir.BzrDirMetaFormat1))
        bzrdir.BzrDirFormat._set_default_format(SampleBzrDirFormat())
        # creating a bzr dir should now create an instrumented dir.
        try:
            result = bzrdir.BzrDir.create('memory:///')
            self.failUnless(isinstance(result, SampleBzrDir))
        finally:
            bzrdir.BzrDirFormat._set_default_format(old_format)
        self.assertEqual(old_format, bzrdir.BzrDirFormat.get_default_format())


class TestFormatRegistry(TestCase):

    def make_format_registry(self):
        my_format_registry = bzrdir.BzrDirFormatRegistry()
        my_format_registry.register('weave', bzrdir.BzrDirFormat6,
            'Pre-0.8 format.  Slower and does not support checkouts or shared'
            ' repositories', deprecated=True)
        my_format_registry.register_lazy('lazy', 'bzrlib.bzrdir', 
            'BzrDirFormat6', 'Format registered lazily', deprecated=True)
        my_format_registry.register_metadir('knit',
            'bzrlib.repofmt.knitrepo.RepositoryFormatKnit1',
            'Format using knits',
            )
        my_format_registry.set_default('knit')
        my_format_registry.register_metadir(
            'branch6',
            'bzrlib.repofmt.knitrepo.RepositoryFormatKnit3',
            'Experimental successor to knit.  Use at your own risk.',
            branch_format='bzrlib.branch.BzrBranchFormat6',
            experimental=True)
        my_format_registry.register_metadir(
            'hidden format',
            'bzrlib.repofmt.knitrepo.RepositoryFormatKnit3',
            'Experimental successor to knit.  Use at your own risk.',
            branch_format='bzrlib.branch.BzrBranchFormat6', hidden=True)
        my_format_registry.register('hiddenweave', bzrdir.BzrDirFormat6,
            'Pre-0.8 format.  Slower and does not support checkouts or shared'
            ' repositories', hidden=True)
        my_format_registry.register_lazy('hiddenlazy', 'bzrlib.bzrdir',
            'BzrDirFormat6', 'Format registered lazily', deprecated=True,
            hidden=True)
        return my_format_registry

    def test_format_registry(self):
        my_format_registry = self.make_format_registry()
        my_bzrdir = my_format_registry.make_bzrdir('lazy')
        self.assertIsInstance(my_bzrdir, bzrdir.BzrDirFormat6)
        my_bzrdir = my_format_registry.make_bzrdir('weave')
        self.assertIsInstance(my_bzrdir, bzrdir.BzrDirFormat6)
        my_bzrdir = my_format_registry.make_bzrdir('default')
        self.assertIsInstance(my_bzrdir.repository_format, 
            knitrepo.RepositoryFormatKnit1)
        my_bzrdir = my_format_registry.make_bzrdir('knit')
        self.assertIsInstance(my_bzrdir.repository_format, 
            knitrepo.RepositoryFormatKnit1)
        my_bzrdir = my_format_registry.make_bzrdir('branch6')
        self.assertIsInstance(my_bzrdir.get_branch_format(),
                              bzrlib.branch.BzrBranchFormat6)

    def test_get_help(self):
        my_format_registry = self.make_format_registry()
        self.assertEqual('Format registered lazily',
                         my_format_registry.get_help('lazy'))
        self.assertEqual('Format using knits', 
                         my_format_registry.get_help('knit'))
        self.assertEqual('Format using knits', 
                         my_format_registry.get_help('default'))
        self.assertEqual('Pre-0.8 format.  Slower and does not support'
                         ' checkouts or shared repositories', 
                         my_format_registry.get_help('weave'))
        
    def test_help_topic(self):
        topics = help_topics.HelpTopicRegistry()
        topics.register('formats', self.make_format_registry().help_topic, 
                        'Directory formats')
        topic = topics.get_detail('formats')
        new, rest = topic.split('Experimental formats')
        experimental, deprecated = rest.split('Deprecated formats')
        self.assertContainsRe(new, 'These formats can be used')
        self.assertContainsRe(new, 
                ':knit:\n    \(native\) \(default\) Format using knits\n')
        self.assertContainsRe(experimental, 
                ':branch6:\n    \(native\) Experimental successor to knit')
        self.assertContainsRe(deprecated, 
                ':lazy:\n    \(native\) Format registered lazily\n')
        self.assertNotContainsRe(new, 'hidden')

    def test_set_default_repository(self):
        default_factory = bzrdir.format_registry.get('default')
        old_default = [k for k, v in bzrdir.format_registry.iteritems()
                       if v == default_factory and k != 'default'][0]
        bzrdir.format_registry.set_default_repository('dirstate-with-subtree')
        try:
            self.assertIs(bzrdir.format_registry.get('dirstate-with-subtree'),
                          bzrdir.format_registry.get('default'))
            self.assertIs(
                repository.RepositoryFormat.get_default_format().__class__,
                knitrepo.RepositoryFormatKnit3)
        finally:
            bzrdir.format_registry.set_default_repository(old_default)

    def test_aliases(self):
        a_registry = bzrdir.BzrDirFormatRegistry()
        a_registry.register('weave', bzrdir.BzrDirFormat6,
            'Pre-0.8 format.  Slower and does not support checkouts or shared'
            ' repositories', deprecated=True)
        a_registry.register('weavealias', bzrdir.BzrDirFormat6,
            'Pre-0.8 format.  Slower and does not support checkouts or shared'
            ' repositories', deprecated=True, alias=True)
        self.assertEqual(frozenset(['weavealias']), a_registry.aliases())
    

class SampleBranch(bzrlib.branch.Branch):
    """A dummy branch for guess what, dummy use."""

    def __init__(self, dir):
        self.bzrdir = dir


class SampleBzrDir(bzrdir.BzrDir):
    """A sample BzrDir implementation to allow testing static methods."""

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return "A repository"

    def open_repository(self):
        """See BzrDir.open_repository."""
        return "A repository"

    def create_branch(self):
        """See BzrDir.create_branch."""
        return SampleBranch(self)

    def create_workingtree(self):
        """See BzrDir.create_workingtree."""
        return "A tree"


class SampleBzrDirFormat(bzrdir.BzrDirFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Sample .bzr dir format."

    def initialize_on_transport(self, t):
        """Create a bzr dir."""
        t.mkdir('.bzr')
        t.put_bytes('.bzr/branch-format', self.get_format_string())
        return SampleBzrDir(t, self)

    def is_supported(self):
        return False

    def open(self, transport, _found=None):
        return "opened branch."


class TestBzrDirFormat(TestCaseWithTransport):
    """Tests for the BzrDirFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        t = get_transport(self.get_url())
        self.build_tree(["foo/", "bar/"], transport=t)
        def check_format(format, url):
            format.initialize(url)
            t = get_transport(url)
            found_format = bzrdir.BzrDirFormat.find_format(t)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(bzrdir.BzrDirFormat5(), "foo")
        check_format(bzrdir.BzrDirFormat6(), "bar")
        
    def test_find_format_nothing_there(self):
        self.assertRaises(NotBranchError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_find_format_unknown_format(self):
        t = get_transport(self.get_url())
        t.mkdir('.bzr')
        t.put_bytes('.bzr/branch-format', '')
        self.assertRaises(UnknownFormatError,
                          bzrdir.BzrDirFormat.find_format,
                          get_transport('.'))

    def test_register_unregister_format(self):
        format = SampleBzrDirFormat()
        url = self.get_url()
        # make a bzrdir
        format.initialize(url)
        # register a format for it.
        bzrdir.BzrDirFormat.register_format(format)
        # which bzrdir.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open, url)
        # which bzrdir.open_containing will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, bzrdir.BzrDir.open_containing, url)
        # but open_downlevel will work
        t = get_transport(url)
        self.assertEqual(format.open(t), bzrdir.BzrDir.open_unsupported(url))
        # unregister the format
        bzrdir.BzrDirFormat.unregister_format(format)
        # now open_downlevel should fail too.
        self.assertRaises(UnknownFormatError, bzrdir.BzrDir.open_unsupported, url)

    def test_create_branch_and_repo_uses_default(self):
        format = SampleBzrDirFormat()
        branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url(),
                                                      format=format)
        self.assertTrue(isinstance(branch, SampleBranch))

    def test_create_branch_and_repo_under_shared(self):
        # creating a branch and repo in a shared repo uses the
        # shared repository
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_and_repo(
            self.get_url('child'), format=format)
        self.assertRaises(errors.NoRepositoryPresent,
                          branch.bzrdir.open_repository)

    def test_create_branch_and_repo_under_shared_force_new(self):
        # creating a branch and repo in a shared repo can be forced to 
        # make a new repo
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_and_repo(self.get_url('child'),
                                                      force_new_repo=True,
                                                      format=format)
        branch.bzrdir.open_repository()

    def test_create_standalone_working_tree(self):
        format = SampleBzrDirFormat()
        # note this is deliberately readonly, as this failure should 
        # occur before any writes.
        self.assertRaises(errors.NotLocalUrl,
                          bzrdir.BzrDir.create_standalone_workingtree,
                          self.get_readonly_url(), format=format)
        tree = bzrdir.BzrDir.create_standalone_workingtree('.', 
                                                           format=format)
        self.assertEqual('A tree', tree)

    def test_create_standalone_working_tree_under_shared_repo(self):
        # create standalone working tree always makes a repo.
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        # note this is deliberately readonly, as this failure should 
        # occur before any writes.
        self.assertRaises(errors.NotLocalUrl,
                          bzrdir.BzrDir.create_standalone_workingtree,
                          self.get_readonly_url('child'), format=format)
        tree = bzrdir.BzrDir.create_standalone_workingtree('child', 
            format=format)
        tree.bzrdir.open_repository()

    def test_create_branch_convenience(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = bzrdir.format_registry.make_bzrdir('knit')
        branch = bzrdir.BzrDir.create_branch_convenience('.', format=format)
        branch.bzrdir.open_workingtree()
        branch.bzrdir.open_repository()

    def test_create_branch_convenience_possible_transports(self):
        """Check that the optional 'possible_transports' is recognized"""
        format = bzrdir.format_registry.make_bzrdir('knit')
        t = self.get_transport()
        branch = bzrdir.BzrDir.create_branch_convenience(
            '.', format=format, possible_transports=[t])
        branch.bzrdir.open_workingtree()
        branch.bzrdir.open_repository()

    def test_create_branch_convenience_root(self):
        """Creating a branch at the root of a fs should work."""
        self.vfs_transport_factory = MemoryServer
        # outside a repo the default convenience output is a repo+branch_tree
        format = bzrdir.format_registry.make_bzrdir('knit')
        branch = bzrdir.BzrDir.create_branch_convenience(self.get_url(), 
                                                         format=format)
        self.assertRaises(errors.NoWorkingTree,
                          branch.bzrdir.open_workingtree)
        branch.bzrdir.open_repository()

    def test_create_branch_convenience_under_shared_repo(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience('child',
            format=format)
        branch.bzrdir.open_workingtree()
        self.assertRaises(errors.NoRepositoryPresent,
                          branch.bzrdir.open_repository)
            
    def test_create_branch_convenience_under_shared_repo_force_no_tree(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience('child',
            force_new_tree=False, format=format)
        self.assertRaises(errors.NoWorkingTree,
                          branch.bzrdir.open_workingtree)
        self.assertRaises(errors.NoRepositoryPresent,
                          branch.bzrdir.open_repository)
            
    def test_create_branch_convenience_under_shared_repo_no_tree_policy(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy
        format = bzrdir.format_registry.make_bzrdir('knit')
        repo = self.make_repository('.', shared=True, format=format)
        repo.set_make_working_trees(False)
        branch = bzrdir.BzrDir.create_branch_convenience('child', 
                                                         format=format)
        self.assertRaises(errors.NoWorkingTree,
                          branch.bzrdir.open_workingtree)
        self.assertRaises(errors.NoRepositoryPresent,
                          branch.bzrdir.open_repository)

    def test_create_branch_convenience_under_shared_repo_no_tree_policy_force_tree(self):
        # inside a repo the default convenience output is a branch+ follow the
        # repo tree policy but we can override that
        format = bzrdir.format_registry.make_bzrdir('knit')
        repo = self.make_repository('.', shared=True, format=format)
        repo.set_make_working_trees(False)
        branch = bzrdir.BzrDir.create_branch_convenience('child',
            force_new_tree=True, format=format)
        branch.bzrdir.open_workingtree()
        self.assertRaises(errors.NoRepositoryPresent,
                          branch.bzrdir.open_repository)

    def test_create_branch_convenience_under_shared_repo_force_new_repo(self):
        # inside a repo the default convenience output is overridable to give
        # repo+branch+tree
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.make_repository('.', shared=True, format=format)
        branch = bzrdir.BzrDir.create_branch_convenience('child',
            force_new_repo=True, format=format)
        branch.bzrdir.open_repository()
        branch.bzrdir.open_workingtree()


class TestRepositoryAcquisitionPolicy(TestCaseWithTransport):

    def test_acquire_repository_standalone(self):
        """The default acquisition policy should create a standalone branch."""
        my_bzrdir = self.make_bzrdir('.')
        repo_policy = my_bzrdir.determine_repository_policy()
        repo = repo_policy.acquire_repository()
        self.assertEqual(repo.bzrdir.root_transport.base,
                         my_bzrdir.root_transport.base)
        self.assertFalse(repo.is_shared())


    def test_determine_stacking_policy(self):
        parent_bzrdir = self.make_bzrdir('.')
        child_bzrdir = self.make_bzrdir('child')
        parent_bzrdir.get_config().set_default_stack_on('http://example.org')
        repo_policy = child_bzrdir.determine_repository_policy()
        self.assertEqual('http://example.org', repo_policy._stack_on)

    def test_determine_stacking_policy_relative(self):
        parent_bzrdir = self.make_bzrdir('.')
        child_bzrdir = self.make_bzrdir('child')
        parent_bzrdir.get_config().set_default_stack_on('child2')
        repo_policy = child_bzrdir.determine_repository_policy()
        self.assertEqual('child2', repo_policy._stack_on)
        self.assertEqual(parent_bzrdir.root_transport.base,
                         repo_policy._stack_on_pwd)

    def prepare_default_stacking(self, child_format='1.6'):
        parent_bzrdir = self.make_bzrdir('.')
        child_branch = self.make_branch('child', format=child_format)
        parent_bzrdir.get_config().set_default_stack_on(child_branch.base)
        new_child_transport = parent_bzrdir.transport.clone('child2')
        return child_branch, new_child_transport

    def test_clone_on_transport_obeys_stacking_policy(self):
        child_branch, new_child_transport = self.prepare_default_stacking()
        new_child = child_branch.bzrdir.clone_on_transport(new_child_transport)
        self.assertEqual(child_branch.base,
                         new_child.open_branch().get_stacked_on_url())

    def test_sprout_obeys_stacking_policy(self):
        child_branch, new_child_transport = self.prepare_default_stacking()
        new_child = child_branch.bzrdir.sprout(new_child_transport.base)
        self.assertEqual(child_branch.base,
                         new_child.open_branch().get_stacked_on_url())

    def test_clone_ignores_policy_for_unsupported_formats(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format='pack-0.92')
        new_child = child_branch.bzrdir.clone_on_transport(new_child_transport)
        self.assertRaises(errors.UnstackableBranchFormat,
                          new_child.open_branch().get_stacked_on_url)

    def test_sprout_ignores_policy_for_unsupported_formats(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format='pack-0.92')
        new_child = child_branch.bzrdir.sprout(new_child_transport.base)
        self.assertRaises(errors.UnstackableBranchFormat,
                          new_child.open_branch().get_stacked_on_url)

    def test_sprout_upgrades_format_if_stacked_specified(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format='pack-0.92')
        new_child = child_branch.bzrdir.sprout(new_child_transport.base,
                                               stacked=True)
        self.assertEqual(child_branch.bzrdir.root_transport.base,
                         new_child.open_branch().get_stacked_on_url())
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertFalse(repo.supports_rich_root())

    def test_clone_on_transport_upgrades_format_if_stacked_on_specified(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format='pack-0.92')
        new_child = child_branch.bzrdir.clone_on_transport(new_child_transport,
            stacked_on=child_branch.bzrdir.root_transport.base)
        self.assertEqual(child_branch.bzrdir.root_transport.base,
                         new_child.open_branch().get_stacked_on_url())
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertFalse(repo.supports_rich_root())

    def test_sprout_upgrades_to_rich_root_format_if_needed(self):
        child_branch, new_child_transport = self.prepare_default_stacking(
            child_format='rich-root-pack')
        new_child = child_branch.bzrdir.sprout(new_child_transport.base,
                                               stacked=True)
        repo = new_child.open_repository()
        self.assertTrue(repo._format.supports_external_lookups)
        self.assertTrue(repo.supports_rich_root())

    def test_add_fallback_repo_handles_absolute_urls(self):
        stack_on = self.make_branch('stack_on', format='1.6')
        repo = self.make_repository('repo', format='1.6')
        policy = bzrdir.UseExistingRepository(repo, stack_on.base)
        policy._add_fallback(repo)

    def test_add_fallback_repo_handles_relative_urls(self):
        stack_on = self.make_branch('stack_on', format='1.6')
        repo = self.make_repository('repo', format='1.6')
        policy = bzrdir.UseExistingRepository(repo, '.', stack_on.base)
        policy._add_fallback(repo)

    def test_configure_relative_branch_stacking_url(self):
        stack_on = self.make_branch('stack_on', format='1.6')
        stacked = self.make_branch('stack_on/stacked', format='1.6')
        policy = bzrdir.UseExistingRepository(stacked.repository,
            '.', stack_on.base)
        policy.configure_branch(stacked)
        self.assertEqual('..', stacked.get_stacked_on_url())

    def test_relative_branch_stacking_to_absolute(self):
        stack_on = self.make_branch('stack_on', format='1.6')
        stacked = self.make_branch('stack_on/stacked', format='1.6')
        policy = bzrdir.UseExistingRepository(stacked.repository,
            '.', self.get_readonly_url('stack_on'))
        policy.configure_branch(stacked)
        self.assertEqual(self.get_readonly_url('stack_on'),
                         stacked.get_stacked_on_url())


class ChrootedTests(TestCaseWithTransport):
    """A support class that provides readonly urls outside the local namespace.

    This is done by checking if self.transport_server is a MemoryServer. if it
    is then we are chrooted already, if it is not then an HttpServer is used
    for readonly urls.
    """

    def setUp(self):
        super(ChrootedTests, self).setUp()
        if not self.vfs_transport_factory == MemoryServer:
            self.transport_readonly_server = HttpServer

    def local_branch_path(self, branch):
         return os.path.realpath(urlutils.local_path_from_url(branch.base))

    def test_open_containing(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url(''))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing,
                          self.get_readonly_url('g/p/q'))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url(''))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing(self.get_readonly_url('g/p/q'))
        self.assertEqual('g/p/q', relpath)

    def test_open_containing_tree_branch_or_repository_empty(self):
        self.assertRaises(errors.NotBranchError,
            bzrdir.BzrDir.open_containing_tree_branch_or_repository,
            self.get_readonly_url(''))

    def test_open_containing_tree_branch_or_repository_all(self):
        self.make_branch_and_tree('topdir')
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'topdir/foo')
        self.assertEqual(os.path.realpath('topdir'),
                         os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath('topdir'),
                         self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join('topdir', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, 'foo')

    def test_open_containing_tree_branch_or_repository_no_tree(self):
        self.make_branch('branch')
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'branch/foo')
        self.assertEqual(tree, None)
        self.assertEqual(os.path.realpath('branch'),
                         self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join('branch', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, 'foo')

    def test_open_containing_tree_branch_or_repository_repo(self):
        self.make_repository('repo')
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'repo')
        self.assertEqual(tree, None)
        self.assertEqual(branch, None)
        self.assertEqual(
            osutils.realpath(os.path.join('repo', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, '')

    def test_open_containing_tree_branch_or_repository_shared_repo(self):
        self.make_repository('shared', shared=True)
        bzrdir.BzrDir.create_branch_convenience('shared/branch',
                                                force_new_tree=False)
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'shared/branch')
        self.assertEqual(tree, None)
        self.assertEqual(os.path.realpath('shared/branch'),
                         self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join('shared', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, '')

    def test_open_containing_tree_branch_or_repository_branch_subdir(self):
        self.make_branch_and_tree('foo')
        self.build_tree(['foo/bar/'])
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'foo/bar')
        self.assertEqual(os.path.realpath('foo'),
                         os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath('foo'),
                         self.local_branch_path(branch))
        self.assertEqual(
            osutils.realpath(os.path.join('foo', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, 'bar')

    def test_open_containing_tree_branch_or_repository_repo_subdir(self):
        self.make_repository('bar')
        self.build_tree(['bar/baz/'])
        tree, branch, repo, relpath = \
            bzrdir.BzrDir.open_containing_tree_branch_or_repository(
                'bar/baz')
        self.assertEqual(tree, None)
        self.assertEqual(branch, None)
        self.assertEqual(
            osutils.realpath(os.path.join('bar', '.bzr', 'repository')),
            repo.bzrdir.transport.local_abspath('repository'))
        self.assertEqual(relpath, 'baz')

    def test_open_containing_from_transport(self):
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_from_transport,
                          get_transport(self.get_readonly_url('')))
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_containing_from_transport,
                          get_transport(self.get_readonly_url('g/p/q')))
        control = bzrdir.BzrDir.create(self.get_url())
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            get_transport(self.get_readonly_url('')))
        self.assertEqual('', relpath)
        branch, relpath = bzrdir.BzrDir.open_containing_from_transport(
            get_transport(self.get_readonly_url('g/p/q')))
        self.assertEqual('g/p/q', relpath)

    def test_open_containing_tree_or_branch(self):
        self.make_branch_and_tree('topdir')
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            'topdir/foo')
        self.assertEqual(os.path.realpath('topdir'),
                         os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath('topdir'),
                         self.local_branch_path(branch))
        self.assertIs(tree.bzrdir, branch.bzrdir)
        self.assertEqual('foo', relpath)
        # opening from non-local should not return the tree
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            self.get_readonly_url('topdir/foo'))
        self.assertEqual(None, tree)
        self.assertEqual('foo', relpath)
        # without a tree:
        self.make_branch('topdir/foo')
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            'topdir/foo')
        self.assertIs(tree, None)
        self.assertEqual(os.path.realpath('topdir/foo'),
                         self.local_branch_path(branch))
        self.assertEqual('', relpath)

    def test_open_tree_or_branch(self):
        self.make_branch_and_tree('topdir')
        tree, branch = bzrdir.BzrDir.open_tree_or_branch('topdir')
        self.assertEqual(os.path.realpath('topdir'),
                         os.path.realpath(tree.basedir))
        self.assertEqual(os.path.realpath('topdir'),
                         self.local_branch_path(branch))
        self.assertIs(tree.bzrdir, branch.bzrdir)
        # opening from non-local should not return the tree
        tree, branch = bzrdir.BzrDir.open_tree_or_branch(
            self.get_readonly_url('topdir'))
        self.assertEqual(None, tree)
        # without a tree:
        self.make_branch('topdir/foo')
        tree, branch = bzrdir.BzrDir.open_tree_or_branch('topdir/foo')
        self.assertIs(tree, None)
        self.assertEqual(os.path.realpath('topdir/foo'),
                         self.local_branch_path(branch))

    def test_open_from_transport(self):
        # transport pointing at bzrdir should give a bzrdir with root transport
        # set to the given transport
        control = bzrdir.BzrDir.create(self.get_url())
        transport = get_transport(self.get_url())
        opened_bzrdir = bzrdir.BzrDir.open_from_transport(transport)
        self.assertEqual(transport.base, opened_bzrdir.root_transport.base)
        self.assertIsInstance(opened_bzrdir, bzrdir.BzrDir)
        
    def test_open_from_transport_no_bzrdir(self):
        transport = get_transport(self.get_url())
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport,
                          transport)

    def test_open_from_transport_bzrdir_in_parent(self):
        control = bzrdir.BzrDir.create(self.get_url())
        transport = get_transport(self.get_url())
        transport.mkdir('subdir')
        transport = transport.clone('subdir')
        self.assertRaises(NotBranchError, bzrdir.BzrDir.open_from_transport,
                          transport)

    def test_sprout_recursive(self):
        tree = self.make_branch_and_tree('tree1', format='dirstate-with-subtree')
        sub_tree = self.make_branch_and_tree('tree1/subtree',
            format='dirstate-with-subtree')
        tree.add_reference(sub_tree)
        self.build_tree(['tree1/subtree/file'])
        sub_tree.add('file')
        tree.commit('Initial commit')
        tree.bzrdir.sprout('tree2')
        self.failUnlessExists('tree2/subtree/file')

    def test_cloning_metadir(self):
        """Ensure that cloning metadir is suitable"""
        bzrdir = self.make_bzrdir('bzrdir')
        bzrdir.cloning_metadir()
        branch = self.make_branch('branch', format='knit')
        format = branch.bzrdir.cloning_metadir()
        self.assertIsInstance(format.workingtree_format,
            workingtree.WorkingTreeFormat3)

    def test_sprout_recursive_treeless(self):
        tree = self.make_branch_and_tree('tree1',
            format='dirstate-with-subtree')
        sub_tree = self.make_branch_and_tree('tree1/subtree',
            format='dirstate-with-subtree')
        tree.add_reference(sub_tree)
        self.build_tree(['tree1/subtree/file'])
        sub_tree.add('file')
        tree.commit('Initial commit')
        tree.bzrdir.destroy_workingtree()
        repo = self.make_repository('repo', shared=True,
            format='dirstate-with-subtree')
        repo.set_make_working_trees(False)
        tree.bzrdir.sprout('repo/tree2')
        self.failUnlessExists('repo/tree2/subtree')
        self.failIfExists('repo/tree2/subtree/file')

    def make_foo_bar_baz(self):
        foo = bzrdir.BzrDir.create_branch_convenience('foo').bzrdir
        bar = self.make_branch('foo/bar').bzrdir
        baz = self.make_branch('baz').bzrdir
        return foo, bar, baz

    def test_find_bzrdirs(self):
        foo, bar, baz = self.make_foo_bar_baz()
        transport = get_transport(self.get_url())
        self.assertEqualBzrdirs([baz, foo, bar],
                                bzrdir.BzrDir.find_bzrdirs(transport))

    def test_find_bzrdirs_list_current(self):
        def list_current(transport):
            return [s for s in transport.list_dir('') if s != 'baz']

        foo, bar, baz = self.make_foo_bar_baz()
        transport = get_transport(self.get_url())
        self.assertEqualBzrdirs([foo, bar],
                                bzrdir.BzrDir.find_bzrdirs(transport,
                                    list_current=list_current))


    def test_find_bzrdirs_evaluate(self):
        def evaluate(bzrdir):
            try:
                repo = bzrdir.open_repository()
            except NoRepositoryPresent:
                return True, bzrdir.root_transport.base
            else:
                return False, bzrdir.root_transport.base

        foo, bar, baz = self.make_foo_bar_baz()
        transport = get_transport(self.get_url())
        self.assertEqual([baz.root_transport.base, foo.root_transport.base],
                         list(bzrdir.BzrDir.find_bzrdirs(transport,
                                                         evaluate=evaluate)))

    def assertEqualBzrdirs(self, first, second):
        first = list(first)
        second = list(second)
        self.assertEqual(len(first), len(second))
        for x, y in zip(first, second):
            self.assertEqual(x.root_transport.base, y.root_transport.base)

    def test_find_branches(self):
        root = self.make_repository('', shared=True)
        foo, bar, baz = self.make_foo_bar_baz()
        qux = self.make_bzrdir('foo/qux')
        transport = get_transport(self.get_url())
        branches = bzrdir.BzrDir.find_branches(transport)
        self.assertEqual(baz.root_transport.base, branches[0].base)
        self.assertEqual(foo.root_transport.base, branches[1].base)
        self.assertEqual(bar.root_transport.base, branches[2].base)

        # ensure this works without a top-level repo
        branches = bzrdir.BzrDir.find_branches(transport.clone('foo'))
        self.assertEqual(foo.root_transport.base, branches[0].base)
        self.assertEqual(bar.root_transport.base, branches[1].base)


class TestMeta1DirFormat(TestCaseWithTransport):
    """Tests specific to the meta1 dir format."""

    def test_right_base_dirs(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        branch_base = t.clone('branch').base
        self.assertEqual(branch_base, dir.get_branch_transport(None).base)
        self.assertEqual(branch_base,
                         dir.get_branch_transport(bzrlib.branch.BzrBranchFormat5()).base)
        repository_base = t.clone('repository').base
        self.assertEqual(repository_base, dir.get_repository_transport(None).base)
        self.assertEqual(repository_base,
                         dir.get_repository_transport(weaverepo.RepositoryFormat7()).base)
        checkout_base = t.clone('checkout').base
        self.assertEqual(checkout_base, dir.get_workingtree_transport(None).base)
        self.assertEqual(checkout_base,
                         dir.get_workingtree_transport(workingtree.WorkingTreeFormat3()).base)

    def test_meta1dir_uses_lockdir(self):
        """Meta1 format uses a LockDir to guard the whole directory, not a file."""
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        t = dir.transport
        self.assertIsDirectory('branch-lock', t)

    def test_comparison(self):
        """Equality and inequality behave properly.

        Metadirs should compare equal iff they have the same repo, branch and
        tree formats.
        """
        mydir = bzrdir.format_registry.make_bzrdir('knit')
        self.assertEqual(mydir, mydir)
        self.assertFalse(mydir != mydir)
        otherdir = bzrdir.format_registry.make_bzrdir('knit')
        self.assertEqual(otherdir, mydir)
        self.assertFalse(otherdir != mydir)
        otherdir2 = bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')
        self.assertNotEqual(otherdir2, mydir)
        self.assertFalse(otherdir2 == mydir)

    def test_needs_conversion_different_working_tree(self):
        # meta1dirs need an conversion if any element is not the default.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        # test with 
        new_default = bzrdir.format_registry.make_bzrdir('dirstate')
        bzrdir.BzrDirFormat._set_default_format(new_default)
        try:
            tree = self.make_branch_and_tree('tree', format='knit')
            self.assertTrue(tree.bzrdir.needs_format_conversion())
        finally:
            bzrdir.BzrDirFormat._set_default_format(old_format)


class TestFormat5(TestCaseWithTransport):
    """Tests specific to the version 5 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created 
        # for format 5 objects
        dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = bzrdir.BzrDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)
    
    def test_can_convert(self):
        # format 5 dirs are convertable
        dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())
    
    def test_needs_conversion(self):
        # format 5 dirs need a conversion if they are not the default.
        # and they start of not the default.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat._set_default_format(bzrdir.BzrDirFormat5())
        try:
            dir = bzrdir.BzrDirFormat5().initialize(self.get_url())
            self.assertFalse(dir.needs_format_conversion())
        finally:
            bzrdir.BzrDirFormat._set_default_format(old_format)
        self.assertTrue(dir.needs_format_conversion())


class TestFormat6(TestCaseWithTransport):
    """Tests specific to the version 6 bzrdir format."""

    def test_same_lockfiles_between_tree_repo_branch(self):
        # this checks that only a single lockfiles instance is created 
        # for format 6 objects
        dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
        def check_dir_components_use_same_lock(dir):
            ctrl_1 = dir.open_repository().control_files
            ctrl_2 = dir.open_branch().control_files
            ctrl_3 = dir.open_workingtree()._control_files
            self.assertTrue(ctrl_1 is ctrl_2)
            self.assertTrue(ctrl_2 is ctrl_3)
        check_dir_components_use_same_lock(dir)
        # and if we open it normally.
        dir = bzrdir.BzrDir.open(self.get_url())
        check_dir_components_use_same_lock(dir)
    
    def test_can_convert(self):
        # format 6 dirs are convertable
        dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
        self.assertTrue(dir.can_convert_format())
    
    def test_needs_conversion(self):
        # format 6 dirs need an conversion if they are not the default.
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat._set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            dir = bzrdir.BzrDirFormat6().initialize(self.get_url())
            self.assertTrue(dir.needs_format_conversion())
        finally:
            bzrdir.BzrDirFormat._set_default_format(old_format)


class NotBzrDir(bzrlib.bzrdir.BzrDir):
    """A non .bzr based control directory."""

    def __init__(self, transport, format):
        self._format = format
        self.root_transport = transport
        self.transport = transport.clone('.not')


class NotBzrDirFormat(bzrlib.bzrdir.BzrDirFormat):
    """A test class representing any non-.bzr based disk format."""

    def initialize_on_transport(self, transport):
        """Initialize a new .not dir in the base directory of a Transport."""
        transport.mkdir('.not')
        return self.open(transport)

    def open(self, transport):
        """Open this directory."""
        return NotBzrDir(transport, self)

    @classmethod
    def _known_formats(self):
        return set([NotBzrDirFormat()])

    @classmethod
    def probe_transport(self, transport):
        """Our format is present if the transport ends in '.not/'."""
        if transport.has('.not'):
            return NotBzrDirFormat()


class TestNotBzrDir(TestCaseWithTransport):
    """Tests for using the bzrdir api with a non .bzr based disk format.
    
    If/when one of these is in the core, we can let the implementation tests
    verify this works.
    """

    def test_create_and_find_format(self):
        # create a .notbzr dir 
        format = NotBzrDirFormat()
        dir = format.initialize(self.get_url())
        self.assertIsInstance(dir, NotBzrDir)
        # now probe for it.
        bzrlib.bzrdir.BzrDirFormat.register_control_format(format)
        try:
            found = bzrlib.bzrdir.BzrDirFormat.find_format(
                get_transport(self.get_url()))
            self.assertIsInstance(found, NotBzrDirFormat)
        finally:
            bzrlib.bzrdir.BzrDirFormat.unregister_control_format(format)

    def test_included_in_known_formats(self):
        bzrlib.bzrdir.BzrDirFormat.register_control_format(NotBzrDirFormat)
        try:
            formats = bzrlib.bzrdir.BzrDirFormat.known_formats()
            for format in formats:
                if isinstance(format, NotBzrDirFormat):
                    return
            self.fail("No NotBzrDirFormat in %s" % formats)
        finally:
            bzrlib.bzrdir.BzrDirFormat.unregister_control_format(NotBzrDirFormat)


class NonLocalTests(TestCaseWithTransport):
    """Tests for bzrdir static behaviour on non local paths."""

    def setUp(self):
        super(NonLocalTests, self).setUp()
        self.vfs_transport_factory = MemoryServer
    
    def test_create_branch_convenience(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = bzrdir.format_registry.make_bzrdir('knit')
        branch = bzrdir.BzrDir.create_branch_convenience(
            self.get_url('foo'), format=format)
        self.assertRaises(errors.NoWorkingTree,
                          branch.bzrdir.open_workingtree)
        branch.bzrdir.open_repository()

    def test_create_branch_convenience_force_tree_not_local_fails(self):
        # outside a repo the default convenience output is a repo+branch_tree
        format = bzrdir.format_registry.make_bzrdir('knit')
        self.assertRaises(errors.NotLocalUrl,
            bzrdir.BzrDir.create_branch_convenience,
            self.get_url('foo'),
            force_new_tree=True,
            format=format)
        t = get_transport(self.get_url('.'))
        self.assertFalse(t.has('foo'))

    def test_clone(self):
        # clone into a nonlocal path works
        format = bzrdir.format_registry.make_bzrdir('knit')
        branch = bzrdir.BzrDir.create_branch_convenience('local',
                                                         format=format)
        branch.bzrdir.open_workingtree()
        result = branch.bzrdir.clone(self.get_url('remote'))
        self.assertRaises(errors.NoWorkingTree,
                          result.open_workingtree)
        result.open_branch()
        result.open_repository()

    def test_checkout_metadir(self):
        # checkout_metadir has reasonable working tree format even when no
        # working tree is present
        self.make_branch('branch-knit2', format='dirstate-with-subtree')
        my_bzrdir = bzrdir.BzrDir.open(self.get_url('branch-knit2'))
        checkout_format = my_bzrdir.checkout_metadir()
        self.assertIsInstance(checkout_format.workingtree_format,
                              workingtree.WorkingTreeFormat3)


class TestHTTPRedirectionLoop(object):
    """Test redirection loop between two http servers.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithTwoWebservers.

    We can't inherit directly from TestCaseWithTwoWebservers or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete. 
    """

    # Should be defined by daughter classes to ensure redirection
    # still use the same transport implementation (not currently
    # enforced as it's a bit tricky to get right (see the FIXME
    # in BzrDir.open_from_transport for the unique use case so
    # far)
    _qualifier = None

    def create_transport_readonly_server(self):
        return HTTPServerRedirecting()

    def create_transport_secondary_server(self):
        return HTTPServerRedirecting()

    def setUp(self):
        # Both servers redirect to each server creating a loop
        super(TestHTTPRedirectionLoop, self).setUp()
        # The redirections will point to the new server
        self.new_server = self.get_readonly_server()
        # The requests to the old server will be redirected
        self.old_server = self.get_secondary_server()
        # Configure the redirections
        self.old_server.redirect_to(self.new_server.host, self.new_server.port)
        self.new_server.redirect_to(self.old_server.host, self.old_server.port)

    def _qualified_url(self, host, port):
        return 'http+%s://%s:%s' % (self._qualifier, host, port)

    def test_loop(self):
        # Starting from either server should loop
        old_url = self._qualified_url(self.old_server.host, 
                                      self.old_server.port)
        oldt = self._transport(old_url)
        self.assertRaises(errors.NotBranchError,
                          bzrdir.BzrDir.open_from_transport, oldt)
        new_url = self._qualified_url(self.new_server.host, 
                                      self.new_server.port)
        newt = self._transport(new_url)
        self.assertRaises(errors.NotBranchError,
                          bzrdir.BzrDir.open_from_transport, newt)


class TestHTTPRedirections_urllib(TestHTTPRedirectionLoop,
                                  TestCaseWithTwoWebservers):
    """Tests redirections for urllib implementation"""

    _qualifier = 'urllib'
    _transport = HttpTransport_urllib



class TestHTTPRedirections_pycurl(TestWithTransport_pycurl,
                                  TestHTTPRedirectionLoop,
                                  TestCaseWithTwoWebservers):
    """Tests redirections for pycurl implementation"""

    _qualifier = 'pycurl'


class TestDotBzrHidden(TestCaseWithTransport):

    ls = ['ls']
    if sys.platform == 'win32':
        ls = [os.environ['COMSPEC'], '/C', 'dir', '/B']

    def get_ls(self):
        f = subprocess.Popen(self.ls, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        out, err = f.communicate()
        self.assertEqual(0, f.returncode, 'Calling %s failed: %s'
                         % (self.ls, err))
        return out.splitlines()

    def test_dot_bzr_hidden(self):
        if sys.platform == 'win32' and not win32utils.has_win32file:
            raise TestSkipped('unable to make file hidden without pywin32 library')
        b = bzrdir.BzrDir.create('.')
        self.build_tree(['a'])
        self.assertEquals(['a'], self.get_ls())

    def test_dot_bzr_hidden_with_url(self):
        if sys.platform == 'win32' and not win32utils.has_win32file:
            raise TestSkipped('unable to make file hidden without pywin32 library')
        b = bzrdir.BzrDir.create(urlutils.local_path_to_url('.'))
        self.build_tree(['a'])
        self.assertEquals(['a'], self.get_ls())


class _TestBzrDirFormat(bzrdir.BzrDirMetaFormat1):
    """Test BzrDirFormat implementation for TestBzrDirSprout."""

    def _open(self, transport):
        return _TestBzrDir(transport, self)


class _TestBzrDir(bzrdir.BzrDirMeta1):
    """Test BzrDir implementation for TestBzrDirSprout.
    
    When created a _TestBzrDir already has repository and a branch.  The branch
    is a test double as well.
    """

    def __init__(self, *args, **kwargs):
        super(_TestBzrDir, self).__init__(*args, **kwargs)
        self.test_branch = _TestBranch()
        self.test_branch.repository = self.create_repository()

    def open_branch(self, unsupported=False):
        return self.test_branch

    def cloning_metadir(self, require_stacking=False):
        return _TestBzrDirFormat()


class _TestBranch(bzrlib.branch.Branch):
    """Test Branch implementation for TestBzrDirSprout."""

    def __init__(self, *args, **kwargs):
        super(_TestBranch, self).__init__(*args, **kwargs)
        self.calls = []
        self._parent = None

    def sprout(self, *args, **kwargs):
        self.calls.append('sprout')
        return _TestBranch()

    def copy_content_into(self, destination, revision_id=None):
        self.calls.append('copy_content_into')

    def get_parent(self):
        return self._parent

    def set_parent(self, parent):
        self._parent = parent


class TestBzrDirSprout(TestCaseWithMemoryTransport):

    def test_sprout_uses_branch_sprout(self):
        """BzrDir.sprout calls Branch.sprout.

        Usually, BzrDir.sprout should delegate to the branch's sprout method
        for part of the work.  This allows the source branch to control the
        choice of format for the new branch.
        
        There are exceptions, but this tests avoids them:
          - if there's no branch in the source bzrdir,
          - or if the stacking has been requested and the format needs to be
            overridden to satisfy that.
        """
        # Make an instrumented bzrdir.
        t = self.get_transport('source')
        t.ensure_base()
        source_bzrdir = _TestBzrDirFormat().initialize_on_transport(t)
        # The instrumented bzrdir has a test_branch attribute that logs calls
        # made to the branch contained in that bzrdir.  Initially the test
        # branch exists but no calls have been made to it.
        self.assertEqual([], source_bzrdir.test_branch.calls)

        # Sprout the bzrdir
        target_url = self.get_url('target')
        result = source_bzrdir.sprout(target_url, recurse='no')

        # The bzrdir called the branch's sprout method.
        self.assertSubset(['sprout'], source_bzrdir.test_branch.calls)

    def test_sprout_parent(self):
        grandparent_tree = self.make_branch('grandparent')
        parent = grandparent_tree.bzrdir.sprout('parent').open_branch()
        branch_tree = parent.bzrdir.sprout('branch').open_branch()
        self.assertContainsRe(branch_tree.get_parent(), '/parent/$')
