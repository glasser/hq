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

"""Tests for the Branch facility that are not interface  tests.

For interface tests see tests/branch_implementations/*.py.

For concrete class tests see this file, and for meta-branch tests
also see this file.
"""

from StringIO import StringIO

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    config,
    errors,
    trace,
    urlutils,
    )
from bzrlib.branch import (
    Branch,
    BranchHooks,
    BranchFormat,
    BranchReferenceFormat,
    BzrBranch5,
    BzrBranchFormat5,
    BzrBranchFormat6,
    PullResult,
    _run_with_write_locked_target,
    )
from bzrlib.bzrdir import (BzrDirMetaFormat1, BzrDirMeta1, 
                           BzrDir, BzrDirFormat)
from bzrlib.errors import (NotBranchError,
                           UnknownFormatError,
                           UnknownHook,
                           UnsupportedFormatError,
                           )

from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.transport import get_transport


class TestDefaultFormat(TestCase):

    def test_default_format(self):
        # update this if you change the default branch format
        self.assertIsInstance(BranchFormat.get_default_format(),
                BzrBranchFormat6)

    def test_default_format_is_same_as_bzrdir_default(self):
        # XXX: it might be nice if there was only one place the default was
        # set, but at the moment that's not true -- mbp 20070814 -- 
        # https://bugs.launchpad.net/bzr/+bug/132376
        self.assertEqual(BranchFormat.get_default_format(),
                BzrDirFormat.get_default_format().get_branch_format())

    def test_get_set_default_format(self):
        # set the format and then set it back again
        old_format = BranchFormat.get_default_format()
        BranchFormat.set_default_format(SampleBranchFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = BzrDirMetaFormat1().initialize('memory:///')
            result = dir.create_branch()
            self.assertEqual(result, 'A branch')
        finally:
            BranchFormat.set_default_format(old_format)
        self.assertEqual(old_format, BranchFormat.get_default_format())


class TestBranchFormat5(TestCaseWithTransport):
    """Tests specific to branch format 5"""

    def test_branch_format_5_uses_lockdir(self):
        url = self.get_url()
        bzrdir = BzrDirMetaFormat1().initialize(url)
        bzrdir.create_repository()
        branch = bzrdir.create_branch()
        t = self.get_transport()
        self.log("branch instance is %r" % branch)
        self.assert_(isinstance(branch, BzrBranch5))
        self.assertIsDirectory('.', t)
        self.assertIsDirectory('.bzr/branch', t)
        self.assertIsDirectory('.bzr/branch/lock', t)
        branch.lock_write()
        try:
            self.assertIsDirectory('.bzr/branch/lock/held', t)
        finally:
            branch.unlock()

    def test_set_push_location(self):
        from bzrlib.config import (locations_config_filename,
                                   ensure_config_dir_exists)
        ensure_config_dir_exists()
        fn = locations_config_filename()
        # write correct newlines to locations.conf
        # by default ConfigObj uses native line-endings for new files
        # but uses already existing line-endings if file is not empty
        f = open(fn, 'wb')
        try:
            f.write('# comment\n')
        finally:
            f.close()

        branch = self.make_branch('.', format='knit')
        branch.set_push_location('foo')
        local_path = urlutils.local_path_from_url(branch.base[:-1])
        self.assertFileEqual("# comment\n"
                             "[%s]\n"
                             "push_location = foo\n"
                             "push_location:policy = norecurse\n" % local_path,
                             fn)

    # TODO RBC 20051029 test getting a push location from a branch in a
    # recursive section - that is, it appends the branch name.


class SampleBranchFormat(BranchFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See BzrBranchFormat.get_format_string()."""
        return "Sample branch format."

    def initialize(self, a_bzrdir):
        """Format 4 branches cannot be created."""
        t = a_bzrdir.get_branch_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A branch'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened branch."


class TestBzrBranchFormat(TestCaseWithTransport):
    """Tests for the BzrBranchFormat facility."""

    def test_find_format(self):
        # is the right format object found for a branch?
        # create a branch with a few known format objects.
        # this is not quite the same as 
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            format.initialize(dir)
            found_format = BranchFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(BzrBranchFormat5(), "bar")
        
    def test_find_format_not_branch(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        self.assertRaises(NotBranchError,
                          BranchFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        SampleBranchFormat().initialize(dir)
        self.assertRaises(UnknownFormatError,
                          BranchFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleBranchFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        # make a branch
        format.initialize(dir)
        # register a format for it.
        BranchFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(UnsupportedFormatError, Branch.open, self.get_url())
        self.make_branch_and_tree('foo')
        # but open_downlevel will work
        self.assertEqual(format.open(dir), bzrdir.BzrDir.open(self.get_url()).open_branch(unsupported=True))
        # unregister the format
        BranchFormat.unregister_format(format)
        self.make_branch_and_tree('bar')


class TestBranch67(object):
    """Common tests for both branch 6 and 7 which are mostly the same."""

    def get_format_name(self):
        raise NotImplementedError(self.get_format_name)

    def get_format_name_subtree(self):
        raise NotImplementedError(self.get_format_name)

    def get_class(self):
        raise NotImplementedError(self.get_class)

    def test_creation(self):
        format = BzrDirMetaFormat1()
        format.set_branch_format(_mod_branch.BzrBranchFormat6())
        branch = self.make_branch('a', format=format)
        self.assertIsInstance(branch, self.get_class())
        branch = self.make_branch('b', format=self.get_format_name())
        self.assertIsInstance(branch, self.get_class())
        branch = _mod_branch.Branch.open('a')
        self.assertIsInstance(branch, self.get_class())

    def test_layout(self):
        branch = self.make_branch('a', format=self.get_format_name())
        self.failUnlessExists('a/.bzr/branch/last-revision')
        self.failIfExists('a/.bzr/branch/revision-history')

    def test_config(self):
        """Ensure that all configuration data is stored in the branch"""
        branch = self.make_branch('a', format=self.get_format_name())
        branch.set_parent('http://bazaar-vcs.org')
        self.failIfExists('a/.bzr/branch/parent')
        self.assertEqual('http://bazaar-vcs.org', branch.get_parent())
        branch.set_push_location('sftp://bazaar-vcs.org')
        config = branch.get_config()._get_branch_data_config()
        self.assertEqual('sftp://bazaar-vcs.org',
                         config.get_user_option('push_location'))
        branch.set_bound_location('ftp://bazaar-vcs.org')
        self.failIfExists('a/.bzr/branch/bound')
        self.assertEqual('ftp://bazaar-vcs.org', branch.get_bound_location())

    def test_set_revision_history(self):
        builder = self.make_branch_builder('.', format=self.get_format_name())
        builder.build_snapshot('foo', None,
            [('add', ('', None, 'directory', None))],
            message='foo')
        builder.build_snapshot('bar', None, [], message='bar')
        branch = builder.get_branch()
        branch.lock_write()
        self.addCleanup(branch.unlock)
        branch.set_revision_history(['foo', 'bar'])
        branch.set_revision_history(['foo'])
        self.assertRaises(errors.NotLefthandHistory,
                          branch.set_revision_history, ['bar'])

    def do_checkout_test(self, lightweight=False):
        tree = self.make_branch_and_tree('source',
            format=self.get_format_name_subtree())
        subtree = self.make_branch_and_tree('source/subtree',
            format=self.get_format_name_subtree())
        subsubtree = self.make_branch_and_tree('source/subtree/subsubtree',
            format=self.get_format_name_subtree())
        self.build_tree(['source/subtree/file',
                         'source/subtree/subsubtree/file'])
        subsubtree.add('file')
        subtree.add('file')
        subtree.add_reference(subsubtree)
        tree.add_reference(subtree)
        tree.commit('a revision')
        subtree.commit('a subtree file')
        subsubtree.commit('a subsubtree file')
        tree.branch.create_checkout('target', lightweight=lightweight)
        self.failUnlessExists('target')
        self.failUnlessExists('target/subtree')
        self.failUnlessExists('target/subtree/file')
        self.failUnlessExists('target/subtree/subsubtree/file')
        subbranch = _mod_branch.Branch.open('target/subtree/subsubtree')
        if lightweight:
            self.assertEndsWith(subbranch.base, 'source/subtree/subsubtree/')
        else:
            self.assertEndsWith(subbranch.base, 'target/subtree/subsubtree/')

    def test_checkout_with_references(self):
        self.do_checkout_test()

    def test_light_checkout_with_references(self):
        self.do_checkout_test(lightweight=True)

    def test_set_push(self):
        branch = self.make_branch('source', format=self.get_format_name())
        branch.get_config().set_user_option('push_location', 'old',
            store=config.STORE_LOCATION)
        warnings = []
        def warning(*args):
            warnings.append(args[0] % args[1:])
        _warning = trace.warning
        trace.warning = warning
        try:
            branch.set_push_location('new')
        finally:
            trace.warning = _warning
        self.assertEqual(warnings[0], 'Value "new" is masked by "old" from '
                         'locations.conf')


class TestBranch6(TestBranch67, TestCaseWithTransport):

    def get_class(self):
        return _mod_branch.BzrBranch6

    def get_format_name(self):
        return "dirstate-tags"

    def get_format_name_subtree(self):
        return "dirstate-with-subtree"

    def test_set_stacked_on_url_errors(self):
        branch = self.make_branch('a', format=self.get_format_name())
        self.assertRaises(errors.UnstackableBranchFormat,
            branch.set_stacked_on_url, None)

    def test_default_stacked_location(self):
        branch = self.make_branch('a', format=self.get_format_name())
        self.assertRaises(errors.UnstackableBranchFormat, branch.get_stacked_on_url)


class TestBranch7(TestBranch67, TestCaseWithTransport):

    def get_class(self):
        return _mod_branch.BzrBranch7

    def get_format_name(self):
        return "development"

    def get_format_name_subtree(self):
        return "development-subtree"

    def test_set_stacked_on_url_unstackable_repo(self):
        repo = self.make_repository('a', format='dirstate-tags')
        control = repo.bzrdir
        branch = _mod_branch.BzrBranchFormat7().initialize(control)
        target = self.make_branch('b')
        self.assertRaises(errors.UnstackableRepositoryFormat,
            branch.set_stacked_on_url, target.base)

    def test_clone_stacked_on_unstackable_repo(self):
        repo = self.make_repository('a', format='dirstate-tags')
        control = repo.bzrdir
        branch = _mod_branch.BzrBranchFormat7().initialize(control)
        # Calling clone should not raise UnstackableRepositoryFormat.
        cloned_bzrdir = control.clone('cloned')

    def _test_default_stacked_location(self):
        branch = self.make_branch('a', format=self.get_format_name())
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)

    def test_stack_and_unstack(self):
        branch = self.make_branch('a', format=self.get_format_name())
        target = self.make_branch_and_tree('b', format=self.get_format_name())
        branch.set_stacked_on_url(target.branch.base)
        self.assertEqual(target.branch.base, branch.get_stacked_on_url())
        revid = target.commit('foo')
        self.assertTrue(branch.repository.has_revision(revid))
        branch.set_stacked_on_url(None)
        self.assertRaises(errors.NotStacked, branch.get_stacked_on_url)
        self.assertFalse(branch.repository.has_revision(revid))

    def test_open_opens_stacked_reference(self):
        branch = self.make_branch('a', format=self.get_format_name())
        target = self.make_branch_and_tree('b', format=self.get_format_name())
        branch.set_stacked_on_url(target.branch.base)
        branch = branch.bzrdir.open_branch()
        revid = target.commit('foo')
        self.assertTrue(branch.repository.has_revision(revid))


class TestBranchReference(TestCaseWithTransport):
    """Tests for the branch reference facility."""

    def test_create_open_reference(self):
        bzrdirformat = bzrdir.BzrDirMetaFormat1()
        t = get_transport(self.get_url('.'))
        t.mkdir('repo')
        dir = bzrdirformat.initialize(self.get_url('repo'))
        dir.create_repository()
        target_branch = dir.create_branch()
        t.mkdir('branch')
        branch_dir = bzrdirformat.initialize(self.get_url('branch'))
        made_branch = BranchReferenceFormat().initialize(branch_dir, target_branch)
        self.assertEqual(made_branch.base, target_branch.base)
        opened_branch = branch_dir.open_branch()
        self.assertEqual(opened_branch.base, target_branch.base)

    def test_get_reference(self):
        """For a BranchReference, get_reference should reutrn the location."""
        branch = self.make_branch('target')
        checkout = branch.create_checkout('checkout', lightweight=True)
        reference_url = branch.bzrdir.root_transport.abspath('') + '/'
        # if the api for create_checkout changes to return different checkout types
        # then this file read will fail.
        self.assertFileEqual(reference_url, 'checkout/.bzr/branch/location')
        self.assertEqual(reference_url,
            _mod_branch.BranchReferenceFormat().get_reference(checkout.bzrdir))


class TestHooks(TestCase):

    def test_constructor(self):
        """Check that creating a BranchHooks instance has the right defaults."""
        hooks = BranchHooks()
        self.assertTrue("set_rh" in hooks, "set_rh not in %s" % hooks)
        self.assertTrue("post_push" in hooks, "post_push not in %s" % hooks)
        self.assertTrue("post_commit" in hooks, "post_commit not in %s" % hooks)
        self.assertTrue("pre_commit" in hooks, "pre_commit not in %s" % hooks)
        self.assertTrue("post_pull" in hooks, "post_pull not in %s" % hooks)
        self.assertTrue("post_uncommit" in hooks, "post_uncommit not in %s" % hooks)
        self.assertTrue("post_change_branch_tip" in hooks,
                        "post_change_branch_tip not in %s" % hooks)

    def test_installed_hooks_are_BranchHooks(self):
        """The installed hooks object should be a BranchHooks."""
        # the installed hooks are saved in self._preserved_hooks.
        self.assertIsInstance(self._preserved_hooks[_mod_branch.Branch], BranchHooks)


class TestPullResult(TestCase):

    def test_pull_result_to_int(self):
        # to support old code, the pull result can be used as an int
        r = PullResult()
        r.old_revno = 10
        r.new_revno = 20
        # this usage of results is not recommended for new code (because it
        # doesn't describe very well what happened), but for api stability
        # it's still supported
        a = "%d revisions pulled" % r
        self.assertEqual(a, "10 revisions pulled")



class _StubLockable(object):
    """Helper for TestRunWithWriteLockedTarget."""

    def __init__(self, calls, unlock_exc=None):
        self.calls = calls
        self.unlock_exc = unlock_exc

    def lock_write(self):
        self.calls.append('lock_write')
    
    def unlock(self):
        self.calls.append('unlock')
        if self.unlock_exc is not None:
            raise self.unlock_exc


class _ErrorFromCallable(Exception):
    """Helper for TestRunWithWriteLockedTarget."""


class _ErrorFromUnlock(Exception):
    """Helper for TestRunWithWriteLockedTarget."""


class TestRunWithWriteLockedTarget(TestCase):
    """Tests for _run_with_write_locked_target."""

    def setUp(self):
        self._calls = []

    def func_that_returns_ok(self):
        self._calls.append('func called')
        return 'ok'

    def func_that_raises(self):
        self._calls.append('func called')
        raise _ErrorFromCallable()

    def test_success_unlocks(self):
        lockable = _StubLockable(self._calls)
        result = _run_with_write_locked_target(
            lockable, self.func_that_returns_ok)
        self.assertEqual('ok', result)
        self.assertEqual(['lock_write', 'func called', 'unlock'], self._calls)

    def test_exception_unlocks_and_propagates(self):
        lockable = _StubLockable(self._calls)
        self.assertRaises(_ErrorFromCallable,
            _run_with_write_locked_target, lockable, self.func_that_raises)
        self.assertEqual(['lock_write', 'func called', 'unlock'], self._calls)

    def test_callable_succeeds_but_error_during_unlock(self):
        lockable = _StubLockable(self._calls, unlock_exc=_ErrorFromUnlock())
        self.assertRaises(_ErrorFromUnlock,
            _run_with_write_locked_target, lockable, self.func_that_returns_ok)
        self.assertEqual(['lock_write', 'func called', 'unlock'], self._calls)

    def test_error_during_unlock_does_not_mask_original_error(self):
        lockable = _StubLockable(self._calls, unlock_exc=_ErrorFromUnlock())
        self.assertRaises(_ErrorFromCallable,
            _run_with_write_locked_target, lockable, self.func_that_raises)
        self.assertEqual(['lock_write', 'func called', 'unlock'], self._calls)


