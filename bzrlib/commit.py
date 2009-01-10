# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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


# The newly committed revision is going to have a shape corresponding
# to that of the working tree.  Files that are not in the
# working tree and that were in the predecessor are reported as
# removed --- this can include files that were either removed from the
# inventory or deleted in the working tree.  If they were only
# deleted from disk, they are removed from the working inventory.

# We then consider the remaining entries, which will be in the new
# version.  Directory entries are simply copied across.  File entries
# must be checked to see if a new version of the file should be
# recorded.  For each parent revision tree, we check to see what
# version of the file was present.  If the file was present in at
# least one tree, and if it was the same version in all the trees,
# then we can just refer to that version.  Otherwise, a new version
# representing the merger of the file versions must be added.

# TODO: Update hashcache before and after - or does the WorkingTree
# look after that?

# TODO: Rather than mashing together the ancestry and storing it back,
# perhaps the weave should have single method which does it all in one
# go, avoiding a lot of redundant work.

# TODO: Perhaps give a warning if one of the revisions marked as
# merged is already in the ancestry, and then don't record it as a
# distinct parent.

# TODO: If the file is newly merged but unchanged from the version it
# merges from, then it should still be reported as newly added
# relative to the basis revision.

# TODO: Change the parameter 'rev_id' to 'revision_id' to be consistent with
# the rest of the code; add a deprecation of the old name.

import os
import re
import sys
import time

from cStringIO import StringIO

from bzrlib import (
    debug,
    errors,
    revision,
    trace,
    tree,
    )
from bzrlib.branch import Branch
import bzrlib.config
from bzrlib.errors import (BzrError, PointlessCommit,
                           ConflictsInTree,
                           StrictCommitFailed
                           )
from bzrlib.osutils import (get_user_encoding,
                            kind_marker, isdir,isfile, is_inside_any,
                            is_inside_or_parent_of_any,
                            minimum_path_selection,
                            quotefn, sha_file, split_lines,
                            splitpath,
                            )
from bzrlib.testament import Testament
from bzrlib.trace import mutter, note, warning, is_quiet
from bzrlib.inventory import Inventory, InventoryEntry, make_entry
from bzrlib import symbol_versioning
from bzrlib.symbol_versioning import (deprecated_passed,
        deprecated_function,
        DEPRECATED_PARAMETER)
from bzrlib.workingtree import WorkingTree
from bzrlib.urlutils import unescape_for_display
import bzrlib.ui


class NullCommitReporter(object):
    """I report on progress of a commit."""

    def started(self, revno, revid, location=None):
        if location is None:
            symbol_versioning.warn("As of bzr 1.0 you must pass a location "
                                   "to started.", DeprecationWarning,
                                   stacklevel=2)
        pass

    def snapshot_change(self, change, path):
        pass

    def completed(self, revno, rev_id):
        pass

    def deleted(self, file_id):
        pass

    def escaped(self, escape_count, message):
        pass

    def missing(self, path):
        pass

    def renamed(self, change, old_path, new_path):
        pass

    def is_verbose(self):
        return False


class ReportCommitToLog(NullCommitReporter):

    def _note(self, format, *args):
        """Output a message.

        Subclasses may choose to override this method.
        """
        note(format, *args)

    def snapshot_change(self, change, path):
        if change == 'unchanged':
            return
        if change == 'added' and path == '':
            return
        self._note("%s %s", change, path)

    def started(self, revno, rev_id, location=None):
        if location is not None:
            location = ' to: ' + unescape_for_display(location, 'utf-8')
        else:
            # When started was added, location was only made optional by
            # accident.  Matt Nordhoff 20071129
            symbol_versioning.warn("As of bzr 1.0 you must pass a location "
                                   "to started.", DeprecationWarning,
                                   stacklevel=2)
            location = ''
        self._note('Committing%s', location)

    def completed(self, revno, rev_id):
        self._note('Committed revision %d.', revno)

    def deleted(self, file_id):
        self._note('deleted %s', file_id)

    def escaped(self, escape_count, message):
        self._note("replaced %d control characters in message", escape_count)

    def missing(self, path):
        self._note('missing %s', path)

    def renamed(self, change, old_path, new_path):
        self._note('%s %s => %s', change, old_path, new_path)

    def is_verbose(self):
        return True


class Commit(object):
    """Task of committing a new revision.

    This is a MethodObject: it accumulates state as the commit is
    prepared, and then it is discarded.  It doesn't represent
    historical revisions, just the act of recording a new one.

            missing_ids
            Modified to hold a list of files that have been deleted from
            the working directory; these should be removed from the
            working inventory.
    """
    def __init__(self,
                 reporter=None,
                 config=None):
        """Create a Commit object.

        :param reporter: the default reporter to use or None to decide later
        """
        self.reporter = reporter
        self.config = config

    def commit(self,
               message=None,
               timestamp=None,
               timezone=None,
               committer=None,
               specific_files=None,
               rev_id=None,
               allow_pointless=True,
               strict=False,
               verbose=False,
               revprops=None,
               working_tree=None,
               local=False,
               reporter=None,
               config=None,
               message_callback=None,
               recursive='down',
               exclude=None,
               possible_master_transports=None):
        """Commit working copy as a new revision.

        :param message: the commit message (it or message_callback is required)

        :param timestamp: if not None, seconds-since-epoch for a
            postdated/predated commit.

        :param specific_files: If true, commit only those files.

        :param rev_id: If set, use this as the new revision id.
            Useful for test or import commands that need to tightly
            control what revisions are assigned.  If you duplicate
            a revision id that exists elsewhere it is your own fault.
            If null (default), a time/random revision id is generated.

        :param allow_pointless: If true (default), commit even if nothing
            has changed and no merges are recorded.

        :param strict: If true, don't allow a commit if the working tree
            contains unknown files.

        :param revprops: Properties for new revision
        :param local: Perform a local only commit.
        :param reporter: the reporter to use or None for the default
        :param verbose: if True and the reporter is not None, report everything
        :param recursive: If set to 'down', commit in any subtrees that have
            pending changes of any sort during this commit.
        :param exclude: None or a list of relative paths to exclude from the
            commit. Pending changes to excluded files will be ignored by the
            commit. 
        """
        mutter('preparing to commit')

        if working_tree is None:
            raise BzrError("working_tree must be passed into commit().")
        else:
            self.work_tree = working_tree
            self.branch = self.work_tree.branch
            if getattr(self.work_tree, 'requires_rich_root', lambda: False)():
                if not self.branch.repository.supports_rich_root():
                    raise errors.RootNotRich()
        if message_callback is None:
            if message is not None:
                if isinstance(message, str):
                    message = message.decode(get_user_encoding())
                message_callback = lambda x: message
            else:
                raise BzrError("The message or message_callback keyword"
                               " parameter is required for commit().")

        self.bound_branch = None
        self.any_entries_changed = False
        self.any_entries_deleted = False
        if exclude is not None:
            self.exclude = sorted(
                minimum_path_selection(exclude))
        else:
            self.exclude = []
        self.local = local
        self.master_branch = None
        self.master_locked = False
        self.recursive = recursive
        self.rev_id = None
        if specific_files is not None:
            self.specific_files = sorted(
                minimum_path_selection(specific_files))
        else:
            self.specific_files = None
        self.specific_file_ids = None
        self.allow_pointless = allow_pointless
        self.revprops = revprops
        self.message_callback = message_callback
        self.timestamp = timestamp
        self.timezone = timezone
        self.committer = committer
        self.strict = strict
        self.verbose = verbose
        # accumulates an inventory delta to the basis entry, so we can make
        # just the necessary updates to the workingtree's cached basis.
        self._basis_delta = []

        self.work_tree.lock_write()
        self.pb = bzrlib.ui.ui_factory.nested_progress_bar()
        self.basis_revid = self.work_tree.last_revision()
        self.basis_tree = self.work_tree.basis_tree()
        self.basis_tree.lock_read()
        try:
            # Cannot commit with conflicts present.
            if len(self.work_tree.conflicts()) > 0:
                raise ConflictsInTree

            # Setup the bound branch variables as needed.
            self._check_bound_branch(possible_master_transports)

            # Check that the working tree is up to date
            old_revno, new_revno = self._check_out_of_date_tree()

            # Complete configuration setup
            if reporter is not None:
                self.reporter = reporter
            elif self.reporter is None:
                self.reporter = self._select_reporter()
            if self.config is None:
                self.config = self.branch.get_config()

            # If provided, ensure the specified files are versioned
            if self.specific_files is not None:
                # Note: This routine is being called because it raises
                # PathNotVersionedError as a side effect of finding the IDs. We
                # later use the ids we found as input to the working tree
                # inventory iterator, so we only consider those ids rather than
                # examining the whole tree again.
                # XXX: Dont we have filter_unversioned to do this more
                # cheaply?
                self.specific_file_ids = tree.find_ids_across_trees(
                    specific_files, [self.basis_tree, self.work_tree])

            # Setup the progress bar. As the number of files that need to be
            # committed in unknown, progress is reported as stages.
            # We keep track of entries separately though and include that
            # information in the progress bar during the relevant stages.
            self.pb_stage_name = ""
            self.pb_stage_count = 0
            self.pb_stage_total = 5
            if self.bound_branch:
                self.pb_stage_total += 1
            self.pb.show_pct = False
            self.pb.show_spinner = False
            self.pb.show_eta = False
            self.pb.show_count = True
            self.pb.show_bar = True

            self.basis_inv = self.basis_tree.inventory
            self._gather_parents()
            # After a merge, a selected file commit is not supported.
            # See 'bzr help merge' for an explanation as to why.
            if len(self.parents) > 1 and self.specific_files:
                raise errors.CannotCommitSelectedFileMerge(self.specific_files)
            # Excludes are a form of selected file commit.
            if len(self.parents) > 1 and self.exclude:
                raise errors.CannotCommitSelectedFileMerge(self.exclude)

            # Collect the changes
            self._set_progress_stage("Collecting changes",
                    entries_title="Directory")
            self.builder = self.branch.get_commit_builder(self.parents,
                self.config, timestamp, timezone, committer, revprops, rev_id)
            
            try:
                # find the location being committed to
                if self.bound_branch:
                    master_location = self.master_branch.base
                else:
                    master_location = self.branch.base

                # report the start of the commit
                self.reporter.started(new_revno, self.rev_id, master_location)

                self._update_builder_with_changes()
                self._report_and_accumulate_deletes()
                self._check_pointless()

                # TODO: Now the new inventory is known, check for conflicts.
                # ADHB 2006-08-08: If this is done, populate_new_inv should not add
                # weave lines, because nothing should be recorded until it is known
                # that commit will succeed.
                self._set_progress_stage("Saving data locally")
                self.builder.finish_inventory()

                # Prompt the user for a commit message if none provided
                message = message_callback(self)
                self.message = message
                self._escape_commit_message()

                # Add revision data to the local branch
                self.rev_id = self.builder.commit(self.message)

            except Exception, e:
                mutter("aborting commit write group because of exception:")
                trace.log_exception_quietly()
                note("aborting commit write group: %r" % (e,))
                self.builder.abort()
                raise

            self._process_pre_hooks(old_revno, new_revno)

            # Upload revision data to the master.
            # this will propagate merged revisions too if needed.
            if self.bound_branch:
                if not self.master_branch.repository.has_same_location(
                        self.branch.repository):
                    self._set_progress_stage("Uploading data to master branch")
                    self.master_branch.repository.fetch(self.branch.repository,
                        revision_id=self.rev_id)
                # now the master has the revision data
                # 'commit' to the master first so a timeout here causes the
                # local branch to be out of date
                self.master_branch.set_last_revision_info(new_revno,
                                                          self.rev_id)

            # and now do the commit locally.
            self.branch.set_last_revision_info(new_revno, self.rev_id)

            # Make the working tree up to date with the branch
            self._set_progress_stage("Updating the working tree")
            self.work_tree.update_basis_by_delta(self.rev_id,
                 self._basis_delta)
            self.reporter.completed(new_revno, self.rev_id)
            self._process_post_hooks(old_revno, new_revno)
        finally:
            self._cleanup()
        return self.rev_id

    def _select_reporter(self):
        """Select the CommitReporter to use."""
        if is_quiet():
            return NullCommitReporter()
        return ReportCommitToLog()

    def _check_pointless(self):
        if self.allow_pointless:
            return
        # A merge with no effect on files
        if len(self.parents) > 1:
            return
        # TODO: we could simplify this by using self._basis_delta.

        # The initial commit adds a root directory, but this in itself is not
        # a worthwhile commit.
        if (self.basis_revid == revision.NULL_REVISION and
            len(self.builder.new_inventory) == 1):
            raise PointlessCommit()
        # If length == 1, then we only have the root entry. Which means
        # that there is no real difference (only the root could be different)
        # unless deletes occured, in which case the length is irrelevant.
        if (self.any_entries_deleted or 
            (len(self.builder.new_inventory) != 1 and
             self.any_entries_changed)):
            return
        raise PointlessCommit()

    def _check_bound_branch(self, possible_master_transports=None):
        """Check to see if the local branch is bound.

        If it is bound, then most of the commit will actually be
        done using the remote branch as the target branch.
        Only at the end will the local branch be updated.
        """
        if self.local and not self.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        if not self.local:
            self.master_branch = self.branch.get_master_branch(
                possible_master_transports)

        if not self.master_branch:
            # make this branch the reference branch for out of date checks.
            self.master_branch = self.branch
            return

        # If the master branch is bound, we must fail
        master_bound_location = self.master_branch.get_bound_location()
        if master_bound_location:
            raise errors.CommitToDoubleBoundBranch(self.branch,
                    self.master_branch, master_bound_location)

        # TODO: jam 20051230 We could automatically push local
        #       commits to the remote branch if they would fit.
        #       But for now, just require remote to be identical
        #       to local.
        
        # Make sure the local branch is identical to the master
        master_info = self.master_branch.last_revision_info()
        local_info = self.branch.last_revision_info()
        if local_info != master_info:
            raise errors.BoundBranchOutOfDate(self.branch,
                    self.master_branch)

        # Now things are ready to change the master branch
        # so grab the lock
        self.bound_branch = self.branch
        self.master_branch.lock_write()
        self.master_locked = True

    def _check_out_of_date_tree(self):
        """Check that the working tree is up to date.

        :return: old_revision_number,new_revision_number tuple
        """
        try:
            first_tree_parent = self.work_tree.get_parent_ids()[0]
        except IndexError:
            # if there are no parents, treat our parent as 'None'
            # this is so that we still consider the master branch
            # - in a checkout scenario the tree may have no
            # parents but the branch may do.
            first_tree_parent = bzrlib.revision.NULL_REVISION
        old_revno, master_last = self.master_branch.last_revision_info()
        if master_last != first_tree_parent:
            if master_last != bzrlib.revision.NULL_REVISION:
                raise errors.OutOfDateTree(self.work_tree)
        if self.branch.repository.has_revision(first_tree_parent):
            new_revno = old_revno + 1
        else:
            # ghost parents never appear in revision history.
            new_revno = 1
        return old_revno,new_revno

    def _process_pre_hooks(self, old_revno, new_revno):
        """Process any registered pre commit hooks."""
        self._set_progress_stage("Running pre_commit hooks")
        self._process_hooks("pre_commit", old_revno, new_revno)

    def _process_post_hooks(self, old_revno, new_revno):
        """Process any registered post commit hooks."""
        # Process the post commit hooks, if any
        self._set_progress_stage("Running post_commit hooks")
        # old style commit hooks - should be deprecated ? (obsoleted in
        # 0.15)
        if self.config.post_commit() is not None:
            hooks = self.config.post_commit().split(' ')
            # this would be nicer with twisted.python.reflect.namedAny
            for hook in hooks:
                result = eval(hook + '(branch, rev_id)',
                              {'branch':self.branch,
                               'bzrlib':bzrlib,
                               'rev_id':self.rev_id})
        # process new style post commit hooks
        self._process_hooks("post_commit", old_revno, new_revno)

    def _process_hooks(self, hook_name, old_revno, new_revno):
        if not Branch.hooks[hook_name]:
            return
        
        # new style commit hooks:
        if not self.bound_branch:
            hook_master = self.branch
            hook_local = None
        else:
            hook_master = self.master_branch
            hook_local = self.branch
        # With bound branches, when the master is behind the local branch,
        # the 'old_revno' and old_revid values here are incorrect.
        # XXX: FIXME ^. RBC 20060206
        if self.parents:
            old_revid = self.parents[0]
        else:
            old_revid = bzrlib.revision.NULL_REVISION
        
        if hook_name == "pre_commit":
            future_tree = self.builder.revision_tree()
            tree_delta = future_tree.changes_from(self.basis_tree,
                                             include_root=True)
        
        for hook in Branch.hooks[hook_name]:
            # show the running hook in the progress bar. As hooks may
            # end up doing nothing (e.g. because they are not configured by
            # the user) this is still showing progress, not showing overall
            # actions - its up to each plugin to show a UI if it want's to
            # (such as 'Emailing diff to foo@example.com').
            self.pb_stage_name = "Running %s hooks [%s]" % \
                (hook_name, Branch.hooks.get_hook_name(hook))
            self._emit_progress()
            if 'hooks' in debug.debug_flags:
                mutter("Invoking commit hook: %r", hook)
            if hook_name == "post_commit":
                hook(hook_local, hook_master, old_revno, old_revid, new_revno,
                     self.rev_id)
            elif hook_name == "pre_commit":
                hook(hook_local, hook_master,
                     old_revno, old_revid, new_revno, self.rev_id,
                     tree_delta, future_tree)

    def _cleanup(self):
        """Cleanup any open locks, progress bars etc."""
        cleanups = [self._cleanup_bound_branch,
                    self.basis_tree.unlock,
                    self.work_tree.unlock,
                    self.pb.finished]
        found_exception = None
        for cleanup in cleanups:
            try:
                cleanup()
            # we want every cleanup to run no matter what.
            # so we have a catchall here, but we will raise the
            # last encountered exception up the stack: and
            # typically this will be useful enough.
            except Exception, e:
                found_exception = e
        if found_exception is not None: 
            # don't do a plan raise, because the last exception may have been
            # trashed, e is our sure-to-work exception even though it loses the
            # full traceback. XXX: RBC 20060421 perhaps we could check the
            # exc_info and if its the same one do a plain raise otherwise 
            # 'raise e' as we do now.
            raise e

    def _cleanup_bound_branch(self):
        """Executed at the end of a try/finally to cleanup a bound branch.

        If the branch wasn't bound, this is a no-op.
        If it was, it resents self.branch to the local branch, instead
        of being the master.
        """
        if not self.bound_branch:
            return
        if self.master_locked:
            self.master_branch.unlock()

    def _escape_commit_message(self):
        """Replace xml-incompatible control characters."""
        # FIXME: RBC 20060419 this should be done by the revision
        # serialiser not by commit. Then we can also add an unescaper
        # in the deserializer and start roundtripping revision messages
        # precisely. See repository_implementations/test_repository.py
        
        # Python strings can include characters that can't be
        # represented in well-formed XML; escape characters that
        # aren't listed in the XML specification
        # (http://www.w3.org/TR/REC-xml/#NT-Char).
        self.message, escape_count = re.subn(
            u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
            lambda match: match.group(0).encode('unicode_escape'),
            self.message)
        if escape_count:
            self.reporter.escaped(escape_count, self.message)

    def _gather_parents(self):
        """Record the parents of a merge for merge detection."""
        # TODO: Make sure that this list doesn't contain duplicate 
        # entries and the order is preserved when doing this.
        self.parents = self.work_tree.get_parent_ids()
        self.parent_invs = [self.basis_inv]
        for revision in self.parents[1:]:
            if self.branch.repository.has_revision(revision):
                mutter('commit parent revision {%s}', revision)
                inventory = self.branch.repository.get_inventory(revision)
                self.parent_invs.append(inventory)
            else:
                mutter('commit parent ghost revision {%s}', revision)

    def _update_builder_with_changes(self):
        """Update the commit builder with the data about what has changed.
        """
        # Build the revision inventory.
        #
        # This starts by creating a new empty inventory. Depending on
        # which files are selected for commit, and what is present in the
        # current tree, the new inventory is populated. inventory entries 
        # which are candidates for modification have their revision set to
        # None; inventory entries that are carried over untouched have their
        # revision set to their prior value.
        #
        # ESEPARATIONOFCONCERNS: this function is diffing and using the diff
        # results to create a new inventory at the same time, which results
        # in bugs like #46635.  Any reason not to use/enhance Tree.changes_from?
        # ADHB 11-07-2006

        exclude = self.exclude
        specific_files = self.specific_files or []
        mutter("Selecting files for commit with filter %s", specific_files)

        # Build the new inventory
        self._populate_from_inventory()

        # If specific files are selected, then all un-selected files must be
        # recorded in their previous state. For more details, see
        # https://lists.ubuntu.com/archives/bazaar/2007q3/028476.html.
        if specific_files or exclude:
            for path, old_ie in self.basis_inv.iter_entries():
                if old_ie.file_id in self.builder.new_inventory:
                    # already added - skip.
                    continue
                if (is_inside_any(specific_files, path)
                    and not is_inside_any(exclude, path)):
                    # was inside the selected path, and not excluded - if not
                    # present it has been deleted so skip.
                    continue
                # From here down it was either not selected, or was excluded:
                if old_ie.kind == 'directory':
                    self._next_progress_entry()
                # We preserve the entry unaltered.
                ie = old_ie.copy()
                # Note: specific file commits after a merge are currently
                # prohibited. This test is for sanity/safety in case it's
                # required after that changes.
                if len(self.parents) > 1:
                    ie.revision = None
                delta, version_recorded, _ = self.builder.record_entry_contents(
                    ie, self.parent_invs, path, self.basis_tree, None)
                if version_recorded:
                    self.any_entries_changed = True
                if delta:
                    self._basis_delta.append(delta)

    def _report_and_accumulate_deletes(self):
        # XXX: Could the list of deleted paths and ids be instead taken from
        # _populate_from_inventory?
        if (isinstance(self.basis_inv, Inventory)
            and isinstance(self.builder.new_inventory, Inventory)):
            # the older Inventory classes provide a _byid dict, and building a
            # set from the keys of this dict is substantially faster than even
            # getting a set of ids from the inventory
            #
            # <lifeless> set(dict) is roughly the same speed as
            # set(iter(dict)) and both are significantly slower than
            # set(dict.keys())
            deleted_ids = set(self.basis_inv._byid.keys()) - \
               set(self.builder.new_inventory._byid.keys())
        else:
            deleted_ids = set(self.basis_inv) - set(self.builder.new_inventory)
        if deleted_ids:
            self.any_entries_deleted = True
            deleted = [(self.basis_tree.id2path(file_id), file_id)
                for file_id in deleted_ids]
            deleted.sort()
            # XXX: this is not quite directory-order sorting
            for path, file_id in deleted:
                self._basis_delta.append((path, None, file_id, None))
                self.reporter.deleted(path)

    def _populate_from_inventory(self):
        """Populate the CommitBuilder by walking the working tree inventory."""
        if self.strict:
            # raise an exception as soon as we find a single unknown.
            for unknown in self.work_tree.unknowns():
                raise StrictCommitFailed()
        
        specific_files = self.specific_files
        exclude = self.exclude
        report_changes = self.reporter.is_verbose()
        deleted_ids = []
        # A tree of paths that have been deleted. E.g. if foo/bar has been
        # deleted, then we have {'foo':{'bar':{}}}
        deleted_paths = {}
        # XXX: Note that entries may have the wrong kind because the entry does
        # not reflect the status on disk.
        work_inv = self.work_tree.inventory
        # NB: entries will include entries within the excluded ids/paths
        # because iter_entries_by_dir has no 'exclude' facility today.
        entries = work_inv.iter_entries_by_dir(
            specific_file_ids=self.specific_file_ids, yield_parents=True)
        for path, existing_ie in entries:
            file_id = existing_ie.file_id
            name = existing_ie.name
            parent_id = existing_ie.parent_id
            kind = existing_ie.kind
            if kind == 'directory':
                self._next_progress_entry()
            # Skip files that have been deleted from the working tree.
            # The deleted path ids are also recorded so they can be explicitly
            # unversioned later.
            if deleted_paths:
                path_segments = splitpath(path)
                deleted_dict = deleted_paths
                for segment in path_segments:
                    deleted_dict = deleted_dict.get(segment, None)
                    if not deleted_dict:
                        # We either took a path not present in the dict
                        # (deleted_dict was None), or we've reached an empty
                        # child dir in the dict, so are now a sub-path.
                        break
                else:
                    deleted_dict = None
                if deleted_dict is not None:
                    # the path has a deleted parent, do not add it.
                    continue
            if exclude and is_inside_any(exclude, path):
                # Skip excluded paths. Excluded paths are processed by
                # _update_builder_with_changes.
                continue
            content_summary = self.work_tree.path_content_summary(path)
            # Note that when a filter of specific files is given, we must only
            # skip/record deleted files matching that filter.
            if not specific_files or is_inside_any(specific_files, path):
                if content_summary[0] == 'missing':
                    if not deleted_paths:
                        # path won't have been split yet.
                        path_segments = splitpath(path)
                    deleted_dict = deleted_paths
                    for segment in path_segments:
                        deleted_dict = deleted_dict.setdefault(segment, {})
                    self.reporter.missing(path)
                    deleted_ids.append(file_id)
                    continue
            # TODO: have the builder do the nested commit just-in-time IF and
            # only if needed.
            if content_summary[0] == 'tree-reference':
                # enforce repository nested tree policy.
                if (not self.work_tree.supports_tree_reference() or
                    # repository does not support it either.
                    not self.branch.repository._format.supports_tree_reference):
                    content_summary = ('directory',) + content_summary[1:]
            kind = content_summary[0]
            # TODO: specific_files filtering before nested tree processing
            if kind == 'tree-reference':
                if self.recursive == 'down':
                    nested_revision_id = self._commit_nested_tree(
                        file_id, path)
                    content_summary = content_summary[:3] + (
                        nested_revision_id,)
                else:
                    content_summary = content_summary[:3] + (
                        self.work_tree.get_reference_revision(file_id),)

            # Record an entry for this item
            # Note: I don't particularly want to have the existing_ie
            # parameter but the test suite currently (28-Jun-07) breaks
            # without it thanks to a unicode normalisation issue. :-(
            definitely_changed = kind != existing_ie.kind
            self._record_entry(path, file_id, specific_files, kind, name,
                parent_id, definitely_changed, existing_ie, report_changes,
                content_summary)

        # Unversion IDs that were found to be deleted
        self.work_tree.unversion(deleted_ids)

    def _commit_nested_tree(self, file_id, path):
        "Commit a nested tree."
        sub_tree = self.work_tree.get_nested_tree(file_id, path)
        # FIXME: be more comprehensive here:
        # this works when both trees are in --trees repository,
        # but when both are bound to a different repository,
        # it fails; a better way of approaching this is to 
        # finally implement the explicit-caches approach design
        # a while back - RBC 20070306.
        if sub_tree.branch.repository.has_same_location(
            self.work_tree.branch.repository):
            sub_tree.branch.repository = \
                self.work_tree.branch.repository
        try:
            return sub_tree.commit(message=None, revprops=self.revprops,
                recursive=self.recursive,
                message_callback=self.message_callback,
                timestamp=self.timestamp, timezone=self.timezone,
                committer=self.committer,
                allow_pointless=self.allow_pointless,
                strict=self.strict, verbose=self.verbose,
                local=self.local, reporter=self.reporter)
        except errors.PointlessCommit:
            return self.work_tree.get_reference_revision(file_id)

    def _record_entry(self, path, file_id, specific_files, kind, name,
        parent_id, definitely_changed, existing_ie, report_changes,
        content_summary):
        "Record the new inventory entry for a path if any."
        # mutter('check %s {%s}', path, file_id)
        # mutter('%s selected for commit', path)
        if definitely_changed or existing_ie is None:
            ie = make_entry(kind, name, parent_id, file_id)
        else:
            ie = existing_ie.copy()
            ie.revision = None
        # For carried over entries we don't care about the fs hash - the repo
        # isn't generating a sha, so we're not saving computation time.
        delta, version_recorded, fs_hash = self.builder.record_entry_contents(
            ie, self.parent_invs, path, self.work_tree, content_summary)
        if delta:
            self._basis_delta.append(delta)
        if version_recorded:
            self.any_entries_changed = True
        if report_changes:
            self._report_change(ie, path)
        if fs_hash:
            self.work_tree._observed_sha1(ie.file_id, path, fs_hash)
        return ie

    def _report_change(self, ie, path):
        """Report a change to the user.

        The change that has occurred is described relative to the basis
        inventory.
        """
        if (self.basis_inv.has_id(ie.file_id)):
            basis_ie = self.basis_inv[ie.file_id]
        else:
            basis_ie = None
        change = ie.describe_change(basis_ie, ie)
        if change in (InventoryEntry.RENAMED, 
            InventoryEntry.MODIFIED_AND_RENAMED):
            old_path = self.basis_inv.id2path(ie.file_id)
            self.reporter.renamed(change, old_path, path)
        else:
            self.reporter.snapshot_change(change, path)

    def _set_progress_stage(self, name, entries_title=None):
        """Set the progress stage and emit an update to the progress bar."""
        self.pb_stage_name = name
        self.pb_stage_count += 1
        self.pb_entries_title = entries_title
        if entries_title is not None:
            self.pb_entries_count = 0
            self.pb_entries_total = '?'
        self._emit_progress()

    def _next_progress_entry(self):
        """Emit an update to the progress bar and increment the entry count."""
        self.pb_entries_count += 1
        self._emit_progress()

    def _emit_progress(self):
        if self.pb_entries_title:
            if self.pb_entries_total == '?':
                text = "%s [%s %d] - Stage" % (self.pb_stage_name,
                    self.pb_entries_title, self.pb_entries_count)
            else:
                text = "%s [%s %d/%s] - Stage" % (self.pb_stage_name,
                    self.pb_entries_title, self.pb_entries_count,
                    str(self.pb_entries_total))
        else:
            text = "%s - Stage" % (self.pb_stage_name)
        self.pb.update(text, self.pb_stage_count, self.pb_stage_total)

