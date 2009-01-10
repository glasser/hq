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


"""Tests for the commit CLI of bzr."""

import os
import sys

from bzrlib import (
    osutils,
    ignores,
    msgeditor,
    osutils,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import (
    probe_bad_non_ascii,
    TestSkipped,
    )
from bzrlib.tests.blackbox import ExternalBase


class TestCommit(ExternalBase):

    def test_05_empty_commit(self):
        """Commit of tree with no versioned files should fail"""
        # If forced, it should succeed, but this is not tested here.
        self.make_branch_and_tree('.')
        self.build_tree(['hello.txt'])
        out,err = self.run_bzr('commit -m empty', retcode=3)
        self.assertEqual('', out)
        self.assertContainsRe(err, 'bzr: ERROR: no changes to commit\.'
                                  ' use --unchanged to commit anyhow\n')

    def test_commit_success(self):
        """Successful commit should not leave behind a bzr-commit-* file"""
        self.make_branch_and_tree('.')
        self.run_bzr('commit --unchanged -m message')
        self.assertEqual('', self.run_bzr('unknowns')[0])

        # same for unicode messages
        self.run_bzr(["commit", "--unchanged", "-m", u'foo\xb5'])
        self.assertEqual('', self.run_bzr('unknowns')[0])

    def test_commit_with_path(self):
        """Commit tree with path of root specified"""
        a_tree = self.make_branch_and_tree('a')
        self.build_tree(['a/a_file'])
        a_tree.add('a_file')
        self.run_bzr(['commit', '-m', 'first commit', 'a'])

        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        self.build_tree_contents([('b/a_file', 'changes in b')])
        self.run_bzr(['commit', '-m', 'first commit in b', 'b'])

        self.build_tree_contents([('a/a_file', 'new contents')])
        self.run_bzr(['commit', '-m', 'change in a', 'a'])

        b_tree.merge_from_branch(a_tree.branch)
        self.assertEqual(len(b_tree.conflicts()), 1)
        self.run_bzr('resolved b/a_file')
        self.run_bzr(['commit', '-m', 'merge into b', 'b'])


    def test_10_verbose_commit(self):
        """Add one file and examine verbose commit output"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt'])
        tree.add("hello.txt")
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'added hello.txt\n'
                              'Committed revision 1.\n$',)

    def prepare_simple_history(self):
        """Prepare and return a working tree with one commit of one file"""
        # Commit with modified file should say so
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        wt.commit(message='added')
        return wt

    def test_verbose_commit_modified(self):
        # Verbose commit of modified file should say so
        wt = self.prepare_simple_history()
        self.build_tree_contents([('hello.txt', 'new contents')])
        out, err = self.run_bzr('commit -m modified')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'modified hello\.txt\n'
                              'Committed revision 2\.\n$')

    def test_verbose_commit_renamed(self):
        # Verbose commit of renamed file should say so
        wt = self.prepare_simple_history()
        wt.rename_one('hello.txt', 'gutentag.txt')
        out, err = self.run_bzr('commit -m renamed')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'renamed hello\.txt => gutentag\.txt\n'
                              'Committed revision 2\.$\n')

    def test_verbose_commit_moved(self):
        # Verbose commit of file moved to new directory should say so
        wt = self.prepare_simple_history()
        os.mkdir('subdir')
        wt.add(['subdir'])
        wt.rename_one('hello.txt', 'subdir/hello.txt')
        out, err = self.run_bzr('commit -m renamed')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'added subdir\n'
                              'renamed hello\.txt => subdir/hello\.txt\n'
                              'Committed revision 2\.\n$')

    def test_verbose_commit_with_unknown(self):
        """Unknown files should not be listed by default in verbose output"""
        # Is that really the best policy?
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'added hello\.txt\n'
                              'Committed revision 1\.\n$')

    def test_verbose_commit_with_unchanged(self):
        """Unchanged files should not be listed by default in verbose output"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt', 'unchanged.txt'])
        tree.add('unchanged.txt')
        self.run_bzr('commit -m unchanged unchanged.txt')
        tree.add("hello.txt")
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        self.assertContainsRe(err, '^Committing to: .*\n'
                              'added hello\.txt\n'
                              'Committed revision 2\.$\n')

    def test_verbose_commit_includes_master_location(self):
        """Location of master is displayed when committing to bound branch"""
        a_tree = self.make_branch_and_tree('a')
        self.build_tree(['a/b'])
        a_tree.add('b')
        a_tree.commit(message='Initial message')

        b_tree = a_tree.branch.create_checkout('b')
        expected = "%s/" % (osutils.abspath('a'), )
        out, err = self.run_bzr('commit -m blah --unchanged', working_dir='b')
        self.assertEqual(err, 'Committing to: %s\n'
                         'Committed revision 2.\n' % expected)

    def test_commit_merge_reports_all_modified_files(self):
        # the commit command should show all the files that are shown by
        # bzr diff or bzr status when committing, even when they were not
        # changed by the user but rather through doing a merge.
        this_tree = self.make_branch_and_tree('this')
        # we need a bunch of files and dirs, to perform one action on each.
        self.build_tree([
            'this/dirtorename/',
            'this/dirtoreparent/',
            'this/dirtoleave/',
            'this/dirtoremove/',
            'this/filetoreparent',
            'this/filetorename',
            'this/filetomodify',
            'this/filetoremove',
            'this/filetoleave']
            )
        this_tree.add([
            'dirtorename',
            'dirtoreparent',
            'dirtoleave',
            'dirtoremove',
            'filetoreparent',
            'filetorename',
            'filetomodify',
            'filetoremove',
            'filetoleave']
            )
        this_tree.commit('create_files')
        other_dir = this_tree.bzrdir.sprout('other')
        other_tree = other_dir.open_workingtree()
        other_tree.lock_write()
        # perform the needed actions on the files and dirs.
        try:
            other_tree.rename_one('dirtorename', 'renameddir')
            other_tree.rename_one('dirtoreparent', 'renameddir/reparenteddir')
            other_tree.rename_one('filetorename', 'renamedfile')
            other_tree.rename_one('filetoreparent',
                                  'renameddir/reparentedfile')
            other_tree.remove(['dirtoremove', 'filetoremove'])
            self.build_tree_contents([
                ('other/newdir/',),
                ('other/filetomodify', 'new content'),
                ('other/newfile', 'new file content')])
            other_tree.add('newfile')
            other_tree.add('newdir/')
            other_tree.commit('modify all sample files and dirs.')
        finally:
            other_tree.unlock()
        this_tree.merge_from_branch(other_tree.branch)
        os.chdir('this')
        out,err = self.run_bzr('commit -m added')
        self.assertEqual('', out)
        expected = '%s/' % (osutils.getcwd(), )
        self.assertEqualDiff(
            'Committing to: %s\n'
            'modified filetomodify\n'
            'added newdir\n'
            'added newfile\n'
            'renamed dirtorename => renameddir\n'
            'renamed filetorename => renamedfile\n'
            'renamed dirtoreparent => renameddir/reparenteddir\n'
            'renamed filetoreparent => renameddir/reparentedfile\n'
            'deleted dirtoremove\n'
            'deleted filetoremove\n'
            'Committed revision 2.\n' % (expected, ),
            err)

    def test_empty_commit_message(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('foo.c', 'int main() {}')])
        tree.add('foo.c')
        self.run_bzr('commit -m ""', retcode=3)

    def test_unsupported_encoding_commit_message(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('foo.c', 'int main() {}')])
        tree.add('foo.c')
        # LANG env variable has no effect on Windows
        # but some characters anyway cannot be represented
        # in default user encoding
        char = probe_bad_non_ascii(osutils.get_user_encoding())
        if char is None:
            raise TestSkipped('Cannot find suitable non-ascii character'
                'for user_encoding (%s)' % osutils.get_user_encoding())
        out,err = self.run_bzr_subprocess('commit -m "%s"' % char,
                                          retcode=1,
                                          env_changes={'LANG': 'C'})
        self.assertContainsRe(err, r'bzrlib.errors.BzrError: Parameter.*is '
                                    'unsupported by the current encoding.')

    def test_other_branch_commit(self):
        # this branch is to ensure consistent behaviour, whether we're run
        # inside a branch, or not.
        outer_tree = self.make_branch_and_tree('.')
        inner_tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([
            ('branch/foo.c', 'int main() {}'),
            ('branch/bar.c', 'int main() {}')])
        inner_tree.add('foo.c')
        inner_tree.add('bar.c')
        # can't commit files in different trees; sane error
        self.run_bzr('commit -m newstuff branch/foo.c .', retcode=3)
        self.run_bzr('commit -m newstuff branch/foo.c')
        self.run_bzr('commit -m newstuff branch')
        self.run_bzr('commit -m newstuff branch', retcode=3)

    def test_out_of_date_tree_commit(self):
        # check we get an error code and a clear message committing with an out
        # of date checkout
        tree = self.make_branch_and_tree('branch')
        # make a checkout
        checkout = tree.branch.create_checkout('checkout', lightweight=True)
        # commit to the original branch to make the checkout out of date
        tree.commit('message branch', allow_pointless=True)
        # now commit to the checkout should emit
        # ERROR: Out of date with the branch, 'bzr update' is suggested
        output = self.run_bzr('commit --unchanged -m checkout_message '
                             'checkout', retcode=3)
        self.assertEqual(output,
                         ('',
                          "bzr: ERROR: Working tree is out of date, please "
                          "run 'bzr update'.\n"))

    def test_local_commit_unbound(self):
        # a --local commit on an unbound branch is an error
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('commit --local', retcode=3)
        self.assertEqualDiff('', out)
        self.assertEqualDiff('bzr: ERROR: Cannot perform local-only commits '
                             'on unbound branches.\n', err)

    def test_commit_a_text_merge_in_a_checkout(self):
        # checkouts perform multiple actions in a transaction across bond
        # branches and their master, and have been observed to fail in the
        # past. This is a user story reported to fail in bug #43959 where 
        # a merge done in a checkout (using the update command) failed to
        # commit correctly.
        trunk = self.make_branch_and_tree('trunk')

        u1 = trunk.branch.create_checkout('u1')
        self.build_tree_contents([('u1/hosts', 'initial contents')])
        u1.add('hosts')
        self.run_bzr('commit -m add-hosts u1')

        u2 = trunk.branch.create_checkout('u2')
        self.build_tree_contents([('u2/hosts', 'altered in u2')])
        self.run_bzr('commit -m checkin-from-u2 u2')

        # make an offline commits
        self.build_tree_contents([('u1/hosts', 'first offline change in u1')])
        self.run_bzr('commit -m checkin-offline --local u1')

        # now try to pull in online work from u2, and then commit our offline
        # work as a merge
        # retcode 1 as we expect a text conflict
        self.run_bzr('update u1', retcode=1)
        self.run_bzr('resolved u1/hosts')
        # add a text change here to represent resolving the merge conflicts in
        # favour of a new version of the file not identical to either the u1
        # version or the u2 version.
        self.build_tree_contents([('u1/hosts', 'merge resolution\n')])
        self.run_bzr('commit -m checkin-merge-of-the-offline-work-from-u1 u1')

    def test_commit_exclude_excludes_modified_files(self):
        """Commit -x foo should ignore changes to foo."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.smart_add(['.'])
        out, err = self.run_bzr(['commit', '-m', 'test', '-x', 'b'])
        self.assertFalse('added b' in out)
        self.assertFalse('added b' in err)
        # If b was excluded it will still be 'added' in status.
        out, err = self.run_bzr(['added'])
        self.assertEqual('b\n', out)
        self.assertEqual('', err)

    def test_commit_exclude_twice_uses_both_rules(self):
        """Commit -x foo -x bar should ignore changes to foo and bar."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.smart_add(['.'])
        out, err = self.run_bzr(['commit', '-m', 'test', '-x', 'b', '-x', 'c'])
        self.assertFalse('added b' in out)
        self.assertFalse('added c' in out)
        self.assertFalse('added b' in err)
        self.assertFalse('added c' in err)
        # If b was excluded it will still be 'added' in status.
        out, err = self.run_bzr(['added'])
        self.assertTrue('b\n' in out)
        self.assertTrue('c\n' in out)
        self.assertEqual('', err)

    def test_commit_respects_spec_for_removals(self):
        """Commit with a file spec should only commit removals that match"""
        t = self.make_branch_and_tree('.')
        self.build_tree(['file-a', 'dir-a/', 'dir-a/file-b'])
        t.add(['file-a', 'dir-a', 'dir-a/file-b'])
        t.commit('Create')
        t.remove(['file-a', 'dir-a/file-b'])
        os.chdir('dir-a')
        result = self.run_bzr('commit . -m removed-file-b')[1]
        self.assertNotContainsRe(result, 'file-a')
        result = self.run_bzr('status')[0]
        self.assertContainsRe(result, 'removed:\n  file-a')

    def test_strict_commit(self):
        """Commit with --strict works if everything is known"""
        ignores._set_user_ignores([])
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        # A simple change should just work
        self.run_bzr('commit --strict -m adding-a',
                     working_dir='tree')

    def test_strict_commit_no_changes(self):
        """commit --strict gives "no changes" if there is nothing to commit"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit('adding a')

        # With no changes, it should just be 'no changes'
        # Make sure that commit is failing because there is nothing to do
        self.run_bzr_error(['no changes to commit'],
                           'commit --strict -m no-changes',
                           working_dir='tree')

        # But --strict doesn't care if you supply --unchanged
        self.run_bzr('commit --strict --unchanged -m no-changes',
                     working_dir='tree')

    def test_strict_commit_unknown(self):
        """commit --strict fails if a file is unknown"""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add('a')
        tree.commit('adding a')

        # Add one file so there is a change, but forget the other
        self.build_tree(['tree/b', 'tree/c'])
        tree.add('b')
        self.run_bzr_error(['Commit refused because there are unknown files'],
                           'commit --strict -m add-b',
                           working_dir='tree')

        # --no-strict overrides --strict
        self.run_bzr('commit --strict -m add-b --no-strict',
                     working_dir='tree')

    def test_fixes_bug_output(self):
        """commit --fixes=lp:23452 succeeds without output."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        output, err = self.run_bzr(
            'commit -m hello --fixes=lp:23452 tree/hello.txt')
        self.assertEqual('', output)
        self.assertContainsRe(err, 'Committing to: .*\n'
                              'added hello\.txt\n'
                              'Committed revision 1\.\n')

    def test_no_bugs_no_properties(self):
        """If no bugs are fixed, the bugs property is not set.

        see https://beta.launchpad.net/bzr/+bug/109613
        """
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr( 'commit -m hello tree/hello.txt')
        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']
        self.assertFalse('bugs' in properties)

    def test_fixes_bug_sets_property(self):
        """commit --fixes=lp:234 sets the lp:234 revprop to 'fixed'."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:234 tree/hello.txt')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual({'bugs': 'https://launchpad.net/bugs/234 fixed'},
                         properties)

    def test_fixes_multiple_bugs_sets_properties(self):
        """--fixes can be used more than once to show that bugs are fixed."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:123 --fixes=lp:235'
                     ' tree/hello.txt')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual(
            {'bugs': 'https://launchpad.net/bugs/123 fixed\n'
                     'https://launchpad.net/bugs/235 fixed'},
            properties)

    def test_fixes_bug_with_alternate_trackers(self):
        """--fixes can be used on a properly configured branch to mark bug
        fixes on multiple trackers.
        """
        tree = self.make_branch_and_tree('tree')
        tree.branch.get_config().set_user_option(
            'trac_twisted_url', 'http://twistedmatrix.com/trac')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr('commit -m hello --fixes=lp:123 --fixes=twisted:235 tree/')

        # Get the revision properties, ignoring the branch-nick property, which
        # we don't care about for this test.
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = dict(last_rev.properties)
        del properties['branch-nick']

        self.assertEqual(
            {'bugs': 'https://launchpad.net/bugs/123 fixed\n'
                     'http://twistedmatrix.com/trac/ticket/235 fixed'},
            properties)

    def test_fixes_unknown_bug_prefix(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            ["Unrecognized bug %s. Commit refused." % 'xxx:123'],
            'commit -m add-b --fixes=xxx:123',
            working_dir='tree')

    def test_fixes_invalid_bug_number(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            ["Invalid bug identifier for %s. Commit refused." % 'lp:orange'],
            'commit -m add-b --fixes=lp:orange',
            working_dir='tree')

    def test_fixes_invalid_argument(self):
        """Raise an appropriate error when the fixes argument isn't tag:id."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr_error(
            [r"Invalid bug orange. Must be in the form of 'tag:id'\. "
             r"Commit refused\."],
            'commit -m add-b --fixes=orange',
            working_dir='tree')

    def test_no_author(self):
        """If the author is not specified, the author property is not set."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr( 'commit -m hello tree/hello.txt')
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertFalse('author' in properties)

    def test_author_sets_property(self):
        """commit --author='John Doe <jdoe@example.com>' sets the author
           revprop.
        """
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        self.run_bzr(["commit", '-m', 'hello',
                      '--author', u'John D\xf6 <jdoe@example.com>',
                     "tree/hello.txt"])
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertEqual(u'John D\xf6 <jdoe@example.com>', properties['author'])

    def test_author_no_email(self):
        """Author's name without an email address is allowed, too."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        out, err = self.run_bzr("commit -m hello --author='John Doe' "
                                "tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        properties = last_rev.properties
        self.assertEqual('John Doe', properties['author'])

    def test_partial_commit_with_renames_in_tree(self):
        # this test illustrates bug #140419
        t = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/a', 'test'])
        t.add(['dir/', 'dir/a', 'test'])
        t.commit('initial commit')
        # important part: file dir/a should change parent
        # and should appear before old parent
        # then during partial commit we have error
        # parent_id {dir-XXX} not in inventory
        t.rename_one('dir/a', 'a')
        self.build_tree_contents([('test', 'changes in test')])
        # partial commit
        out, err = self.run_bzr('commit test -m "partial commit"')
        self.assertEquals('', out)
        self.assertContainsRe(err, r'modified test\nCommitted revision 2.')

    def test_commit_readonly_checkout(self):
        # https://bugs.edge.launchpad.net/bzr/+bug/129701
        # "UnlockableTransport error trying to commit in checkout of readonly
        # branch"
        self.make_branch('master')
        master = BzrDir.open_from_transport(
            self.get_readonly_transport('master')).open_branch()
        master.create_checkout('checkout')
        out, err = self.run_bzr(['commit', '--unchanged', '-mfoo', 'checkout'],
            retcode=3)
        self.assertContainsRe(err,
            r'^bzr: ERROR: Cannot lock.*readonly transport')

    def test_commit_hook_template(self):
        # Test that commit template hooks work
        def restoreDefaults():
            msgeditor.hooks['commit_message_template'] = []
            osutils.set_or_unset_env('BZR_EDITOR', default_editor)
        if sys.platform == "win32":
            f = file('fed.bat', 'w')
            f.write('@rem dummy fed')
            f.close()
            default_editor = osutils.set_or_unset_env('BZR_EDITOR', "fed.bat")
        else:
            f = file('fed.sh', 'wb')
            f.write('#!/bin/sh\n')
            f.close()
            os.chmod('fed.sh', 0755)
            default_editor = osutils.set_or_unset_env('BZR_EDITOR', "./fed.sh")
        self.addCleanup(restoreDefaults)
        msgeditor.hooks.install_named_hook("commit_message_template",
                lambda commit_obj, msg: "save me some typing\n", None)
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/hello.txt'])
        tree.add('hello.txt')
        out, err = self.run_bzr("commit tree/hello.txt")
        last_rev = tree.branch.repository.get_revision(tree.last_revision())
        self.assertEqual('save me some typing\n', last_rev.message)
