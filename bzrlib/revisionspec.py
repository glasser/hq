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


import re

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import bisect
import datetime
""")

from bzrlib import (
    errors,
    osutils,
    revision,
    symbol_versioning,
    trace,
    )


_marker = []


class RevisionInfo(object):
    """The results of applying a revision specification to a branch."""

    help_txt = """The results of applying a revision specification to a branch.

    An instance has two useful attributes: revno, and rev_id.

    They can also be accessed as spec[0] and spec[1] respectively,
    so that you can write code like:
    revno, rev_id = RevisionSpec(branch, spec)
    although this is probably going to be deprecated later.

    This class exists mostly to be the return value of a RevisionSpec,
    so that you can access the member you're interested in (number or id)
    or treat the result as a tuple.
    """

    def __init__(self, branch, revno, rev_id=_marker):
        self.branch = branch
        self.revno = revno
        if rev_id is _marker:
            # allow caller to be lazy
            if self.revno is None:
                self.rev_id = None
            else:
                self.rev_id = branch.get_rev_id(self.revno)
        else:
            self.rev_id = rev_id

    def __nonzero__(self):
        # first the easy ones...
        if self.rev_id is None:
            return False
        if self.revno is not None:
            return True
        # TODO: otherwise, it should depend on how I was built -
        # if it's in_history(branch), then check revision_history(),
        # if it's in_store(branch), do the check below
        return self.branch.repository.has_revision(self.rev_id)

    def __len__(self):
        return 2

    def __getitem__(self, index):
        if index == 0: return self.revno
        if index == 1: return self.rev_id
        raise IndexError(index)

    def get(self):
        return self.branch.repository.get_revision(self.rev_id)

    def __eq__(self, other):
        if type(other) not in (tuple, list, type(self)):
            return False
        if type(other) is type(self) and self.branch is not other.branch:
            return False
        return tuple(self) == tuple(other)

    def __repr__(self):
        return '<bzrlib.revisionspec.RevisionInfo object %s, %s for %r>' % (
            self.revno, self.rev_id, self.branch)

    @staticmethod
    def from_revision_id(branch, revision_id, revs):
        """Construct a RevisionInfo given just the id.

        Use this if you don't know or care what the revno is.
        """
        if revision_id == revision.NULL_REVISION:
            return RevisionInfo(branch, 0, revision_id)
        try:
            revno = revs.index(revision_id) + 1
        except ValueError:
            revno = None
        return RevisionInfo(branch, revno, revision_id)


# classes in this list should have a "prefix" attribute, against which
# string specs are matched
SPEC_TYPES = []
_revno_regex = None


class RevisionSpec(object):
    """A parsed revision specification."""

    help_txt = """A parsed revision specification.

    A revision specification can be an integer, in which case it is
    assumed to be a revno (though this will translate negative values
    into positive ones); or it can be a string, in which case it is
    parsed for something like 'date:' or 'revid:' etc.

    Revision specs are an UI element, and they have been moved out
    of the branch class to leave "back-end" classes unaware of such
    details.  Code that gets a revno or rev_id from other code should
    not be using revision specs - revnos and revision ids are the
    accepted ways to refer to revisions internally.

    (Equivalent to the old Branch method get_revision_info())
    """

    prefix = None
    wants_revision_history = True

    @staticmethod
    def from_string(spec):
        """Parse a revision spec string into a RevisionSpec object.

        :param spec: A string specified by the user
        :return: A RevisionSpec object that understands how to parse the
            supplied notation.
        """
        if not isinstance(spec, (type(None), basestring)):
            raise TypeError('error')

        if spec is None:
            return RevisionSpec(None, _internal=True)
        for spectype in SPEC_TYPES:
            if spec.startswith(spectype.prefix):
                trace.mutter('Returning RevisionSpec %s for %s',
                             spectype.__name__, spec)
                return spectype(spec, _internal=True)
        else:
            # RevisionSpec_revno is special cased, because it is the only
            # one that directly handles plain integers
            # TODO: This should not be special cased rather it should be
            # a method invocation on spectype.canparse()
            global _revno_regex
            if _revno_regex is None:
                _revno_regex = re.compile(r'^(?:(\d+(\.\d+)*)|-\d+)(:.*)?$')
            if _revno_regex.match(spec) is not None:
                return RevisionSpec_revno(spec, _internal=True)

            raise errors.NoSuchRevisionSpec(spec)

    def __init__(self, spec, _internal=False):
        """Create a RevisionSpec referring to the Null revision.

        :param spec: The original spec supplied by the user
        :param _internal: Used to ensure that RevisionSpec is not being
            called directly. Only from RevisionSpec.from_string()
        """
        if not _internal:
            # XXX: Update this after 0.10 is released
            symbol_versioning.warn('Creating a RevisionSpec directly has'
                                   ' been deprecated in version 0.11. Use'
                                   ' RevisionSpec.from_string()'
                                   ' instead.',
                                   DeprecationWarning, stacklevel=2)
        self.user_spec = spec
        if self.prefix and spec.startswith(self.prefix):
            spec = spec[len(self.prefix):]
        self.spec = spec

    def _match_on(self, branch, revs):
        trace.mutter('Returning RevisionSpec._match_on: None')
        return RevisionInfo(branch, None, None)

    def _match_on_and_check(self, branch, revs):
        info = self._match_on(branch, revs)
        if info:
            return info
        elif info == (None, None):
            # special case - nothing supplied
            return info
        elif self.prefix:
            raise errors.InvalidRevisionSpec(self.user_spec, branch)
        else:
            raise errors.InvalidRevisionSpec(self.spec, branch)

    def in_history(self, branch):
        if branch:
            if self.wants_revision_history:
                revs = branch.revision_history()
            else:
                revs = None
        else:
            # this should never trigger.
            # TODO: make it a deprecated code path. RBC 20060928
            revs = None
        return self._match_on_and_check(branch, revs)

        # FIXME: in_history is somewhat broken,
        # it will return non-history revisions in many
        # circumstances. The expected facility is that
        # in_history only returns revision-history revs,
        # in_store returns any rev. RBC 20051010
    # aliases for now, when we fix the core logic, then they
    # will do what you expect.
    in_store = in_history
    in_branch = in_store

    def as_revision_id(self, context_branch):
        """Return just the revision_id for this revisions spec.

        Some revision specs require a context_branch to be able to determine
        their value. Not all specs will make use of it.
        """
        return self._as_revision_id(context_branch)

    def _as_revision_id(self, context_branch):
        """Implementation of as_revision_id()

        Classes should override this function to provide appropriate
        functionality. The default is to just call '.in_history().rev_id'
        """
        return self.in_history(context_branch).rev_id

    def as_tree(self, context_branch):
        """Return the tree object for this revisions spec.

        Some revision specs require a context_branch to be able to determine
        the revision id and access the repository. Not all specs will make
        use of it.
        """
        return self._as_tree(context_branch)

    def _as_tree(self, context_branch):
        """Implementation of as_tree().

        Classes should override this function to provide appropriate
        functionality. The default is to just call '.as_revision_id()'
        and get the revision tree from context_branch's repository.
        """
        revision_id = self.as_revision_id(context_branch)
        return context_branch.repository.revision_tree(revision_id)

    def __repr__(self):
        # this is mostly for helping with testing
        return '<%s %s>' % (self.__class__.__name__,
                              self.user_spec)
    
    def needs_branch(self):
        """Whether this revision spec needs a branch.

        Set this to False the branch argument of _match_on is not used.
        """
        return True

    def get_branch(self):
        """When the revision specifier contains a branch location, return it.
        
        Otherwise, return None.
        """
        return None


# private API

class RevisionSpec_revno(RevisionSpec):
    """Selects a revision using a number."""

    help_txt = """Selects a revision using a number.

    Use an integer to specify a revision in the history of the branch.
    Optionally a branch can be specified. The 'revno:' prefix is optional.
    A negative number will count from the end of the branch (-1 is the
    last revision, -2 the previous one). If the negative number is larger
    than the branch's history, the first revision is returned.
    Examples::

      revno:1                   -> return the first revision of this branch
      revno:3:/path/to/branch   -> return the 3rd revision of
                                   the branch '/path/to/branch'
      revno:-1                  -> The last revision in a branch.
      -2:http://other/branch    -> The second to last revision in the
                                   remote branch.
      -1000000                  -> Most likely the first revision, unless
                                   your history is very long.
    """
    prefix = 'revno:'
    wants_revision_history = False

    def _match_on(self, branch, revs):
        """Lookup a revision by revision number"""
        branch, revno, revision_id = self._lookup(branch, revs)
        return RevisionInfo(branch, revno, revision_id)

    def _lookup(self, branch, revs_or_none):
        loc = self.spec.find(':')
        if loc == -1:
            revno_spec = self.spec
            branch_spec = None
        else:
            revno_spec = self.spec[:loc]
            branch_spec = self.spec[loc+1:]

        if revno_spec == '':
            if not branch_spec:
                raise errors.InvalidRevisionSpec(self.user_spec,
                        branch, 'cannot have an empty revno and no branch')
            revno = None
        else:
            try:
                revno = int(revno_spec)
                dotted = False
            except ValueError:
                # dotted decimal. This arguably should not be here
                # but the from_string method is a little primitive 
                # right now - RBC 20060928
                try:
                    match_revno = tuple((int(number) for number in revno_spec.split('.')))
                except ValueError, e:
                    raise errors.InvalidRevisionSpec(self.user_spec, branch, e)

                dotted = True

        if branch_spec:
            # the user has override the branch to look in.
            # we need to refresh the revision_history map and
            # the branch object.
            from bzrlib.branch import Branch
            branch = Branch.open(branch_spec)
            revs_or_none = None

        if dotted:
            branch.lock_read()
            try:
                revision_id_to_revno = branch.get_revision_id_to_revno_map()
                revisions = [revision_id for revision_id, revno
                             in revision_id_to_revno.iteritems()
                             if revno == match_revno]
            finally:
                branch.unlock()
            if len(revisions) != 1:
                return branch, None, None
            else:
                # there is no traditional 'revno' for dotted-decimal revnos.
                # so for  API compatability we return None.
                return branch, None, revisions[0]
        else:
            last_revno, last_revision_id = branch.last_revision_info()
            if revno < 0:
                # if get_rev_id supported negative revnos, there would not be a
                # need for this special case.
                if (-revno) >= last_revno:
                    revno = 1
                else:
                    revno = last_revno + revno + 1
            try:
                revision_id = branch.get_rev_id(revno, revs_or_none)
            except errors.NoSuchRevision:
                raise errors.InvalidRevisionSpec(self.user_spec, branch)
        return branch, revno, revision_id

    def _as_revision_id(self, context_branch):
        # We would have the revno here, but we don't really care
        branch, revno, revision_id = self._lookup(context_branch, None)
        return revision_id

    def needs_branch(self):
        return self.spec.find(':') == -1

    def get_branch(self):
        if self.spec.find(':') == -1:
            return None
        else:
            return self.spec[self.spec.find(':')+1:]

# Old compatibility 
RevisionSpec_int = RevisionSpec_revno

SPEC_TYPES.append(RevisionSpec_revno)


class RevisionSpec_revid(RevisionSpec):
    """Selects a revision using the revision id."""

    help_txt = """Selects a revision using the revision id.

    Supply a specific revision id, that can be used to specify any
    revision id in the ancestry of the branch. 
    Including merges, and pending merges.
    Examples::

      revid:aaaa@bbbb-123456789 -> Select revision 'aaaa@bbbb-123456789'
    """

    prefix = 'revid:'

    def _match_on(self, branch, revs):
        # self.spec comes straight from parsing the command line arguments,
        # so we expect it to be a Unicode string. Switch it to the internal
        # representation.
        revision_id = osutils.safe_revision_id(self.spec, warn=False)
        return RevisionInfo.from_revision_id(branch, revision_id, revs)

    def _as_revision_id(self, context_branch):
        return osutils.safe_revision_id(self.spec, warn=False)

SPEC_TYPES.append(RevisionSpec_revid)


class RevisionSpec_last(RevisionSpec):
    """Selects the nth revision from the end."""

    help_txt = """Selects the nth revision from the end.

    Supply a positive number to get the nth revision from the end.
    This is the same as supplying negative numbers to the 'revno:' spec.
    Examples::

      last:1        -> return the last revision
      last:3        -> return the revision 2 before the end.
    """

    prefix = 'last:'

    def _match_on(self, branch, revs):
        revno, revision_id = self._revno_and_revision_id(branch, revs)
        return RevisionInfo(branch, revno, revision_id)

    def _revno_and_revision_id(self, context_branch, revs_or_none):
        last_revno, last_revision_id = context_branch.last_revision_info()

        if self.spec == '':
            if not last_revno:
                raise errors.NoCommits(context_branch)
            return last_revno, last_revision_id

        try:
            offset = int(self.spec)
        except ValueError, e:
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch, e)

        if offset <= 0:
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch,
                                             'you must supply a positive value')

        revno = last_revno - offset + 1
        try:
            revision_id = context_branch.get_rev_id(revno, revs_or_none)
        except errors.NoSuchRevision:
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch)
        return revno, revision_id

    def _as_revision_id(self, context_branch):
        # We compute the revno as part of the process, but we don't really care
        # about it.
        revno, revision_id = self._revno_and_revision_id(context_branch, None)
        return revision_id

SPEC_TYPES.append(RevisionSpec_last)


class RevisionSpec_before(RevisionSpec):
    """Selects the parent of the revision specified."""

    help_txt = """Selects the parent of the revision specified.

    Supply any revision spec to return the parent of that revision.  This is
    mostly useful when inspecting revisions that are not in the revision history
    of a branch.

    It is an error to request the parent of the null revision (before:0).

    Examples::

      before:1913    -> Return the parent of revno 1913 (revno 1912)
      before:revid:aaaa@bbbb-1234567890  -> return the parent of revision
                                            aaaa@bbbb-1234567890
      bzr diff -r before:1913..1913
            -> Find the changes between revision 1913 and its parent (1912).
               (What changes did revision 1913 introduce).
               This is equivalent to:  bzr diff -c 1913
    """

    prefix = 'before:'
    
    def _match_on(self, branch, revs):
        r = RevisionSpec.from_string(self.spec)._match_on(branch, revs)
        if r.revno == 0:
            raise errors.InvalidRevisionSpec(self.user_spec, branch,
                                         'cannot go before the null: revision')
        if r.revno is None:
            # We need to use the repository history here
            rev = branch.repository.get_revision(r.rev_id)
            if not rev.parent_ids:
                revno = 0
                revision_id = revision.NULL_REVISION
            else:
                revision_id = rev.parent_ids[0]
                try:
                    revno = revs.index(revision_id) + 1
                except ValueError:
                    revno = None
        else:
            revno = r.revno - 1
            try:
                revision_id = branch.get_rev_id(revno, revs)
            except errors.NoSuchRevision:
                raise errors.InvalidRevisionSpec(self.user_spec,
                                                 branch)
        return RevisionInfo(branch, revno, revision_id)

    def _as_revision_id(self, context_branch):
        base_revspec = RevisionSpec.from_string(self.spec)
        base_revision_id = base_revspec.as_revision_id(context_branch)
        if base_revision_id == revision.NULL_REVISION:
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch,
                                         'cannot go before the null: revision')
        context_repo = context_branch.repository
        context_repo.lock_read()
        try:
            parent_map = context_repo.get_parent_map([base_revision_id])
        finally:
            context_repo.unlock()
        if base_revision_id not in parent_map:
            # Ghost, or unknown revision id
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch,
                'cannot find the matching revision')
        parents = parent_map[base_revision_id]
        if len(parents) < 1:
            raise errors.InvalidRevisionSpec(self.user_spec, context_branch,
                'No parents for revision.')
        return parents[0]

SPEC_TYPES.append(RevisionSpec_before)


class RevisionSpec_tag(RevisionSpec):
    """Select a revision identified by tag name"""

    help_txt = """Selects a revision identified by a tag name.

    Tags are stored in the branch and created by the 'tag' command.
    """

    prefix = 'tag:'

    def _match_on(self, branch, revs):
        # Can raise tags not supported, NoSuchTag, etc
        return RevisionInfo.from_revision_id(branch,
            branch.tags.lookup_tag(self.spec),
            revs)

    def _as_revision_id(self, context_branch):
        return context_branch.tags.lookup_tag(self.spec)

SPEC_TYPES.append(RevisionSpec_tag)


class _RevListToTimestamps(object):
    """This takes a list of revisions, and allows you to bisect by date"""

    __slots__ = ['revs', 'branch']

    def __init__(self, revs, branch):
        self.revs = revs
        self.branch = branch

    def __getitem__(self, index):
        """Get the date of the index'd item"""
        r = self.branch.repository.get_revision(self.revs[index])
        # TODO: Handle timezone.
        return datetime.datetime.fromtimestamp(r.timestamp)

    def __len__(self):
        return len(self.revs)


class RevisionSpec_date(RevisionSpec):
    """Selects a revision on the basis of a datestamp."""

    help_txt = """Selects a revision on the basis of a datestamp.

    Supply a datestamp to select the first revision that matches the date.
    Date can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
    Matches the first entry after a given date (either at midnight or
    at a specified time).

    One way to display all the changes since yesterday would be::

        bzr log -r date:yesterday..

    Examples::

      date:yesterday            -> select the first revision since yesterday
      date:2006-08-14,17:10:14  -> select the first revision after
                                   August 14th, 2006 at 5:10pm.
    """    
    prefix = 'date:'
    _date_re = re.compile(
            r'(?P<date>(?P<year>\d\d\d\d)-(?P<month>\d\d)-(?P<day>\d\d))?'
            r'(,|T)?\s*'
            r'(?P<time>(?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d))?)?'
        )

    def _match_on(self, branch, revs):
        """Spec for date revisions:
          date:value
          value can be 'yesterday', 'today', 'tomorrow' or a YYYY-MM-DD string.
          matches the first entry after a given date (either at midnight or
          at a specified time).
        """
        #  XXX: This doesn't actually work
        #  So the proper way of saying 'give me all entries for today' is:
        #      -r date:yesterday..date:today
        today = datetime.datetime.fromordinal(datetime.date.today().toordinal())
        if self.spec.lower() == 'yesterday':
            dt = today - datetime.timedelta(days=1)
        elif self.spec.lower() == 'today':
            dt = today
        elif self.spec.lower() == 'tomorrow':
            dt = today + datetime.timedelta(days=1)
        else:
            m = self._date_re.match(self.spec)
            if not m or (not m.group('date') and not m.group('time')):
                raise errors.InvalidRevisionSpec(self.user_spec,
                                                 branch, 'invalid date')

            try:
                if m.group('date'):
                    year = int(m.group('year'))
                    month = int(m.group('month'))
                    day = int(m.group('day'))
                else:
                    year = today.year
                    month = today.month
                    day = today.day

                if m.group('time'):
                    hour = int(m.group('hour'))
                    minute = int(m.group('minute'))
                    if m.group('second'):
                        second = int(m.group('second'))
                    else:
                        second = 0
                else:
                    hour, minute, second = 0,0,0
            except ValueError:
                raise errors.InvalidRevisionSpec(self.user_spec,
                                                 branch, 'invalid date')

            dt = datetime.datetime(year=year, month=month, day=day,
                    hour=hour, minute=minute, second=second)
        branch.lock_read()
        try:
            rev = bisect.bisect(_RevListToTimestamps(revs, branch), dt)
        finally:
            branch.unlock()
        if rev == len(revs):
            raise errors.InvalidRevisionSpec(self.user_spec, branch)
        else:
            return RevisionInfo(branch, rev + 1)

SPEC_TYPES.append(RevisionSpec_date)


class RevisionSpec_ancestor(RevisionSpec):
    """Selects a common ancestor with a second branch."""

    help_txt = """Selects a common ancestor with a second branch.

    Supply the path to a branch to select the common ancestor.

    The common ancestor is the last revision that existed in both
    branches. Usually this is the branch point, but it could also be
    a revision that was merged.

    This is frequently used with 'diff' to return all of the changes
    that your branch introduces, while excluding the changes that you
    have not merged from the remote branch.

    Examples::

      ancestor:/path/to/branch
      $ bzr diff -r ancestor:../../mainline/branch
    """
    prefix = 'ancestor:'

    def _match_on(self, branch, revs):
        trace.mutter('matching ancestor: on: %s, %s', self.spec, branch)
        return self._find_revision_info(branch, self.spec)

    def _as_revision_id(self, context_branch):
        return self._find_revision_id(context_branch, self.spec)

    @staticmethod
    def _find_revision_info(branch, other_location):
        revision_id = RevisionSpec_ancestor._find_revision_id(branch,
                                                              other_location)
        try:
            revno = branch.revision_id_to_revno(revision_id)
        except errors.NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, revision_id)

    @staticmethod
    def _find_revision_id(branch, other_location):
        from bzrlib.branch import Branch

        branch.lock_read()
        try:
            revision_a = revision.ensure_null(branch.last_revision())
            if revision_a == revision.NULL_REVISION:
                raise errors.NoCommits(branch)
            other_branch = Branch.open(other_location)
            other_branch.lock_read()
            try:
                revision_b = revision.ensure_null(other_branch.last_revision())
                if revision_b == revision.NULL_REVISION:
                    raise errors.NoCommits(other_branch)
                graph = branch.repository.get_graph(other_branch.repository)
                rev_id = graph.find_unique_lca(revision_a, revision_b)
            finally:
                other_branch.unlock()
            if rev_id == revision.NULL_REVISION:
                raise errors.NoCommonAncestor(revision_a, revision_b)
            return rev_id
        finally:
            branch.unlock()


SPEC_TYPES.append(RevisionSpec_ancestor)


class RevisionSpec_branch(RevisionSpec):
    """Selects the last revision of a specified branch."""

    help_txt = """Selects the last revision of a specified branch.

    Supply the path to a branch to select its last revision.

    Examples::

      branch:/path/to/branch
    """
    prefix = 'branch:'

    def _match_on(self, branch, revs):
        from bzrlib.branch import Branch
        other_branch = Branch.open(self.spec)
        revision_b = other_branch.last_revision()
        if revision_b in (None, revision.NULL_REVISION):
            raise errors.NoCommits(other_branch)
        # pull in the remote revisions so we can diff
        branch.fetch(other_branch, revision_b)
        try:
            revno = branch.revision_id_to_revno(revision_b)
        except errors.NoSuchRevision:
            revno = None
        return RevisionInfo(branch, revno, revision_b)

    def _as_revision_id(self, context_branch):
        from bzrlib.branch import Branch
        other_branch = Branch.open(self.spec)
        last_revision = other_branch.last_revision()
        last_revision = revision.ensure_null(last_revision)
        context_branch.fetch(other_branch, last_revision)
        if last_revision == revision.NULL_REVISION:
            raise errors.NoCommits(other_branch)
        return last_revision

    def _as_tree(self, context_branch):
        from bzrlib.branch import Branch
        other_branch = Branch.open(self.spec)
        last_revision = other_branch.last_revision()
        last_revision = revision.ensure_null(last_revision)
        if last_revision == revision.NULL_REVISION:
            raise errors.NoCommits(other_branch)
        return other_branch.repository.revision_tree(last_revision)

SPEC_TYPES.append(RevisionSpec_branch)


class RevisionSpec_submit(RevisionSpec_ancestor):
    """Selects a common ancestor with a submit branch."""

    help_txt = """Selects a common ancestor with the submit branch.

    Diffing against this shows all the changes that were made in this branch,
    and is a good predictor of what merge will do.  The submit branch is
    used by the bundle and merge directive commands.  If no submit branch
    is specified, the parent branch is used instead.

    The common ancestor is the last revision that existed in both
    branches. Usually this is the branch point, but it could also be
    a revision that was merged.

    Examples::

      $ bzr diff -r submit:
    """

    prefix = 'submit:'

    def _get_submit_location(self, branch):
        submit_location = branch.get_submit_branch()
        location_type = 'submit branch'
        if submit_location is None:
            submit_location = branch.get_parent()
            location_type = 'parent branch'
        if submit_location is None:
            raise errors.NoSubmitBranch(branch)
        trace.note('Using %s %s', location_type, submit_location)
        return submit_location

    def _match_on(self, branch, revs):
        trace.mutter('matching ancestor: on: %s, %s', self.spec, branch)
        return self._find_revision_info(branch,
            self._get_submit_location(branch))

    def _as_revision_id(self, context_branch):
        return self._find_revision_id(context_branch,
            self._get_submit_location(context_branch))


SPEC_TYPES.append(RevisionSpec_submit)
