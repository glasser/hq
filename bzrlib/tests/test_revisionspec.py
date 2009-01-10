# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

import datetime
import os
import time

from bzrlib import (
    branch,
    bzrdir,
    errors,
    repository,
    revision as _mod_revision,
    )
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.revisionspec import (
    RevisionSpec,
    RevisionSpec_revno,
    RevisionSpec_tag,
    )


def spec_in_history(spec, branch):
    """A simple helper to change a revision spec into a branch search"""
    return RevisionSpec.from_string(spec).in_history(branch)


# Basic class, which just creates a really basic set of revisions
class TestRevisionSpec(TestCaseWithTransport):

    def setUp(self):
        super(TestRevisionSpec, self).setUp()
        # this sets up a revision graph:
        # r1: []             1
        # alt_r2: [r1]       1.1.1
        # r2: [r1, alt_r2]   2

        self.tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        self.tree.lock_write()
        self.addCleanup(self.tree.unlock)
        self.tree.add(['a'])
        self.tree.commit('a', rev_id='r1')

        self.tree2 = self.tree.bzrdir.sprout('tree2').open_workingtree()
        self.tree2.commit('alt', rev_id='alt_r2')

        self.tree.merge_from_branch(self.tree2.branch)
        self.tree.commit('second', rev_id='r2')

    def get_in_history(self, revision_spec):
        return spec_in_history(revision_spec, self.tree.branch)

    def assertInHistoryIs(self, exp_revno, exp_revision_id, revision_spec):
        rev_info = self.get_in_history(revision_spec)
        self.assertEqual(exp_revno, rev_info.revno,
                         'Revision spec: %r returned wrong revno: %r != %r'
                         % (revision_spec, exp_revno, rev_info.revno))
        self.assertEqual(exp_revision_id, rev_info.rev_id,
                         'Revision spec: %r returned wrong revision id:'
                         ' %r != %r'
                         % (revision_spec, exp_revision_id, rev_info.rev_id))

    def assertInvalid(self, revision_spec, extra='',
                      invalid_as_revision_id=True):
        try:
            self.get_in_history(revision_spec)
        except errors.InvalidRevisionSpec, e:
            self.assertEqual(revision_spec, e.spec)
            self.assertEqual(extra, e.extra)
        else:
            self.fail('Expected InvalidRevisionSpec to be raised for'
                      ' %r.in_history' % (revision_spec,))
        if invalid_as_revision_id:
            try:
                spec = RevisionSpec.from_string(revision_spec)
                spec.as_revision_id(self.tree.branch)
            except errors.InvalidRevisionSpec, e:
                self.assertEqual(revision_spec, e.spec)
                self.assertEqual(extra, e.extra)
            else:
                self.fail('Expected InvalidRevisionSpec to be raised for'
                          ' %r.as_revision_id' % (revision_spec,))

    def assertAsRevisionId(self, revision_id, revision_spec):
        """Calling as_revision_id() should return the specified id."""
        spec = RevisionSpec.from_string(revision_spec)
        self.assertEqual(revision_id,
                         spec.as_revision_id(self.tree.branch))

    def get_as_tree(self, revision_spec, tree=None):
        if tree is None:
            tree = self.tree
        spec = RevisionSpec.from_string(revision_spec)
        return spec.as_tree(tree.branch)


class RevisionSpecMatchOnTrap(RevisionSpec):

    def _match_on(self, branch, revs):
        self.last_call = (branch, revs)
        return super(RevisionSpecMatchOnTrap, self)._match_on(branch, revs)


class TestRevisionSpecBase(TestRevisionSpec):

    def test_wants_revision_history(self):
        # If wants_revision_history = True, then _match_on should get the
        # branch revision history
        spec = RevisionSpecMatchOnTrap('foo', _internal=True)
        spec.in_history(self.tree.branch)

        self.assertEqual((self.tree.branch, ['r1' ,'r2']),
                         spec.last_call)

    def test_wants_no_revision_history(self):
        # If wants_revision_history = False, then _match_on should get None for
        # the branch revision history
        spec = RevisionSpecMatchOnTrap('foo', _internal=True)
        spec.wants_revision_history = False
        spec.in_history(self.tree.branch)

        self.assertEqual((self.tree.branch, None), spec.last_call)



class TestOddRevisionSpec(TestRevisionSpec):
    """Test things that aren't normally thought of as revision specs"""

    def test_none(self):
        self.assertInHistoryIs(None, None, None)

    def test_object(self):
        self.assertRaises(TypeError, RevisionSpec.from_string, object())

    def test_unregistered_spec(self):
        self.assertRaises(errors.NoSuchRevisionSpec,
                          RevisionSpec.from_string, 'foo')
        self.assertRaises(errors.NoSuchRevisionSpec,
                          RevisionSpec.from_string, '123a')



class TestRevnoFromString(TestCase):

    def test_from_string_dotted_decimal(self):
        self.assertRaises(errors.NoSuchRevisionSpec, RevisionSpec.from_string, '-1.1')
        self.assertRaises(errors.NoSuchRevisionSpec, RevisionSpec.from_string, '.1')
        self.assertRaises(errors.NoSuchRevisionSpec, RevisionSpec.from_string, '1..1')
        self.assertRaises(errors.NoSuchRevisionSpec, RevisionSpec.from_string, '1.2..1')
        self.assertRaises(errors.NoSuchRevisionSpec, RevisionSpec.from_string, '1.')
        self.assertIsInstance(RevisionSpec.from_string('1.1'), RevisionSpec_revno)
        self.assertIsInstance(RevisionSpec.from_string('1.1.3'), RevisionSpec_revno)


class TestRevisionSpec_revno(TestRevisionSpec):

    def test_positive_int(self):
        self.assertInHistoryIs(0, 'null:', '0')
        self.assertInHistoryIs(1, 'r1', '1')
        self.assertInHistoryIs(2, 'r2', '2')
        self.assertInvalid('3')

    def test_dotted_decimal(self):
        self.assertInHistoryIs(None, 'alt_r2', '1.1.1')

    def test_negative_int(self):
        self.assertInHistoryIs(2, 'r2', '-1')
        self.assertInHistoryIs(1, 'r1', '-2')

        self.assertInHistoryIs(1, 'r1', '-3')
        self.assertInHistoryIs(1, 'r1', '-4')
        self.assertInHistoryIs(1, 'r1', '-100')

    def test_positive(self):
        self.assertInHistoryIs(0, 'null:', 'revno:0')
        self.assertInHistoryIs(1, 'r1', 'revno:1')
        self.assertInHistoryIs(2, 'r2', 'revno:2')

        self.assertInvalid('revno:3')

    def test_negative(self):
        self.assertInHistoryIs(2, 'r2', 'revno:-1')
        self.assertInHistoryIs(1, 'r1', 'revno:-2')

        self.assertInHistoryIs(1, 'r1', 'revno:-3')
        self.assertInHistoryIs(1, 'r1', 'revno:-4')

    def test_invalid_number(self):
        # Get the right exception text
        try:
            int('X')
        except ValueError, e:
            pass
        self.assertInvalid('revno:X', extra='\n' + str(e))

    def test_missing_number_and_branch(self):
        self.assertInvalid('revno::',
                           extra='\ncannot have an empty revno and no branch')

    def test_invalid_number_with_branch(self):
        try:
            int('X')
        except ValueError, e:
            pass
        self.assertInvalid('revno:X:tree2', extra='\n' + str(e))

    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        spec = RevisionSpec.from_string('revno:2:tree2/a')
        self.assertRaises(errors.NotBranchError,
                          spec.in_history, self.tree.branch)

    def test_with_branch(self):
        # Passing a URL overrides the supplied branch path
        revinfo = self.get_in_history('revno:2:tree2')
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_int_with_branch(self):
        revinfo = self.get_in_history('2:tree2')
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_with_url(self):
        url = self.get_url() + '/tree2'
        revinfo = self.get_in_history('revno:2:%s' % (url,))
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_negative_with_url(self):
        url = self.get_url() + '/tree2'
        revinfo = self.get_in_history('revno:-1:%s' % (url,))
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual('alt_r2', revinfo.rev_id)

    def test_different_history_lengths(self):
        # Make sure we use the revisions and offsets in the supplied branch
        # not the ones in the original branch.
        self.tree2.commit('three', rev_id='r3')
        self.assertInHistoryIs(3, 'r3', 'revno:3:tree2')
        self.assertInHistoryIs(3, 'r3', 'revno:-1:tree2')

    def test_invalid_branch(self):
        self.assertRaises(errors.NotBranchError,
                          self.get_in_history, 'revno:-1:tree3')

    def test_invalid_revno_in_branch(self):
        self.tree.commit('three', rev_id='r3')
        self.assertInvalid('revno:3:tree2')

    def test_revno_n_path(self):
        """Old revno:N:path tests"""
        wta = self.make_branch_and_tree('a')
        ba = wta.branch
        
        wta.commit('Commit one', rev_id='a@r-0-1')
        wta.commit('Commit two', rev_id='a@r-0-2')
        wta.commit('Commit three', rev_id='a@r-0-3')

        wtb = self.make_branch_and_tree('b')
        bb = wtb.branch

        wtb.commit('Commit one', rev_id='b@r-0-1')
        wtb.commit('Commit two', rev_id='b@r-0-2')
        wtb.commit('Commit three', rev_id='b@r-0-3')


        self.assertEqual((1, 'a@r-0-1'),
                         spec_in_history('revno:1:a/', ba))
        # The argument of in_history should be ignored since it is
        # redundant with the path in the spec.
        self.assertEqual((1, 'a@r-0-1'),
                         spec_in_history('revno:1:a/', None))
        self.assertEqual((1, 'a@r-0-1'),
                         spec_in_history('revno:1:a/', bb))
        self.assertEqual((2, 'b@r-0-2'),
                         spec_in_history('revno:2:b/', None))

    def test_as_revision_id(self):
        self.assertAsRevisionId('null:', '0')
        self.assertAsRevisionId('r1', '1')
        self.assertAsRevisionId('r2', '2')
        self.assertAsRevisionId('r1', '-2')
        self.assertAsRevisionId('r2', '-1')
        self.assertAsRevisionId('alt_r2', '1.1.1')

    def test_as_tree(self):
        tree = self.get_as_tree('0')
        self.assertEquals(_mod_revision.NULL_REVISION, tree.get_revision_id())
        tree = self.get_as_tree('1')
        self.assertEquals('r1', tree.get_revision_id())
        tree = self.get_as_tree('2')
        self.assertEquals('r2', tree.get_revision_id())
        tree = self.get_as_tree('-2')
        self.assertEquals('r1', tree.get_revision_id())
        tree = self.get_as_tree('-1')
        self.assertEquals('r2', tree.get_revision_id())
        tree = self.get_as_tree('1.1.1')
        self.assertEquals('alt_r2', tree.get_revision_id())


class TestRevisionSpec_revid(TestRevisionSpec):
    
    def test_in_history(self):
        # We should be able to access revisions that are directly
        # in the history.
        self.assertInHistoryIs(1, 'r1', 'revid:r1')
        self.assertInHistoryIs(2, 'r2', 'revid:r2')
        
    def test_missing(self):
        self.assertInvalid('revid:r3', invalid_as_revision_id=False)

    def test_merged(self):
        """We can reach revisions in the ancestry"""
        self.assertInHistoryIs(None, 'alt_r2', 'revid:alt_r2')

    def test_not_here(self):
        self.tree2.commit('alt third', rev_id='alt_r3')
        # It exists in tree2, but not in tree
        self.assertInvalid('revid:alt_r3', invalid_as_revision_id=False)

    def test_in_repository(self):
        """We can get any revision id in the repository"""
        # XXX: This may change in the future, but for now, it is true
        self.tree2.commit('alt third', rev_id='alt_r3')
        self.tree.branch.repository.fetch(self.tree2.branch.repository,
                                          revision_id='alt_r3')
        self.assertInHistoryIs(None, 'alt_r3', 'revid:alt_r3')

    def test_unicode(self):
        """We correctly convert a unicode ui string to an encoded revid."""
        revision_id = u'\N{SNOWMAN}'.encode('utf-8')
        self.tree.commit('unicode', rev_id=revision_id)
        self.assertInHistoryIs(3, revision_id, u'revid:\N{SNOWMAN}')
        self.assertInHistoryIs(3, revision_id, 'revid:' + revision_id)

    def test_as_revision_id(self):
        self.assertAsRevisionId('r1', 'revid:r1')
        self.assertAsRevisionId('r2', 'revid:r2')
        self.assertAsRevisionId('alt_r2', 'revid:alt_r2')


class TestRevisionSpec_last(TestRevisionSpec):

    def test_positive(self):
        self.assertInHistoryIs(2, 'r2', 'last:1')
        self.assertInHistoryIs(1, 'r1', 'last:2')
        self.assertInHistoryIs(0, 'null:', 'last:3')

    def test_empty(self):
        self.assertInHistoryIs(2, 'r2', 'last:')

    def test_negative(self):
        self.assertInvalid('last:-1',
                           extra='\nyou must supply a positive value')

    def test_missing(self):
        self.assertInvalid('last:4')

    def test_no_history(self):
        tree = self.make_branch_and_tree('tree3')

        self.assertRaises(errors.NoCommits,
                          spec_in_history, 'last:', tree.branch)

    def test_not_a_number(self):
        try:
            int('Y')
        except ValueError, e:
            pass
        self.assertInvalid('last:Y', extra='\n' + str(e))

    def test_as_revision_id(self):
        self.assertAsRevisionId('r2', 'last:1')
        self.assertAsRevisionId('r1', 'last:2')


class TestRevisionSpec_before(TestRevisionSpec):

    def test_int(self):
        self.assertInHistoryIs(1, 'r1', 'before:2')
        self.assertInHistoryIs(1, 'r1', 'before:-1')

    def test_before_one(self):
        self.assertInHistoryIs(0, 'null:', 'before:1')

    def test_before_none(self):
        self.assertInvalid('before:0',
                           extra='\ncannot go before the null: revision')

    def test_revid(self):
        self.assertInHistoryIs(1, 'r1', 'before:revid:r2')

    def test_last(self):
        self.assertInHistoryIs(1, 'r1', 'before:last:1')

    def test_alt_revid(self):
        # This will grab the left-most ancestor for alternate histories
        self.assertInHistoryIs(1, 'r1', 'before:revid:alt_r2')

    def test_alt_no_parents(self):
        new_tree = self.make_branch_and_tree('new_tree')
        new_tree.commit('first', rev_id='new_r1')
        self.tree.branch.repository.fetch(new_tree.branch.repository,
                                          revision_id='new_r1')
        self.assertInHistoryIs(0, 'null:', 'before:revid:new_r1')

    def test_as_revision_id(self):
        self.assertAsRevisionId('r1', 'before:revid:r2')
        self.assertAsRevisionId('r1', 'before:2')
        self.assertAsRevisionId('r1', 'before:1.1.1')
        self.assertAsRevisionId('r1', 'before:revid:alt_r2')


class TestRevisionSpec_tag(TestRevisionSpec):
    
    def make_branch_and_tree(self, relpath):
        # override format as the default one may not support tags
        return TestRevisionSpec.make_branch_and_tree(
            self, relpath, format='dirstate-tags')

    def test_from_string_tag(self):
        spec = RevisionSpec.from_string('tag:bzr-0.14')
        self.assertIsInstance(spec, RevisionSpec_tag)
        self.assertEqual(spec.spec, 'bzr-0.14')

    def test_lookup_tag(self):
        self.tree.branch.tags.set_tag('bzr-0.14', 'r1')
        self.assertInHistoryIs(1, 'r1', 'tag:bzr-0.14')
        self.tree.branch.tags.set_tag('null_rev', 'null:')
        self.assertInHistoryIs(0, 'null:', 'tag:null_rev')

    def test_failed_lookup(self):
        # tags that don't exist give a specific message: arguably we should
        # just give InvalidRevisionSpec but I think this is more helpful
        self.assertRaises(errors.NoSuchTag,
            self.get_in_history,
            'tag:some-random-tag')

    def test_as_revision_id(self):
        self.tree.branch.tags.set_tag('my-tag', 'r2')
        self.tree.branch.tags.set_tag('null_rev', 'null:')
        self.assertAsRevisionId('r2', 'tag:my-tag')
        self.assertAsRevisionId('null:', 'tag:null_rev')
        self.assertAsRevisionId('r1', 'before:tag:my-tag')


class TestRevisionSpec_date(TestRevisionSpec):

    def setUp(self):
        super(TestRevisionSpec, self).setUp()

        new_tree = self.make_branch_and_tree('new_tree')
        new_tree.commit('Commit one', rev_id='new_r1',
                        timestamp=time.time() - 60*60*24)
        new_tree.commit('Commit two', rev_id='new_r2')
        new_tree.commit('Commit three', rev_id='new_r3')

        self.tree = new_tree

    def test_tomorrow(self):
        self.assertInvalid('date:tomorrow')

    def test_today(self):
        self.assertInHistoryIs(2, 'new_r2', 'date:today')
        self.assertInHistoryIs(1, 'new_r1', 'before:date:today')

    def test_yesterday(self):
        self.assertInHistoryIs(1, 'new_r1', 'date:yesterday')

    def test_invalid(self):
        self.assertInvalid('date:foobar', extra='\ninvalid date')
        # You must have '-' between year/month/day
        self.assertInvalid('date:20040404', extra='\ninvalid date')
        # Need 2 digits for each date piece
        self.assertInvalid('date:2004-4-4', extra='\ninvalid date')

    def test_day(self):
        now = datetime.datetime.now()
        self.assertInHistoryIs(2, 'new_r2',
            'date:%04d-%02d-%02d' % (now.year, now.month, now.day))

    def test_as_revision_id(self):
        self.assertAsRevisionId('new_r2', 'date:today')


class TestRevisionSpec_ancestor(TestRevisionSpec):
    
    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        self.assertRaises(errors.NotBranchError,
                          self.get_in_history, 'ancestor:tree2/a')

    def test_simple(self):
        # Common ancestor of trees is 'alt_r2'
        self.assertInHistoryIs(None, 'alt_r2', 'ancestor:tree2')

        # Going the other way, we get a valid revno
        tmp = self.tree
        self.tree = self.tree2
        self.tree2 = tmp
        self.assertInHistoryIs(2, 'alt_r2', 'ancestor:tree')

    def test_self(self):
        self.assertInHistoryIs(2, 'r2', 'ancestor:tree')

    def test_unrelated(self):
        new_tree = self.make_branch_and_tree('new_tree')

        new_tree.commit('Commit one', rev_id='new_r1')
        new_tree.commit('Commit two', rev_id='new_r2')
        new_tree.commit('Commit three', rev_id='new_r3')

        # With no common ancestor, we should raise another user error
        self.assertRaises(errors.NoCommonAncestor,
                          self.get_in_history, 'ancestor:new_tree')

    def test_no_commits(self):
        new_tree = self.make_branch_and_tree('new_tree')
        self.assertRaises(errors.NoCommits,
                          spec_in_history, 'ancestor:new_tree',
                                           self.tree.branch)
                        
        self.assertRaises(errors.NoCommits,
                          spec_in_history, 'ancestor:tree',
                                           new_tree.branch)

    def test_as_revision_id(self):
        self.assertAsRevisionId('alt_r2', 'ancestor:tree2')


class TestRevisionSpec_branch(TestRevisionSpec):
    
    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        self.assertRaises(errors.NotBranchError,
                          self.get_in_history, 'branch:tree2/a')

    def test_simple(self):
        self.assertInHistoryIs(None, 'alt_r2', 'branch:tree2')

    def test_self(self):
        self.assertInHistoryIs(2, 'r2', 'branch:tree')

    def test_unrelated(self):
        new_tree = self.make_branch_and_tree('new_tree')

        new_tree.commit('Commit one', rev_id='new_r1')
        new_tree.commit('Commit two', rev_id='new_r2')
        new_tree.commit('Commit three', rev_id='new_r3')

        self.assertInHistoryIs(None, 'new_r3', 'branch:new_tree')

        # XXX: Right now, we use fetch() to make sure the remote revisions
        # have been pulled into the local branch. We may change that
        # behavior in the future.
        self.failUnless(self.tree.branch.repository.has_revision('new_r3'))

    def test_no_commits(self):
        new_tree = self.make_branch_and_tree('new_tree')
        self.assertRaises(errors.NoCommits,
                          self.get_in_history, 'branch:new_tree')
        self.assertRaises(errors.NoCommits,
                          self.get_as_tree, 'branch:new_tree')

    def test_as_revision_id(self):
        self.assertAsRevisionId('alt_r2', 'branch:tree2')

    def test_as_tree(self):
        tree = self.get_as_tree('branch:tree', self.tree2)
        self.assertEquals('r2', tree.get_revision_id())
        self.assertFalse(self.tree2.branch.repository.has_revision('r2'))


class TestRevisionSpec_submit(TestRevisionSpec):

    def test_submit_branch(self):
        # Common ancestor of trees is 'alt_r2'
        self.assertRaises(errors.NoSubmitBranch, self.get_in_history,
                          'submit:')
        self.tree.branch.set_parent('../tree2')
        self.assertInHistoryIs(None, 'alt_r2', 'submit:')
        self.tree.branch.set_parent('bogus')
        self.assertRaises(errors.NotBranchError, self.get_in_history,
            'submit:')
        # submit branch overrides parent branch
        self.tree.branch.set_submit_branch('tree2')
        self.assertInHistoryIs(None, 'alt_r2', 'submit:')

    def test_as_revision_id(self):
        self.tree.branch.set_submit_branch('tree2')
        self.assertAsRevisionId('alt_r2', 'branch:tree2')
