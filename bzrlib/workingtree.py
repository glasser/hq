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

"""WorkingTree object and friends.

A WorkingTree represents the editable working copy of a branch.
Operations which represent the WorkingTree are also done here, 
such as renaming or adding files.  The WorkingTree has an inventory 
which is updated by these operations.  A commit produces a 
new revision based on the workingtree and its inventory.

At the moment every WorkingTree has its own branch.  Remote
WorkingTrees aren't supported.

To get a WorkingTree, call bzrdir.open_workingtree() or
WorkingTree.open(dir).
"""

# TODO: Give the workingtree sole responsibility for the working inventory;
# remove the variable and references to it from the branch.  This may require
# updating the commit code so as to update the inventory within the working
# copy, and making sure there's only one WorkingTree for any directory on disk.
# At the moment they may alias the inventory and have old copies of it in
# memory.  (Now done? -- mbp 20060309)

from cStringIO import StringIO
import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bisect import bisect_left
import collections
import errno
import itertools
import operator
import stat
from time import time
import warnings
import re

import bzrlib
from bzrlib import (
    branch,
    bzrdir,
    conflicts as _mod_conflicts,
    dirstate,
    errors,
    generate_ids,
    globbing,
    hashcache,
    ignores,
    merge,
    revision as _mod_revision,
    revisiontree,
    repository,
    textui,
    trace,
    transform,
    ui,
    urlutils,
    xml5,
    xml6,
    xml7,
    )
import bzrlib.branch
from bzrlib.transport import get_transport
import bzrlib.ui
from bzrlib.workingtree_4 import WorkingTreeFormat4
""")

from bzrlib import symbol_versioning
from bzrlib.decorators import needs_read_lock, needs_write_lock
from bzrlib.inventory import InventoryEntry, Inventory, ROOT_ID, TreeReference
from bzrlib.lockable_files import LockableFiles
from bzrlib.lockdir import LockDir
import bzrlib.mutabletree
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib import osutils
from bzrlib.osutils import (
    compact_date,
    file_kind,
    isdir,
    normpath,
    pathjoin,
    rand_chars,
    realpath,
    safe_unicode,
    splitpath,
    supports_executable,
    )
from bzrlib.trace import mutter, note
from bzrlib.transport.local import LocalTransport
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.revision import NULL_REVISION, CURRENT_REVISION
from bzrlib.rio import RioReader, rio_file, Stanza
from bzrlib.symbol_versioning import (deprecated_passed,
        deprecated_method,
        deprecated_function,
        DEPRECATED_PARAMETER,
        )


MERGE_MODIFIED_HEADER_1 = "BZR merge-modified list format 1"
CONFLICT_HEADER_1 = "BZR conflict list format 1"

ERROR_PATH_NOT_FOUND = 3    # WindowsError errno code, equivalent to ENOENT


class TreeEntry(object):
    """An entry that implements the minimum interface used by commands.

    This needs further inspection, it may be better to have 
    InventoryEntries without ids - though that seems wrong. For now,
    this is a parallel hierarchy to InventoryEntry, and needs to become
    one of several things: decorates to that hierarchy, children of, or
    parents of it.
    Another note is that these objects are currently only used when there is
    no InventoryEntry available - i.e. for unversioned objects.
    Perhaps they should be UnversionedEntry et al. ? - RBC 20051003
    """
 
    def __eq__(self, other):
        # yes, this us ugly, TODO: best practice __eq__ style.
        return (isinstance(other, TreeEntry)
                and other.__class__ == self.__class__)
 
    def kind_character(self):
        return "???"


class TreeDirectory(TreeEntry):
    """See TreeEntry. This is a directory in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeDirectory)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return "/"


class TreeFile(TreeEntry):
    """See TreeEntry. This is a regular file in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeFile)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class TreeLink(TreeEntry):
    """See TreeEntry. This is a symlink in a working tree."""

    def __eq__(self, other):
        return (isinstance(other, TreeLink)
                and other.__class__ == self.__class__)

    def kind_character(self):
        return ''


class WorkingTree(bzrlib.mutabletree.MutableTree):
    """Working copy tree.

    The inventory is held in the `Branch` working-inventory, and the
    files are in a directory on disk.

    It is possible for a `WorkingTree` to have a filename which is
    not listed in the Inventory and vice versa.
    """

    def __init__(self, basedir='.',
                 branch=DEPRECATED_PARAMETER,
                 _inventory=None,
                 _control_files=None,
                 _internal=False,
                 _format=None,
                 _bzrdir=None):
        """Construct a WorkingTree instance. This is not a public API.

        :param branch: A branch to override probing for the branch.
        """
        self._format = _format
        self.bzrdir = _bzrdir
        if not _internal:
            raise errors.BzrError("Please use bzrdir.open_workingtree or "
                "WorkingTree.open() to obtain a WorkingTree.")
        basedir = safe_unicode(basedir)
        mutter("opening working tree %r", basedir)
        if deprecated_passed(branch):
            self._branch = branch
        else:
            self._branch = self.bzrdir.open_branch()
        self.basedir = realpath(basedir)
        # if branch is at our basedir and is a format 6 or less
        if isinstance(self._format, WorkingTreeFormat2):
            # share control object
            self._control_files = self.branch.control_files
        else:
            # assume all other formats have their own control files.
            self._control_files = _control_files
        self._transport = self._control_files._transport
        # update the whole cache up front and write to disk if anything changed;
        # in the future we might want to do this more selectively
        # two possible ways offer themselves : in self._unlock, write the cache
        # if needed, or, when the cache sees a change, append it to the hash
        # cache file, and have the parser take the most recent entry for a
        # given path only.
        wt_trans = self.bzrdir.get_workingtree_transport(None)
        cache_filename = wt_trans.local_abspath('stat-cache')
        self._hashcache = hashcache.HashCache(basedir, cache_filename,
            self.bzrdir._get_file_mode())
        hc = self._hashcache
        hc.read()
        # is this scan needed ? it makes things kinda slow.
        #hc.scan()

        if hc.needs_write:
            mutter("write hc")
            hc.write()

        if _inventory is None:
            # This will be acquired on lock_read() or lock_write()
            self._inventory_is_modified = False
            self._inventory = None
        else:
            # the caller of __init__ has provided an inventory,
            # we assume they know what they are doing - as its only
            # the Format factory and creation methods that are
            # permitted to do this.
            self._set_inventory(_inventory, dirty=False)
        self._detect_case_handling()
        self._rules_searcher = None

    def _detect_case_handling(self):
        wt_trans = self.bzrdir.get_workingtree_transport(None)
        try:
            wt_trans.stat("FoRMaT")
        except errors.NoSuchFile:
            self.case_sensitive = True
        else:
            self.case_sensitive = False

        self._setup_directory_is_tree_reference()

    branch = property(
        fget=lambda self: self._branch,
        doc="""The branch this WorkingTree is connected to.

            This cannot be set - it is reflective of the actual disk structure
            the working tree has been constructed from.
            """)

    def break_lock(self):
        """Break a lock if one is present from another instance.

        Uses the ui factory to ask for confirmation if the lock may be from
        an active process.

        This will probe the repository for its lock as well.
        """
        self._control_files.break_lock()
        self.branch.break_lock()

    def requires_rich_root(self):
        return self._format.requires_rich_root

    def supports_tree_reference(self):
        return False

    def _set_inventory(self, inv, dirty):
        """Set the internal cached inventory.

        :param inv: The inventory to set.
        :param dirty: A boolean indicating whether the inventory is the same
            logical inventory as whats on disk. If True the inventory is not
            the same and should be written to disk or data will be lost, if
            False then the inventory is the same as that on disk and any
            serialisation would be unneeded overhead.
        """
        self._inventory = inv
        self._inventory_is_modified = dirty

    @staticmethod
    def open(path=None, _unsupported=False):
        """Open an existing working tree at path.

        """
        if path is None:
            path = osutils.getcwd()
        control = bzrdir.BzrDir.open(path, _unsupported)
        return control.open_workingtree(_unsupported)

    @staticmethod
    def open_containing(path=None):
        """Open an existing working tree which has its root about path.

        This probes for a working tree at path and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into /.  If there isn't one, raises NotBranchError.
        TODO: give this a new exception.
        If there is one, it is returned, along with the unused portion of path.

        :return: The WorkingTree that contains 'path', and the rest of path
        """
        if path is None:
            path = osutils.getcwd()
        control, relpath = bzrdir.BzrDir.open_containing(path)

        return control.open_workingtree(), relpath

    @staticmethod
    def open_downlevel(path=None):
        """Open an unsupported working tree.

        Only intended for advanced situations like upgrading part of a bzrdir.
        """
        return WorkingTree.open(path, _unsupported=True)

    @staticmethod
    def find_trees(location):
        def list_current(transport):
            return [d for d in transport.list_dir('') if d != '.bzr']
        def evaluate(bzrdir):
            try:
                tree = bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                return True, None
            else:
                return True, tree
        transport = get_transport(location)
        iterator = bzrdir.BzrDir.find_bzrdirs(transport, evaluate=evaluate,
                                              list_current=list_current)
        return [t for t in iterator if t is not None]

    # should be deprecated - this is slow and in any case treating them as a
    # container is (we now know) bad style -- mbp 20070302
    ## @deprecated_method(zero_fifteen)
    def __iter__(self):
        """Iterate through file_ids for this tree.

        file_ids are in a WorkingTree if they are in the working inventory
        and the working file exists.
        """
        inv = self._inventory
        for path, ie in inv.iter_entries():
            if osutils.lexists(self.abspath(path)):
                yield ie.file_id

    def all_file_ids(self):
        """See Tree.iter_all_file_ids"""
        return set(self.inventory)

    def __repr__(self):
        return "<%s of %s>" % (self.__class__.__name__,
                               getattr(self, 'basedir', None))

    def abspath(self, filename):
        return pathjoin(self.basedir, filename)

    def basis_tree(self):
        """Return RevisionTree for the current last revision.
        
        If the left most parent is a ghost then the returned tree will be an
        empty tree - one obtained by calling 
        repository.revision_tree(NULL_REVISION).
        """
        try:
            revision_id = self.get_parent_ids()[0]
        except IndexError:
            # no parents, return an empty revision tree.
            # in the future this should return the tree for
            # 'empty:' - the implicit root empty tree.
            return self.branch.repository.revision_tree(
                       _mod_revision.NULL_REVISION)
        try:
            return self.revision_tree(revision_id)
        except errors.NoSuchRevision:
            pass
        # No cached copy available, retrieve from the repository.
        # FIXME? RBC 20060403 should we cache the inventory locally
        # at this point ?
        try:
            return self.branch.repository.revision_tree(revision_id)
        except (errors.RevisionNotPresent, errors.NoSuchRevision):
            # the basis tree *may* be a ghost or a low level error may have
            # occured. If the revision is present, its a problem, if its not
            # its a ghost.
            if self.branch.repository.has_revision(revision_id):
                raise
            # the basis tree is a ghost so return an empty tree.
            return self.branch.repository.revision_tree(
                       _mod_revision.NULL_REVISION)

    def _cleanup(self):
        self._flush_ignore_list_cache()

    def relpath(self, path):
        """Return the local path portion from a given path.
        
        The path may be absolute or relative. If its a relative path it is 
        interpreted relative to the python current working directory.
        """
        return osutils.relpath(self.basedir, path)

    def has_filename(self, filename):
        return osutils.lexists(self.abspath(filename))

    def get_file(self, file_id, path=None):
        return self.get_file_with_stat(file_id, path)[0]

    def get_file_with_stat(self, file_id, path=None, _fstat=os.fstat):
        """See MutableTree.get_file_with_stat."""
        if path is None:
            path = self.id2path(file_id)
        file_obj = self.get_file_byname(path)
        return (file_obj, _fstat(file_obj.fileno()))

    def get_file_byname(self, filename):
        return file(self.abspath(filename), 'rb')

    def get_file_lines(self, file_id, path=None):
        """See Tree.get_file_lines()"""
        file = self.get_file(file_id, path)
        try:
            return file.readlines()
        finally:
            file.close()

    @needs_read_lock
    def annotate_iter(self, file_id, default_revision=CURRENT_REVISION):
        """See Tree.annotate_iter

        This implementation will use the basis tree implementation if possible.
        Lines not in the basis are attributed to CURRENT_REVISION

        If there are pending merges, lines added by those merges will be
        incorrectly attributed to CURRENT_REVISION (but after committing, the
        attribution will be correct).
        """
        basis = self.basis_tree()
        basis.lock_read()
        try:
            changes = self.iter_changes(basis, True, [self.id2path(file_id)],
                require_versioned=True).next()
            changed_content, kind = changes[2], changes[6]
            if not changed_content:
                return basis.annotate_iter(file_id)
            if kind[1] is None:
                return None
            import annotate
            if kind[0] != 'file':
                old_lines = []
            else:
                old_lines = list(basis.annotate_iter(file_id))
            old = [old_lines]
            for tree in self.branch.repository.revision_trees(
                self.get_parent_ids()[1:]):
                if file_id not in tree:
                    continue
                old.append(list(tree.annotate_iter(file_id)))
            return annotate.reannotate(old, self.get_file(file_id).readlines(),
                                       default_revision)
        finally:
            basis.unlock()

    def _get_ancestors(self, default_revision):
        ancestors = set([default_revision])
        for parent_id in self.get_parent_ids():
            ancestors.update(self.branch.repository.get_ancestry(
                             parent_id, topo_sorted=False))
        return ancestors

    def get_parent_ids(self):
        """See Tree.get_parent_ids.
        
        This implementation reads the pending merges list and last_revision
        value and uses that to decide what the parents list should be.
        """
        last_rev = _mod_revision.ensure_null(self._last_revision())
        if _mod_revision.NULL_REVISION == last_rev:
            parents = []
        else:
            parents = [last_rev]
        try:
            merges_file = self._transport.get('pending-merges')
        except errors.NoSuchFile:
            pass
        else:
            for l in merges_file.readlines():
                revision_id = l.rstrip('\n')
                parents.append(revision_id)
        return parents

    @needs_read_lock
    def get_root_id(self):
        """Return the id of this trees root"""
        return self._inventory.root.file_id
        
    def _get_store_filename(self, file_id):
        ## XXX: badly named; this is not in the store at all
        return self.abspath(self.id2path(file_id))

    @needs_read_lock
    def clone(self, to_bzrdir, revision_id=None):
        """Duplicate this working tree into to_bzr, including all state.
        
        Specifically modified files are kept as modified, but
        ignored and unknown files are discarded.

        If you want to make a new line of development, see bzrdir.sprout()

        revision
            If not None, the cloned tree will have its last revision set to 
            revision, and and difference between the source trees last revision
            and this one merged in.
        """
        # assumes the target bzr dir format is compatible.
        result = to_bzrdir.create_workingtree()
        self.copy_content_into(result, revision_id)
        return result

    @needs_read_lock
    def copy_content_into(self, tree, revision_id=None):
        """Copy the current content and user files of this tree into tree."""
        tree.set_root_id(self.get_root_id())
        if revision_id is None:
            merge.transform_tree(tree, self)
        else:
            # TODO now merge from tree.last_revision to revision (to preserve
            # user local changes)
            merge.transform_tree(tree, self)
            tree.set_parent_ids([revision_id])

    def id2abspath(self, file_id):
        return self.abspath(self.id2path(file_id))

    def has_id(self, file_id):
        # files that have been deleted are excluded
        inv = self.inventory
        if not inv.has_id(file_id):
            return False
        path = inv.id2path(file_id)
        return osutils.lexists(self.abspath(path))

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def get_file_size(self, file_id):
        """See Tree.get_file_size"""
        try:
            return os.path.getsize(self.id2abspath(file_id))
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
            else:
                return None

    @needs_read_lock
    def get_file_sha1(self, file_id, path=None, stat_value=None):
        if not path:
            path = self._inventory.id2path(file_id)
        return self._hashcache.get_sha1(path, stat_value)

    def get_file_mtime(self, file_id, path=None):
        if not path:
            path = self.inventory.id2path(file_id)
        return os.lstat(self.abspath(path)).st_mtime

    def _is_executable_from_path_and_stat_from_basis(self, path, stat_result):
        file_id = self.path2id(path)
        return self._inventory[file_id].executable

    def _is_executable_from_path_and_stat_from_stat(self, path, stat_result):
        mode = stat_result.st_mode
        return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

    if not supports_executable():
        def is_executable(self, file_id, path=None):
            return self._inventory[file_id].executable

        _is_executable_from_path_and_stat = \
            _is_executable_from_path_and_stat_from_basis
    else:
        def is_executable(self, file_id, path=None):
            if not path:
                path = self.id2path(file_id)
            mode = os.lstat(self.abspath(path)).st_mode
            return bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)

        _is_executable_from_path_and_stat = \
            _is_executable_from_path_and_stat_from_stat

    @needs_tree_write_lock
    def _add(self, files, ids, kinds):
        """See MutableTree._add."""
        # TODO: Re-adding a file that is removed in the working copy
        # should probably put it back with the previous ID.
        # the read and write working inventory should not occur in this 
        # function - they should be part of lock_write and unlock.
        inv = self.inventory
        for f, file_id, kind in zip(files, ids, kinds):
            if file_id is None:
                inv.add_path(f, kind=kind)
            else:
                inv.add_path(f, kind=kind, file_id=file_id)
            self._inventory_is_modified = True

    @needs_tree_write_lock
    def _gather_kinds(self, files, kinds):
        """See MutableTree._gather_kinds."""
        for pos, f in enumerate(files):
            if kinds[pos] is None:
                fullpath = normpath(self.abspath(f))
                try:
                    kinds[pos] = file_kind(fullpath)
                except OSError, e:
                    if e.errno == errno.ENOENT:
                        raise errors.NoSuchFile(fullpath)

    @needs_write_lock
    def add_parent_tree_id(self, revision_id, allow_leftmost_as_ghost=False):
        """Add revision_id as a parent.

        This is equivalent to retrieving the current list of parent ids
        and setting the list to its value plus revision_id.

        :param revision_id: The revision id to add to the parent list. It may
        be a ghost revision as long as its not the first parent to be added,
        or the allow_leftmost_as_ghost parameter is set True.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parents = self.get_parent_ids() + [revision_id]
        self.set_parent_ids(parents, allow_leftmost_as_ghost=len(parents) > 1
            or allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_parent_tree(self, parent_tuple, allow_leftmost_as_ghost=False):
        """Add revision_id, tree tuple as a parent.

        This is equivalent to retrieving the current list of parent trees
        and setting the list to its value plus parent_tuple. See also
        add_parent_tree_id - if you only have a parent id available it will be
        simpler to use that api. If you have the parent already available, using
        this api is preferred.

        :param parent_tuple: The (revision id, tree) to add to the parent list.
            If the revision_id is a ghost, pass None for the tree.
        :param allow_leftmost_as_ghost: Allow the first parent to be a ghost.
        """
        parent_ids = self.get_parent_ids() + [parent_tuple[0]]
        if len(parent_ids) > 1:
            # the leftmost may have already been a ghost, preserve that if it
            # was.
            allow_leftmost_as_ghost = True
        self.set_parent_ids(parent_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

    @needs_tree_write_lock
    def add_pending_merge(self, *revision_ids):
        # TODO: Perhaps should check at this point that the
        # history of the revision is actually present?
        parents = self.get_parent_ids()
        updated = False
        for rev_id in revision_ids:
            if rev_id in parents:
                continue
            parents.append(rev_id)
            updated = True
        if updated:
            self.set_parent_ids(parents, allow_leftmost_as_ghost=True)

    def path_content_summary(self, path, _lstat=os.lstat,
        _mapper=osutils.file_kind_from_stat_mode):
        """See Tree.path_content_summary."""
        abspath = self.abspath(path)
        try:
            stat_result = _lstat(abspath)
        except OSError, e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                # no file.
                return ('missing', None, None, None)
            # propagate other errors
            raise
        kind = _mapper(stat_result.st_mode)
        if kind == 'file':
            size = stat_result.st_size
            # try for a stat cache lookup
            executable = self._is_executable_from_path_and_stat(path, stat_result)
            return (kind, size, executable, self._sha_from_stat(
                path, stat_result))
        elif kind == 'directory':
            # perhaps it looks like a plain directory, but it's really a
            # reference.
            if self._directory_is_tree_reference(path):
                kind = 'tree-reference'
            return kind, None, None, None
        elif kind == 'symlink':
            return ('symlink', None, None, os.readlink(abspath))
        else:
            return (kind, None, None, None)

    def _check_parents_for_ghosts(self, revision_ids, allow_leftmost_as_ghost):
        """Common ghost checking functionality from set_parent_*.

        This checks that the left hand-parent exists if there are any
        revisions present.
        """
        if len(revision_ids) > 0:
            leftmost_id = revision_ids[0]
            if (not allow_leftmost_as_ghost and not
                self.branch.repository.has_revision(leftmost_id)):
                raise errors.GhostRevisionUnusableHere(leftmost_id)

    def _set_merges_from_parent_ids(self, parent_ids):
        merges = parent_ids[1:]
        self._transport.put_bytes('pending-merges', '\n'.join(merges),
            mode=self._control_files._file_mode)

    def _filter_parent_ids_by_ancestry(self, revision_ids):
        """Check that all merged revisions are proper 'heads'.

        This will always return the first revision_id, and any merged revisions
        which are 
        """
        if len(revision_ids) == 0:
            return revision_ids
        graph = self.branch.repository.get_graph()
        heads = graph.heads(revision_ids)
        new_revision_ids = revision_ids[:1]
        for revision_id in revision_ids[1:]:
            if revision_id in heads and revision_id not in new_revision_ids:
                new_revision_ids.append(revision_id)
        if new_revision_ids != revision_ids:
            trace.mutter('requested to set revision_ids = %s,'
                         ' but filtered to %s', revision_ids, new_revision_ids)
        return new_revision_ids

    @needs_tree_write_lock
    def set_parent_ids(self, revision_ids, allow_leftmost_as_ghost=False):
        """Set the parent ids to revision_ids.
        
        See also set_parent_trees. This api will try to retrieve the tree data
        for each element of revision_ids from the trees repository. If you have
        tree data already available, it is more efficient to use
        set_parent_trees rather than set_parent_ids. set_parent_ids is however
        an easier API to use.

        :param revision_ids: The revision_ids to set as the parent ids of this
            working tree. Any of these may be ghosts.
        """
        self._check_parents_for_ghosts(revision_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)
        for revision_id in revision_ids:
            _mod_revision.check_not_reserved_id(revision_id)

        revision_ids = self._filter_parent_ids_by_ancestry(revision_ids)

        if len(revision_ids) > 0:
            self.set_last_revision(revision_ids[0])
        else:
            self.set_last_revision(_mod_revision.NULL_REVISION)

        self._set_merges_from_parent_ids(revision_ids)

    @needs_tree_write_lock
    def set_parent_trees(self, parents_list, allow_leftmost_as_ghost=False):
        """See MutableTree.set_parent_trees."""
        parent_ids = [rev for (rev, tree) in parents_list]
        for revision_id in parent_ids:
            _mod_revision.check_not_reserved_id(revision_id)

        self._check_parents_for_ghosts(parent_ids,
            allow_leftmost_as_ghost=allow_leftmost_as_ghost)

        parent_ids = self._filter_parent_ids_by_ancestry(parent_ids)

        if len(parent_ids) == 0:
            leftmost_parent_id = _mod_revision.NULL_REVISION
            leftmost_parent_tree = None
        else:
            leftmost_parent_id, leftmost_parent_tree = parents_list[0]

        if self._change_last_revision(leftmost_parent_id):
            if leftmost_parent_tree is None:
                # If we don't have a tree, fall back to reading the
                # parent tree from the repository.
                self._cache_basis_inventory(leftmost_parent_id)
            else:
                inv = leftmost_parent_tree.inventory
                xml = self._create_basis_xml_from_inventory(
                                        leftmost_parent_id, inv)
                self._write_basis_inventory(xml)
        self._set_merges_from_parent_ids(parent_ids)

    @needs_tree_write_lock
    def set_pending_merges(self, rev_list):
        parents = self.get_parent_ids()
        leftmost = parents[:1]
        new_parents = leftmost + rev_list
        self.set_parent_ids(new_parents)

    @needs_tree_write_lock
    def set_merge_modified(self, modified_hashes):
        def iter_stanzas():
            for file_id, hash in modified_hashes.iteritems():
                yield Stanza(file_id=file_id.decode('utf8'), hash=hash)
        self._put_rio('merge-hashes', iter_stanzas(), MERGE_MODIFIED_HEADER_1)

    def _sha_from_stat(self, path, stat_result):
        """Get a sha digest from the tree's stat cache.

        The default implementation assumes no stat cache is present.

        :param path: The path.
        :param stat_result: The stat result being looked up.
        """
        return None

    def _put_rio(self, filename, stanzas, header):
        self._must_be_locked()
        my_file = rio_file(stanzas, header)
        self._transport.put_file(filename, my_file,
            mode=self._control_files._file_mode)

    @needs_write_lock # because merge pulls data into the branch.
    def merge_from_branch(self, branch, to_revision=None, from_revision=None,
        merge_type=None):
        """Merge from a branch into this working tree.

        :param branch: The branch to merge from.
        :param to_revision: If non-None, the merge will merge to to_revision,
            but not beyond it. to_revision does not need to be in the history
            of the branch when it is supplied. If None, to_revision defaults to
            branch.last_revision().
        """
        from bzrlib.merge import Merger, Merge3Merger
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            merger = Merger(self.branch, this_tree=self, pb=pb)
            merger.pp = ProgressPhase("Merge phase", 5, pb)
            merger.pp.next_phase()
            # check that there are no
            # local alterations
            merger.check_basis(check_clean=True, require_commits=False)
            if to_revision is None:
                to_revision = _mod_revision.ensure_null(branch.last_revision())
            merger.other_rev_id = to_revision
            if _mod_revision.is_null(merger.other_rev_id):
                raise errors.NoCommits(branch)
            self.branch.fetch(branch, last_revision=merger.other_rev_id)
            merger.other_basis = merger.other_rev_id
            merger.other_tree = self.branch.repository.revision_tree(
                merger.other_rev_id)
            merger.other_branch = branch
            merger.pp.next_phase()
            if from_revision is None:
                merger.find_base()
            else:
                merger.set_base_revision(from_revision, branch)
            if merger.base_rev_id == merger.other_rev_id:
                raise errors.PointlessMerge
            merger.backup_files = False
            if merge_type is None:
                merger.merge_type = Merge3Merger
            else:
                merger.merge_type = merge_type
            merger.set_interesting_files(None)
            merger.show_base = False
            merger.reprocess = False
            conflicts = merger.do_merge()
            merger.set_pending()
        finally:
            pb.finished()
        return conflicts

    @needs_read_lock
    def merge_modified(self):
        """Return a dictionary of files modified by a merge.

        The list is initialized by WorkingTree.set_merge_modified, which is 
        typically called after we make some automatic updates to the tree
        because of a merge.

        This returns a map of file_id->sha1, containing only files which are
        still in the working inventory and have that text hash.
        """
        try:
            hashfile = self._transport.get('merge-hashes')
        except errors.NoSuchFile:
            return {}
        try:
            merge_hashes = {}
            try:
                if hashfile.next() != MERGE_MODIFIED_HEADER_1 + '\n':
                    raise errors.MergeModifiedFormatError()
            except StopIteration:
                raise errors.MergeModifiedFormatError()
            for s in RioReader(hashfile):
                # RioReader reads in Unicode, so convert file_ids back to utf8
                file_id = osutils.safe_file_id(s.get("file_id"), warn=False)
                if file_id not in self.inventory:
                    continue
                text_hash = s.get("hash")
                if text_hash == self.get_file_sha1(file_id):
                    merge_hashes[file_id] = text_hash
            return merge_hashes
        finally:
            hashfile.close()

    @needs_write_lock
    def mkdir(self, path, file_id=None):
        """See MutableTree.mkdir()."""
        if file_id is None:
            file_id = generate_ids.gen_file_id(os.path.basename(path))
        os.mkdir(self.abspath(path))
        self.add(path, file_id, 'directory')
        return file_id

    def get_symlink_target(self, file_id):
        return os.readlink(self.id2abspath(file_id))

    @needs_write_lock
    def subsume(self, other_tree):
        def add_children(inventory, entry):
            for child_entry in entry.children.values():
                inventory._byid[child_entry.file_id] = child_entry
                if child_entry.kind == 'directory':
                    add_children(inventory, child_entry)
        if other_tree.get_root_id() == self.get_root_id():
            raise errors.BadSubsumeSource(self, other_tree,
                                          'Trees have the same root')
        try:
            other_tree_path = self.relpath(other_tree.basedir)
        except errors.PathNotChild:
            raise errors.BadSubsumeSource(self, other_tree,
                'Tree is not contained by the other')
        new_root_parent = self.path2id(osutils.dirname(other_tree_path))
        if new_root_parent is None:
            raise errors.BadSubsumeSource(self, other_tree,
                'Parent directory is not versioned.')
        # We need to ensure that the result of a fetch will have a
        # versionedfile for the other_tree root, and only fetching into
        # RepositoryKnit2 guarantees that.
        if not self.branch.repository.supports_rich_root():
            raise errors.SubsumeTargetNeedsUpgrade(other_tree)
        other_tree.lock_tree_write()
        try:
            new_parents = other_tree.get_parent_ids()
            other_root = other_tree.inventory.root
            other_root.parent_id = new_root_parent
            other_root.name = osutils.basename(other_tree_path)
            self.inventory.add(other_root)
            add_children(self.inventory, other_root)
            self._write_inventory(self.inventory)
            # normally we don't want to fetch whole repositories, but i think
            # here we really do want to consolidate the whole thing.
            for parent_id in other_tree.get_parent_ids():
                self.branch.fetch(other_tree.branch, parent_id)
                self.add_parent_tree_id(parent_id)
        finally:
            other_tree.unlock()
        other_tree.bzrdir.retire_bzrdir()

    def _setup_directory_is_tree_reference(self):
        if self._branch.repository._format.supports_tree_reference:
            self._directory_is_tree_reference = \
                self._directory_may_be_tree_reference
        else:
            self._directory_is_tree_reference = \
                self._directory_is_never_tree_reference

    def _directory_is_never_tree_reference(self, relpath):
        return False

    def _directory_may_be_tree_reference(self, relpath):
        # as a special case, if a directory contains control files then 
        # it's a tree reference, except that the root of the tree is not
        return relpath and osutils.isdir(self.abspath(relpath) + u"/.bzr")
        # TODO: We could ask all the control formats whether they
        # recognize this directory, but at the moment there's no cheap api
        # to do that.  Since we probably can only nest bzr checkouts and
        # they always use this name it's ok for now.  -- mbp 20060306
        #
        # FIXME: There is an unhandled case here of a subdirectory
        # containing .bzr but not a branch; that will probably blow up
        # when you try to commit it.  It might happen if there is a
        # checkout in a subdirectory.  This can be avoided by not adding
        # it.  mbp 20070306

    @needs_tree_write_lock
    def extract(self, file_id, format=None):
        """Extract a subtree from this tree.
        
        A new branch will be created, relative to the path for this tree.
        """
        self.flush()
        def mkdirs(path):
            segments = osutils.splitpath(path)
            transport = self.branch.bzrdir.root_transport
            for name in segments:
                transport = transport.clone(name)
                transport.ensure_base()
            return transport
            
        sub_path = self.id2path(file_id)
        branch_transport = mkdirs(sub_path)
        if format is None:
            format = self.bzrdir.cloning_metadir()
        branch_transport.ensure_base()
        branch_bzrdir = format.initialize_on_transport(branch_transport)
        try:
            repo = branch_bzrdir.find_repository()
        except errors.NoRepositoryPresent:
            repo = branch_bzrdir.create_repository()
        if not repo.supports_rich_root():
            raise errors.RootNotRich()
        new_branch = branch_bzrdir.create_branch()
        new_branch.pull(self.branch)
        for parent_id in self.get_parent_ids():
            new_branch.fetch(self.branch, parent_id)
        tree_transport = self.bzrdir.root_transport.clone(sub_path)
        if tree_transport.base != branch_transport.base:
            tree_bzrdir = format.initialize_on_transport(tree_transport)
            branch.BranchReferenceFormat().initialize(tree_bzrdir, new_branch)
        else:
            tree_bzrdir = branch_bzrdir
        wt = tree_bzrdir.create_workingtree(NULL_REVISION)
        wt.set_parent_ids(self.get_parent_ids())
        my_inv = self.inventory
        child_inv = Inventory(root_id=None)
        new_root = my_inv[file_id]
        my_inv.remove_recursive_id(file_id)
        new_root.parent_id = None
        child_inv.add(new_root)
        self._write_inventory(my_inv)
        wt._write_inventory(child_inv)
        return wt

    def _serialize(self, inventory, out_file):
        xml5.serializer_v5.write_inventory(self._inventory, out_file,
            working=True)

    def _deserialize(selt, in_file):
        return xml5.serializer_v5.read_inventory(in_file)

    def flush(self):
        """Write the in memory inventory to disk."""
        # TODO: Maybe this should only write on dirty ?
        if self._control_files._lock_mode != 'w':
            raise errors.NotWriteLocked(self)
        sio = StringIO()
        self._serialize(self._inventory, sio)
        sio.seek(0)
        self._transport.put_file('inventory', sio,
            mode=self._control_files._file_mode)
        self._inventory_is_modified = False

    def _kind(self, relpath):
        return osutils.file_kind(self.abspath(relpath))

    def list_files(self, include_root=False):
        """Recursively list all files as (path, class, kind, id, entry).

        Lists, but does not descend into unversioned directories.

        This does not include files that have been deleted in this
        tree.

        Skips the control directory.
        """
        # list_files is an iterator, so @needs_read_lock doesn't work properly
        # with it. So callers should be careful to always read_lock the tree.
        if not self.is_locked():
            raise errors.ObjectNotLocked(self)

        inv = self.inventory
        if include_root is True:
            yield ('', 'V', 'directory', inv.root.file_id, inv.root)
        # Convert these into local objects to save lookup times
        pathjoin = osutils.pathjoin
        file_kind = self._kind

        # transport.base ends in a slash, we want the piece
        # between the last two slashes
        transport_base_dir = self.bzrdir.transport.base.rsplit('/', 2)[1]

        fk_entries = {'directory':TreeDirectory, 'file':TreeFile, 'symlink':TreeLink}

        # directory file_id, relative path, absolute path, reverse sorted children
        children = os.listdir(self.basedir)
        children.sort()
        # jam 20060527 The kernel sized tree seems equivalent whether we 
        # use a deque and popleft to keep them sorted, or if we use a plain
        # list and just reverse() them.
        children = collections.deque(children)
        stack = [(inv.root.file_id, u'', self.basedir, children)]
        while stack:
            from_dir_id, from_dir_relpath, from_dir_abspath, children = stack[-1]

            while children:
                f = children.popleft()
                ## TODO: If we find a subdirectory with its own .bzr
                ## directory, then that is a separate tree and we
                ## should exclude it.

                # the bzrdir for this tree
                if transport_base_dir == f:
                    continue

                # we know that from_dir_relpath and from_dir_abspath never end in a slash
                # and 'f' doesn't begin with one, we can do a string op, rather
                # than the checks of pathjoin(), all relative paths will have an extra slash
                # at the beginning
                fp = from_dir_relpath + '/' + f

                # absolute path
                fap = from_dir_abspath + '/' + f
                
                f_ie = inv.get_child(from_dir_id, f)
                if f_ie:
                    c = 'V'
                elif self.is_ignored(fp[1:]):
                    c = 'I'
                else:
                    # we may not have found this file, because of a unicode issue
                    f_norm, can_access = osutils.normalized_filename(f)
                    if f == f_norm or not can_access:
                        # No change, so treat this file normally
                        c = '?'
                    else:
                        # this file can be accessed by a normalized path
                        # check again if it is versioned
                        # these lines are repeated here for performance
                        f = f_norm
                        fp = from_dir_relpath + '/' + f
                        fap = from_dir_abspath + '/' + f
                        f_ie = inv.get_child(from_dir_id, f)
                        if f_ie:
                            c = 'V'
                        elif self.is_ignored(fp[1:]):
                            c = 'I'
                        else:
                            c = '?'

                fk = file_kind(fap)

                # make a last minute entry
                if f_ie:
                    yield fp[1:], c, fk, f_ie.file_id, f_ie
                else:
                    try:
                        yield fp[1:], c, fk, None, fk_entries[fk]()
                    except KeyError:
                        yield fp[1:], c, fk, None, TreeEntry()
                    continue
                
                if fk != 'directory':
                    continue

                # But do this child first
                new_children = os.listdir(fap)
                new_children.sort()
                new_children = collections.deque(new_children)
                stack.append((f_ie.file_id, fp, fap, new_children))
                # Break out of inner loop,
                # so that we start outer loop with child
                break
            else:
                # if we finished all children, pop it off the stack
                stack.pop()

    @needs_tree_write_lock
    def move(self, from_paths, to_dir=None, after=False, **kwargs):
        """Rename files.

        to_dir must exist in the inventory.

        If to_dir exists and is a directory, the files are moved into
        it, keeping their old names.  

        Note that to_dir is only the last component of the new name;
        this doesn't change the directory.

        For each entry in from_paths the move mode will be determined
        independently.

        The first mode moves the file in the filesystem and updates the
        inventory. The second mode only updates the inventory without
        touching the file on the filesystem. This is the new mode introduced
        in version 0.15.

        move uses the second mode if 'after == True' and the target is not
        versioned but present in the working tree.

        move uses the second mode if 'after == False' and the source is
        versioned but no longer in the working tree, and the target is not
        versioned but present in the working tree.

        move uses the first mode if 'after == False' and the source is
        versioned and present in the working tree, and the target is not
        versioned and not present in the working tree.

        Everything else results in an error.

        This returns a list of (from_path, to_path) pairs for each
        entry that is moved.
        """
        rename_entries = []
        rename_tuples = []

        # check for deprecated use of signature
        if to_dir is None:
            to_dir = kwargs.get('to_name', None)
            if to_dir is None:
                raise TypeError('You must supply a target directory')
            else:
                symbol_versioning.warn('The parameter to_name was deprecated'
                                       ' in version 0.13. Use to_dir instead',
                                       DeprecationWarning)

        # check destination directory
        if isinstance(from_paths, basestring):
            raise ValueError()
        inv = self.inventory
        to_abs = self.abspath(to_dir)
        if not isdir(to_abs):
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotADirectory(to_abs))
        if not self.has_filename(to_dir):
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotInWorkingDirectory(to_dir))
        to_dir_id = inv.path2id(to_dir)
        if to_dir_id is None:
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotVersionedError(path=str(to_dir)))

        to_dir_ie = inv[to_dir_id]
        if to_dir_ie.kind != 'directory':
            raise errors.BzrMoveFailedError('',to_dir,
                errors.NotADirectory(to_abs))

        # create rename entries and tuples
        for from_rel in from_paths:
            from_tail = splitpath(from_rel)[-1]
            from_id = inv.path2id(from_rel)
            if from_id is None:
                raise errors.BzrMoveFailedError(from_rel,to_dir,
                    errors.NotVersionedError(path=str(from_rel)))

            from_entry = inv[from_id]
            from_parent_id = from_entry.parent_id
            to_rel = pathjoin(to_dir, from_tail)
            rename_entry = WorkingTree._RenameEntry(from_rel=from_rel,
                                         from_id=from_id,
                                         from_tail=from_tail,
                                         from_parent_id=from_parent_id,
                                         to_rel=to_rel, to_tail=from_tail,
                                         to_parent_id=to_dir_id)
            rename_entries.append(rename_entry)
            rename_tuples.append((from_rel, to_rel))

        # determine which move mode to use. checks also for movability
        rename_entries = self._determine_mv_mode(rename_entries, after)

        original_modified = self._inventory_is_modified
        try:
            if len(from_paths):
                self._inventory_is_modified = True
            self._move(rename_entries)
        except:
            # restore the inventory on error
            self._inventory_is_modified = original_modified
            raise
        self._write_inventory(inv)
        return rename_tuples

    def _determine_mv_mode(self, rename_entries, after=False):
        """Determines for each from-to pair if both inventory and working tree
        or only the inventory has to be changed.

        Also does basic plausability tests.
        """
        inv = self.inventory

        for rename_entry in rename_entries:
            # store to local variables for easier reference
            from_rel = rename_entry.from_rel
            from_id = rename_entry.from_id
            to_rel = rename_entry.to_rel
            to_id = inv.path2id(to_rel)
            only_change_inv = False

            # check the inventory for source and destination
            if from_id is None:
                raise errors.BzrMoveFailedError(from_rel,to_rel,
                    errors.NotVersionedError(path=str(from_rel)))
            if to_id is not None:
                raise errors.BzrMoveFailedError(from_rel,to_rel,
                    errors.AlreadyVersionedError(path=str(to_rel)))

            # try to determine the mode for rename (only change inv or change
            # inv and file system)
            if after:
                if not self.has_filename(to_rel):
                    raise errors.BzrMoveFailedError(from_id,to_rel,
                        errors.NoSuchFile(path=str(to_rel),
                        extra="New file has not been created yet"))
                only_change_inv = True
            elif not self.has_filename(from_rel) and self.has_filename(to_rel):
                only_change_inv = True
            elif self.has_filename(from_rel) and not self.has_filename(to_rel):
                only_change_inv = False
            elif (not self.case_sensitive
                  and from_rel.lower() == to_rel.lower()
                  and self.has_filename(from_rel)):
                only_change_inv = False
            else:
                # something is wrong, so lets determine what exactly
                if not self.has_filename(from_rel) and \
                   not self.has_filename(to_rel):
                    raise errors.BzrRenameFailedError(from_rel,to_rel,
                        errors.PathsDoNotExist(paths=(str(from_rel),
                        str(to_rel))))
                else:
                    raise errors.RenameFailedFilesExist(from_rel, to_rel)
            rename_entry.only_change_inv = only_change_inv
        return rename_entries

    def _move(self, rename_entries):
        """Moves a list of files.

        Depending on the value of the flag 'only_change_inv', the
        file will be moved on the file system or not.
        """
        inv = self.inventory
        moved = []

        for entry in rename_entries:
            try:
                self._move_entry(entry)
            except:
                self._rollback_move(moved)
                raise
            moved.append(entry)

    def _rollback_move(self, moved):
        """Try to rollback a previous move in case of an filesystem error."""
        inv = self.inventory
        for entry in moved:
            try:
                self._move_entry(_RenameEntry(entry.to_rel, entry.from_id,
                    entry.to_tail, entry.to_parent_id, entry.from_rel,
                    entry.from_tail, entry.from_parent_id,
                    entry.only_change_inv))
            except errors.BzrMoveFailedError, e:
                raise errors.BzrMoveFailedError( '', '', "Rollback failed."
                        " The working tree is in an inconsistent state."
                        " Please consider doing a 'bzr revert'."
                        " Error message is: %s" % e)

    def _move_entry(self, entry):
        inv = self.inventory
        from_rel_abs = self.abspath(entry.from_rel)
        to_rel_abs = self.abspath(entry.to_rel)
        if from_rel_abs == to_rel_abs:
            raise errors.BzrMoveFailedError(entry.from_rel, entry.to_rel,
                "Source and target are identical.")

        if not entry.only_change_inv:
            try:
                osutils.rename(from_rel_abs, to_rel_abs)
            except OSError, e:
                raise errors.BzrMoveFailedError(entry.from_rel,
                    entry.to_rel, e[1])
        inv.rename(entry.from_id, entry.to_parent_id, entry.to_tail)

    @needs_tree_write_lock
    def rename_one(self, from_rel, to_rel, after=False):
        """Rename one file.

        This can change the directory or the filename or both.

        rename_one has several 'modes' to work. First, it can rename a physical
        file and change the file_id. That is the normal mode. Second, it can
        only change the file_id without touching any physical file. This is
        the new mode introduced in version 0.15.

        rename_one uses the second mode if 'after == True' and 'to_rel' is not
        versioned but present in the working tree.

        rename_one uses the second mode if 'after == False' and 'from_rel' is
        versioned but no longer in the working tree, and 'to_rel' is not
        versioned but present in the working tree.

        rename_one uses the first mode if 'after == False' and 'from_rel' is
        versioned and present in the working tree, and 'to_rel' is not
        versioned and not present in the working tree.

        Everything else results in an error.
        """
        inv = self.inventory
        rename_entries = []

        # create rename entries and tuples
        from_tail = splitpath(from_rel)[-1]
        from_id = inv.path2id(from_rel)
        if from_id is None:
            raise errors.BzrRenameFailedError(from_rel,to_rel,
                errors.NotVersionedError(path=str(from_rel)))
        from_entry = inv[from_id]
        from_parent_id = from_entry.parent_id
        to_dir, to_tail = os.path.split(to_rel)
        to_dir_id = inv.path2id(to_dir)
        rename_entry = WorkingTree._RenameEntry(from_rel=from_rel,
                                     from_id=from_id,
                                     from_tail=from_tail,
                                     from_parent_id=from_parent_id,
                                     to_rel=to_rel, to_tail=to_tail,
                                     to_parent_id=to_dir_id)
        rename_entries.append(rename_entry)

        # determine which move mode to use. checks also for movability
        rename_entries = self._determine_mv_mode(rename_entries, after)

        # check if the target changed directory and if the target directory is
        # versioned
        if to_dir_id is None:
            raise errors.BzrMoveFailedError(from_rel,to_rel,
                errors.NotVersionedError(path=str(to_dir)))

        # all checks done. now we can continue with our actual work
        mutter('rename_one:\n'
               '  from_id   {%s}\n'
               '  from_rel: %r\n'
               '  to_rel:   %r\n'
               '  to_dir    %r\n'
               '  to_dir_id {%s}\n',
               from_id, from_rel, to_rel, to_dir, to_dir_id)

        self._move(rename_entries)
        self._write_inventory(inv)

    class _RenameEntry(object):
        def __init__(self, from_rel, from_id, from_tail, from_parent_id,
                     to_rel, to_tail, to_parent_id, only_change_inv=False):
            self.from_rel = from_rel
            self.from_id = from_id
            self.from_tail = from_tail
            self.from_parent_id = from_parent_id
            self.to_rel = to_rel
            self.to_tail = to_tail
            self.to_parent_id = to_parent_id
            self.only_change_inv = only_change_inv

    @needs_read_lock
    def unknowns(self):
        """Return all unknown files.

        These are files in the working directory that are not versioned or
        control files or ignored.
        """
        # force the extras method to be fully executed before returning, to 
        # prevent race conditions with the lock
        return iter(
            [subp for subp in self.extras() if not self.is_ignored(subp)])

    @needs_tree_write_lock
    def unversion(self, file_ids):
        """Remove the file ids in file_ids from the current versioned set.

        When a file_id is unversioned, all of its children are automatically
        unversioned.

        :param file_ids: The file ids to stop versioning.
        :raises: NoSuchId if any fileid is not currently versioned.
        """
        for file_id in file_ids:
            if self._inventory.has_id(file_id):
                self._inventory.remove_recursive_id(file_id)
            else:
                raise errors.NoSuchId(self, file_id)
        if len(file_ids):
            # in the future this should just set a dirty bit to wait for the 
            # final unlock. However, until all methods of workingtree start
            # with the current in -memory inventory rather than triggering 
            # a read, it is more complex - we need to teach read_inventory
            # to know when to read, and when to not read first... and possibly
            # to save first when the in memory one may be corrupted.
            # so for now, we just only write it if it is indeed dirty.
            # - RBC 20060907
            self._write_inventory(self._inventory)
    
    def _iter_conflicts(self):
        conflicted = set()
        for info in self.list_files():
            path = info[0]
            stem = get_conflicted_stem(path)
            if stem is None:
                continue
            if stem not in conflicted:
                conflicted.add(stem)
                yield stem

    @needs_write_lock
    def pull(self, source, overwrite=False, stop_revision=None,
             change_reporter=None, possible_transports=None):
        top_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        source.lock_read()
        try:
            pp = ProgressPhase("Pull phase", 2, top_pb)
            pp.next_phase()
            old_revision_info = self.branch.last_revision_info()
            basis_tree = self.basis_tree()
            count = self.branch.pull(source, overwrite, stop_revision,
                                     possible_transports=possible_transports)
            new_revision_info = self.branch.last_revision_info()
            if new_revision_info != old_revision_info:
                pp.next_phase()
                repository = self.branch.repository
                pb = bzrlib.ui.ui_factory.nested_progress_bar()
                basis_tree.lock_read()
                try:
                    new_basis_tree = self.branch.basis_tree()
                    merge.merge_inner(
                                self.branch,
                                new_basis_tree,
                                basis_tree,
                                this_tree=self,
                                pb=pb,
                                change_reporter=change_reporter)
                    if (basis_tree.inventory.root is None and
                        new_basis_tree.inventory.root is not None):
                        self.set_root_id(new_basis_tree.get_root_id())
                finally:
                    pb.finished()
                    basis_tree.unlock()
                # TODO - dedup parents list with things merged by pull ?
                # reuse the revisiontree we merged against to set the new
                # tree data.
                parent_trees = [(self.branch.last_revision(), new_basis_tree)]
                # we have to pull the merge trees out again, because 
                # merge_inner has set the ids. - this corner is not yet 
                # layered well enough to prevent double handling.
                # XXX TODO: Fix the double handling: telling the tree about
                # the already known parent data is wasteful.
                merges = self.get_parent_ids()[1:]
                parent_trees.extend([
                    (parent, repository.revision_tree(parent)) for
                     parent in merges])
                self.set_parent_trees(parent_trees)
            return count
        finally:
            source.unlock()
            top_pb.finished()

    @needs_write_lock
    def put_file_bytes_non_atomic(self, file_id, bytes):
        """See MutableTree.put_file_bytes_non_atomic."""
        stream = file(self.id2abspath(file_id), 'wb')
        try:
            stream.write(bytes)
        finally:
            stream.close()
        # TODO: update the hashcache here ?

    def extras(self):
        """Yield all unversioned files in this WorkingTree.

        If there are any unversioned directories then only the directory is
        returned, not all its children.  But if there are unversioned files
        under a versioned subdirectory, they are returned.

        Currently returned depth-first, sorted by name within directories.
        This is the same order used by 'osutils.walkdirs'.
        """
        ## TODO: Work from given directory downwards
        for path, dir_entry in self.inventory.directories():
            # mutter("search for unknowns in %r", path)
            dirabs = self.abspath(path)
            if not isdir(dirabs):
                # e.g. directory deleted
                continue

            fl = []
            for subf in os.listdir(dirabs):
                if subf == '.bzr':
                    continue
                if subf not in dir_entry.children:
                    try:
                        (subf_norm,
                         can_access) = osutils.normalized_filename(subf)
                    except UnicodeDecodeError:
                        path_os_enc = path.encode(osutils._fs_enc)
                        relpath = path_os_enc + '/' + subf
                        raise errors.BadFilenameEncoding(relpath,
                                                         osutils._fs_enc)
                    if subf_norm != subf and can_access:
                        if subf_norm not in dir_entry.children:
                            fl.append(subf_norm)
                    else:
                        fl.append(subf)
            
            fl.sort()
            for subf in fl:
                subp = pathjoin(path, subf)
                yield subp

    def ignored_files(self):
        """Yield list of PATH, IGNORE_PATTERN"""
        for subp in self.extras():
            pat = self.is_ignored(subp)
            if pat is not None:
                yield subp, pat

    def get_ignore_list(self):
        """Return list of ignore patterns.

        Cached in the Tree object after the first call.
        """
        ignoreset = getattr(self, '_ignoreset', None)
        if ignoreset is not None:
            return ignoreset

        ignore_globs = set()
        ignore_globs.update(ignores.get_runtime_ignores())
        ignore_globs.update(ignores.get_user_ignores())
        if self.has_filename(bzrlib.IGNORE_FILENAME):
            f = self.get_file_byname(bzrlib.IGNORE_FILENAME)
            try:
                ignore_globs.update(ignores.parse_ignore_file(f))
            finally:
                f.close()
        self._ignoreset = ignore_globs
        return ignore_globs

    def _flush_ignore_list_cache(self):
        """Resets the cached ignore list to force a cache rebuild."""
        self._ignoreset = None
        self._ignoreglobster = None

    def is_ignored(self, filename):
        r"""Check whether the filename matches an ignore pattern.

        Patterns containing '/' or '\' need to match the whole path;
        others match against only the last component.

        If the file is ignored, returns the pattern which caused it to
        be ignored, otherwise None.  So this can simply be used as a
        boolean if desired."""
        if getattr(self, '_ignoreglobster', None) is None:
            self._ignoreglobster = globbing.Globster(self.get_ignore_list())
        return self._ignoreglobster.match(filename)

    def kind(self, file_id):
        return file_kind(self.id2abspath(file_id))

    def stored_kind(self, file_id):
        """See Tree.stored_kind"""
        return self.inventory[file_id].kind

    def _comparison_data(self, entry, path):
        abspath = self.abspath(path)
        try:
            stat_value = os.lstat(abspath)
        except OSError, e:
            if getattr(e, 'errno', None) == errno.ENOENT:
                stat_value = None
                kind = None
                executable = False
            else:
                raise
        else:
            mode = stat_value.st_mode
            kind = osutils.file_kind_from_stat_mode(mode)
            if not supports_executable():
                executable = entry is not None and entry.executable
            else:
                executable = bool(stat.S_ISREG(mode) and stat.S_IEXEC & mode)
        return kind, executable, stat_value

    def _file_size(self, entry, stat_value):
        return stat_value.st_size

    def last_revision(self):
        """Return the last revision of the branch for this tree.

        This format tree does not support a separate marker for last-revision
        compared to the branch.

        See MutableTree.last_revision
        """
        return self._last_revision()

    @needs_read_lock
    def _last_revision(self):
        """helper for get_parent_ids."""
        return _mod_revision.ensure_null(self.branch.last_revision())

    def is_locked(self):
        return self._control_files.is_locked()

    def _must_be_locked(self):
        if not self.is_locked():
            raise errors.ObjectNotLocked(self)

    def lock_read(self):
        """See Branch.lock_read, and WorkingTree.unlock."""
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_read()
        try:
            return self._control_files.lock_read()
        except:
            self.branch.unlock()
            raise

    def lock_tree_write(self):
        """See MutableTree.lock_tree_write, and WorkingTree.unlock."""
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_read()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def lock_write(self):
        """See MutableTree.lock_write, and WorkingTree.unlock."""
        if not self.is_locked():
            self._reset_data()
        self.branch.lock_write()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def get_physical_lock_status(self):
        return self._control_files.get_physical_lock_status()

    def _basis_inventory_name(self):
        return 'basis-inventory-cache'

    def _reset_data(self):
        """Reset transient data that cannot be revalidated."""
        self._inventory_is_modified = False
        result = self._deserialize(self._transport.get('inventory'))
        self._set_inventory(result, dirty=False)

    @needs_tree_write_lock
    def set_last_revision(self, new_revision):
        """Change the last revision in the working tree."""
        if self._change_last_revision(new_revision):
            self._cache_basis_inventory(new_revision)

    def _change_last_revision(self, new_revision):
        """Template method part of set_last_revision to perform the change.
        
        This is used to allow WorkingTree3 instances to not affect branch
        when their last revision is set.
        """
        if _mod_revision.is_null(new_revision):
            self.branch.set_revision_history([])
            return False
        try:
            self.branch.generate_revision_history(new_revision)
        except errors.NoSuchRevision:
            # not present in the repo - dont try to set it deeper than the tip
            self.branch.set_revision_history([new_revision])
        return True

    def _write_basis_inventory(self, xml):
        """Write the basis inventory XML to the basis-inventory file"""
        path = self._basis_inventory_name()
        sio = StringIO(xml)
        self._transport.put_file(path, sio,
            mode=self._control_files._file_mode)

    def _create_basis_xml_from_inventory(self, revision_id, inventory):
        """Create the text that will be saved in basis-inventory"""
        inventory.revision_id = revision_id
        return xml7.serializer_v7.write_inventory_to_string(inventory)

    def _cache_basis_inventory(self, new_revision):
        """Cache new_revision as the basis inventory."""
        # TODO: this should allow the ready-to-use inventory to be passed in,
        # as commit already has that ready-to-use [while the format is the
        # same, that is].
        try:
            # this double handles the inventory - unpack and repack - 
            # but is easier to understand. We can/should put a conditional
            # in here based on whether the inventory is in the latest format
            # - perhaps we should repack all inventories on a repository
            # upgrade ?
            # the fast path is to copy the raw xml from the repository. If the
            # xml contains 'revision_id="', then we assume the right 
            # revision_id is set. We must check for this full string, because a
            # root node id can legitimately look like 'revision_id' but cannot
            # contain a '"'.
            xml = self.branch.repository.get_inventory_xml(new_revision)
            firstline = xml.split('\n', 1)[0]
            if (not 'revision_id="' in firstline or 
                'format="7"' not in firstline):
                inv = self.branch.repository.deserialise_inventory(
                    new_revision, xml)
                xml = self._create_basis_xml_from_inventory(new_revision, inv)
            self._write_basis_inventory(xml)
        except (errors.NoSuchRevision, errors.RevisionNotPresent):
            pass

    def read_basis_inventory(self):
        """Read the cached basis inventory."""
        path = self._basis_inventory_name()
        return self._transport.get_bytes(path)
        
    @needs_read_lock
    def read_working_inventory(self):
        """Read the working inventory.
        
        :raises errors.InventoryModified: read_working_inventory will fail
            when the current in memory inventory has been modified.
        """
        # conceptually this should be an implementation detail of the tree. 
        # XXX: Deprecate this.
        # ElementTree does its own conversion from UTF-8, so open in
        # binary.
        if self._inventory_is_modified:
            raise errors.InventoryModified(self)
        result = self._deserialize(self._transport.get('inventory'))
        self._set_inventory(result, dirty=False)
        return result

    @needs_tree_write_lock
    def remove(self, files, verbose=False, to_file=None, keep_files=True,
        force=False):
        """Remove nominated files from the working inventory.

        :files: File paths relative to the basedir.
        :keep_files: If true, the files will also be kept.
        :force: Delete files and directories, even if they are changed and
            even if the directories are not empty.
        """
        if isinstance(files, basestring):
            files = [files]

        inv_delta = []

        new_files=set()
        unknown_nested_files=set()

        def recurse_directory_to_add_files(directory):
            # Recurse directory and add all files
            # so we can check if they have changed.
            for parent_info, file_infos in\
                self.walkdirs(directory):
                for relpath, basename, kind, lstat, fileid, kind in file_infos:
                    # Is it versioned or ignored?
                    if self.path2id(relpath) or self.is_ignored(relpath):
                        # Add nested content for deletion.
                        new_files.add(relpath)
                    else:
                        # Files which are not versioned and not ignored
                        # should be treated as unknown.
                        unknown_nested_files.add((relpath, None, kind))

        for filename in files:
            # Get file name into canonical form.
            abspath = self.abspath(filename)
            filename = self.relpath(abspath)
            if len(filename) > 0:
                new_files.add(filename)
                recurse_directory_to_add_files(filename)

        files = list(new_files)

        if len(files) == 0:
            return # nothing to do

        # Sort needed to first handle directory content before the directory
        files.sort(reverse=True)

        # Bail out if we are going to delete files we shouldn't
        if not keep_files and not force:
            has_changed_files = len(unknown_nested_files) > 0
            if not has_changed_files:
                for (file_id, path, content_change, versioned, parent_id, name,
                     kind, executable) in self.iter_changes(self.basis_tree(),
                         include_unchanged=True, require_versioned=False,
                         want_unversioned=True, specific_files=files):
                    if versioned == (False, False):
                        # The record is unknown ...
                        if not self.is_ignored(path[1]):
                            # ... but not ignored
                            has_changed_files = True
                            break
                    elif content_change and (kind[1] is not None):
                        # Versioned and changed, but not deleted
                        has_changed_files = True
                        break

            if has_changed_files:
                # Make delta show ALL applicable changes in error message.
                tree_delta = self.changes_from(self.basis_tree(),
                    require_versioned=False, want_unversioned=True,
                    specific_files=files)
                for unknown_file in unknown_nested_files:
                    if unknown_file not in tree_delta.unversioned:
                        tree_delta.unversioned.extend((unknown_file,))
                raise errors.BzrRemoveChangedFilesError(tree_delta)

        # Build inv_delta and delete files where applicaple,
        # do this before any modifications to inventory.
        for f in files:
            fid = self.path2id(f)
            message = None
            if not fid:
                message = "%s is not versioned." % (f,)
            else:
                if verbose:
                    # having removed it, it must be either ignored or unknown
                    if self.is_ignored(f):
                        new_status = 'I'
                    else:
                        new_status = '?'
                    textui.show_status(new_status, self.kind(fid), f,
                                       to_file=to_file)
                # Unversion file
                inv_delta.append((f, None, fid, None))
                message = "removed %s" % (f,)

            if not keep_files:
                abs_path = self.abspath(f)
                if osutils.lexists(abs_path):
                    if (osutils.isdir(abs_path) and
                        len(os.listdir(abs_path)) > 0):
                        if force:
                            osutils.rmtree(abs_path)
                        else:
                            message = "%s is not an empty directory "\
                                "and won't be deleted." % (f,)
                    else:
                        osutils.delete_any(abs_path)
                        message = "deleted %s" % (f,)
                elif message is not None:
                    # Only care if we haven't done anything yet.
                    message = "%s does not exist." % (f,)

            # Print only one message (if any) per file.
            if message is not None:
                note(message)
        self.apply_inventory_delta(inv_delta)

    @needs_tree_write_lock
    def revert(self, filenames=None, old_tree=None, backups=True,
               pb=DummyProgress(), report_changes=False):
        from bzrlib.conflicts import resolve
        if filenames == []:
            filenames = None
            symbol_versioning.warn('Using [] to revert all files is deprecated'
                ' as of bzr 0.91.  Please use None (the default) instead.',
                DeprecationWarning, stacklevel=2)
        if old_tree is None:
            basis_tree = self.basis_tree()
            basis_tree.lock_read()
            old_tree = basis_tree
        else:
            basis_tree = None
        try:
            conflicts = transform.revert(self, old_tree, filenames, backups, pb,
                                         report_changes)
            if filenames is None and len(self.get_parent_ids()) > 1:
                parent_trees = []
                last_revision = self.last_revision()
                if last_revision != NULL_REVISION:
                    if basis_tree is None:
                        basis_tree = self.basis_tree()
                        basis_tree.lock_read()
                    parent_trees.append((last_revision, basis_tree))
                self.set_parent_trees(parent_trees)
                resolve(self)
            else:
                resolve(self, filenames, ignore_misses=True, recursive=True)
        finally:
            if basis_tree is not None:
                basis_tree.unlock()
        return conflicts

    def revision_tree(self, revision_id):
        """See Tree.revision_tree.

        WorkingTree can supply revision_trees for the basis revision only
        because there is only one cached inventory in the bzr directory.
        """
        if revision_id == self.last_revision():
            try:
                xml = self.read_basis_inventory()
            except errors.NoSuchFile:
                pass
            else:
                try:
                    inv = xml7.serializer_v7.read_inventory_from_string(xml)
                    # dont use the repository revision_tree api because we want
                    # to supply the inventory.
                    if inv.revision_id == revision_id:
                        return revisiontree.RevisionTree(self.branch.repository,
                            inv, revision_id)
                except errors.BadInventoryFormat:
                    pass
        # raise if there was no inventory, or if we read the wrong inventory.
        raise errors.NoSuchRevisionInTree(self, revision_id)

    # XXX: This method should be deprecated in favour of taking in a proper
    # new Inventory object.
    @needs_tree_write_lock
    def set_inventory(self, new_inventory_list):
        from bzrlib.inventory import (Inventory,
                                      InventoryDirectory,
                                      InventoryEntry,
                                      InventoryFile,
                                      InventoryLink)
        inv = Inventory(self.get_root_id())
        for path, file_id, parent, kind in new_inventory_list:
            name = os.path.basename(path)
            if name == "":
                continue
            # fixme, there should be a factory function inv,add_?? 
            if kind == 'directory':
                inv.add(InventoryDirectory(file_id, name, parent))
            elif kind == 'file':
                inv.add(InventoryFile(file_id, name, parent))
            elif kind == 'symlink':
                inv.add(InventoryLink(file_id, name, parent))
            else:
                raise errors.BzrError("unknown kind %r" % kind)
        self._write_inventory(inv)

    @needs_tree_write_lock
    def set_root_id(self, file_id):
        """Set the root id for this tree."""
        # for compatability 
        if file_id is None:
            raise ValueError(
                'WorkingTree.set_root_id with fileid=None')
        file_id = osutils.safe_file_id(file_id)
        self._set_root_id(file_id)

    def _set_root_id(self, file_id):
        """Set the root id for this tree, in a format specific manner.

        :param file_id: The file id to assign to the root. It must not be 
            present in the current inventory or an error will occur. It must
            not be None, but rather a valid file id.
        """
        inv = self._inventory
        orig_root_id = inv.root.file_id
        # TODO: it might be nice to exit early if there was nothing
        # to do, saving us from trigger a sync on unlock.
        self._inventory_is_modified = True
        # we preserve the root inventory entry object, but
        # unlinkit from the byid index
        del inv._byid[inv.root.file_id]
        inv.root.file_id = file_id
        # and link it into the index with the new changed id.
        inv._byid[inv.root.file_id] = inv.root
        # and finally update all children to reference the new id.
        # XXX: this should be safe to just look at the root.children
        # list, not the WHOLE INVENTORY.
        for fid in inv:
            entry = inv[fid]
            if entry.parent_id == orig_root_id:
                entry.parent_id = inv.root.file_id

    def unlock(self):
        """See Branch.unlock.
        
        WorkingTree locking just uses the Branch locking facilities.
        This is current because all working trees have an embedded branch
        within them. IF in the future, we were to make branch data shareable
        between multiple working trees, i.e. via shared storage, then we 
        would probably want to lock both the local tree, and the branch.
        """
        raise NotImplementedError(self.unlock)

    def update(self, change_reporter=None, possible_transports=None):
        """Update a working tree along its branch.

        This will update the branch if its bound too, which means we have
        multiple trees involved:

        - The new basis tree of the master.
        - The old basis tree of the branch.
        - The old basis tree of the working tree.
        - The current working tree state.

        Pathologically, all three may be different, and non-ancestors of each
        other.  Conceptually we want to:

        - Preserve the wt.basis->wt.state changes
        - Transform the wt.basis to the new master basis.
        - Apply a merge of the old branch basis to get any 'local' changes from
          it into the tree.
        - Restore the wt.basis->wt.state changes.

        There isn't a single operation at the moment to do that, so we:
        - Merge current state -> basis tree of the master w.r.t. the old tree
          basis.
        - Do a 'normal' merge of the old branch basis if it is relevant.
        """
        if self.branch.get_bound_location() is not None:
            self.lock_write()
            update_branch = True
        else:
            self.lock_tree_write()
            update_branch = False
        try:
            if update_branch:
                old_tip = self.branch.update(possible_transports)
            else:
                old_tip = None
            return self._update_tree(old_tip, change_reporter)
        finally:
            self.unlock()

    @needs_tree_write_lock
    def _update_tree(self, old_tip=None, change_reporter=None):
        """Update a tree to the master branch.

        :param old_tip: if supplied, the previous tip revision the branch,
            before it was changed to the master branch's tip.
        """
        # here if old_tip is not None, it is the old tip of the branch before
        # it was updated from the master branch. This should become a pending
        # merge in the working tree to preserve the user existing work.  we
        # cant set that until we update the working trees last revision to be
        # one from the new branch, because it will just get absorbed by the
        # parent de-duplication logic.
        # 
        # We MUST save it even if an error occurs, because otherwise the users
        # local work is unreferenced and will appear to have been lost.
        # 
        result = 0
        try:
            last_rev = self.get_parent_ids()[0]
        except IndexError:
            last_rev = _mod_revision.NULL_REVISION
        if last_rev != _mod_revision.ensure_null(self.branch.last_revision()):
            # merge tree state up to new branch tip.
            basis = self.basis_tree()
            basis.lock_read()
            try:
                to_tree = self.branch.basis_tree()
                if basis.inventory.root is None:
                    self.set_root_id(to_tree.get_root_id())
                    self.flush()
                result += merge.merge_inner(
                                      self.branch,
                                      to_tree,
                                      basis,
                                      this_tree=self,
                                      change_reporter=change_reporter)
            finally:
                basis.unlock()
            # TODO - dedup parents list with things merged by pull ?
            # reuse the tree we've updated to to set the basis:
            parent_trees = [(self.branch.last_revision(), to_tree)]
            merges = self.get_parent_ids()[1:]
            # Ideally we ask the tree for the trees here, that way the working
            # tree can decide whether to give us teh entire tree or give us a
            # lazy initialised tree. dirstate for instance will have the trees
            # in ram already, whereas a last-revision + basis-inventory tree
            # will not, but also does not need them when setting parents.
            for parent in merges:
                parent_trees.append(
                    (parent, self.branch.repository.revision_tree(parent)))
            if (old_tip is not None and not _mod_revision.is_null(old_tip)):
                parent_trees.append(
                    (old_tip, self.branch.repository.revision_tree(old_tip)))
            self.set_parent_trees(parent_trees)
            last_rev = parent_trees[0][0]
        else:
            # the working tree had the same last-revision as the master
            # branch did. We may still have pivot local work from the local
            # branch into old_tip:
            if (old_tip is not None and not _mod_revision.is_null(old_tip)):
                self.add_parent_tree_id(old_tip)
        if (old_tip is not None and not _mod_revision.is_null(old_tip)
            and old_tip != last_rev):
            # our last revision was not the prior branch last revision
            # and we have converted that last revision to a pending merge.
            # base is somewhere between the branch tip now
            # and the now pending merge

            # Since we just modified the working tree and inventory, flush out
            # the current state, before we modify it again.
            # TODO: jam 20070214 WorkingTree3 doesn't require this, dirstate
            #       requires it only because TreeTransform directly munges the
            #       inventory and calls tree._write_inventory(). Ultimately we
            #       should be able to remove this extra flush.
            self.flush()
            graph = self.branch.repository.get_graph()
            base_rev_id = graph.find_unique_lca(self.branch.last_revision(),
                                                old_tip)
            base_tree = self.branch.repository.revision_tree(base_rev_id)
            other_tree = self.branch.repository.revision_tree(old_tip)
            result += merge.merge_inner(
                                  self.branch,
                                  other_tree,
                                  base_tree,
                                  this_tree=self,
                                  change_reporter=change_reporter)
        return result

    def _write_hashcache_if_dirty(self):
        """Write out the hashcache if it is dirty."""
        if self._hashcache.needs_write:
            try:
                self._hashcache.write()
            except OSError, e:
                if e.errno not in (errno.EPERM, errno.EACCES):
                    raise
                # TODO: jam 20061219 Should this be a warning? A single line
                #       warning might be sufficient to let the user know what
                #       is going on.
                mutter('Could not write hashcache for %s\nError: %s',
                       self._hashcache.cache_file_name(), e)

    @needs_tree_write_lock
    def _write_inventory(self, inv):
        """Write inventory as the current inventory."""
        self._set_inventory(inv, dirty=True)
        self.flush()

    def set_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.set_conflicts, self)

    def add_conflicts(self, arg):
        raise errors.UnsupportedOperation(self.add_conflicts, self)

    @needs_read_lock
    def conflicts(self):
        conflicts = _mod_conflicts.ConflictList()
        for conflicted in self._iter_conflicts():
            text = True
            try:
                if file_kind(self.abspath(conflicted)) != "file":
                    text = False
            except errors.NoSuchFile:
                text = False
            if text is True:
                for suffix in ('.THIS', '.OTHER'):
                    try:
                        kind = file_kind(self.abspath(conflicted+suffix))
                        if kind != "file":
                            text = False
                    except errors.NoSuchFile:
                        text = False
                    if text == False:
                        break
            ctype = {True: 'text conflict', False: 'contents conflict'}[text]
            conflicts.append(_mod_conflicts.Conflict.factory(ctype,
                             path=conflicted,
                             file_id=self.path2id(conflicted)))
        return conflicts

    def walkdirs(self, prefix=""):
        """Walk the directories of this tree.

        returns a generator which yields items in the form:
                ((curren_directory_path, fileid),
                 [(file1_path, file1_name, file1_kind, (lstat), file1_id,
                   file1_kind), ... ])

        This API returns a generator, which is only valid during the current
        tree transaction - within a single lock_read or lock_write duration.

        If the tree is not locked, it may cause an error to be raised,
        depending on the tree implementation.
        """
        disk_top = self.abspath(prefix)
        if disk_top.endswith('/'):
            disk_top = disk_top[:-1]
        top_strip_len = len(disk_top) + 1
        inventory_iterator = self._walkdirs(prefix)
        disk_iterator = osutils.walkdirs(disk_top, prefix)
        try:
            current_disk = disk_iterator.next()
            disk_finished = False
        except OSError, e:
            if not (e.errno == errno.ENOENT or
                (sys.platform == 'win32' and e.errno == ERROR_PATH_NOT_FOUND)):
                raise
            current_disk = None
            disk_finished = True
        try:
            current_inv = inventory_iterator.next()
            inv_finished = False
        except StopIteration:
            current_inv = None
            inv_finished = True
        while not inv_finished or not disk_finished:
            if current_disk:
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = current_disk
            else:
                ((cur_disk_dir_relpath, cur_disk_dir_path_from_top),
                    cur_disk_dir_content) = ((None, None), None)
            if not disk_finished:
                # strip out .bzr dirs
                if (cur_disk_dir_path_from_top[top_strip_len:] == '' and
                    len(cur_disk_dir_content) > 0):
                    # osutils.walkdirs can be made nicer -
                    # yield the path-from-prefix rather than the pathjoined
                    # value.
                    bzrdir_loc = bisect_left(cur_disk_dir_content,
                        ('.bzr', '.bzr'))
                    if (bzrdir_loc < len(cur_disk_dir_content)
                        and cur_disk_dir_content[bzrdir_loc][0] == '.bzr'):
                        # we dont yield the contents of, or, .bzr itself.
                        del cur_disk_dir_content[bzrdir_loc]
            if inv_finished:
                # everything is unknown
                direction = 1
            elif disk_finished:
                # everything is missing
                direction = -1
            else:
                direction = cmp(current_inv[0][0], cur_disk_dir_relpath)
            if direction > 0:
                # disk is before inventory - unknown
                dirblock = [(relpath, basename, kind, stat, None, None) for
                    relpath, basename, kind, stat, top_path in
                    cur_disk_dir_content]
                yield (cur_disk_dir_relpath, None), dirblock
                try:
                    current_disk = disk_iterator.next()
                except StopIteration:
                    disk_finished = True
            elif direction < 0:
                # inventory is before disk - missing.
                dirblock = [(relpath, basename, 'unknown', None, fileid, kind)
                    for relpath, basename, dkind, stat, fileid, kind in
                    current_inv[1]]
                yield (current_inv[0][0], current_inv[0][1]), dirblock
                try:
                    current_inv = inventory_iterator.next()
                except StopIteration:
                    inv_finished = True
            else:
                # versioned present directory
                # merge the inventory and disk data together
                dirblock = []
                for relpath, subiterator in itertools.groupby(sorted(
                    current_inv[1] + cur_disk_dir_content,
                    key=operator.itemgetter(0)), operator.itemgetter(1)):
                    path_elements = list(subiterator)
                    if len(path_elements) == 2:
                        inv_row, disk_row = path_elements
                        # versioned, present file
                        dirblock.append((inv_row[0],
                            inv_row[1], disk_row[2],
                            disk_row[3], inv_row[4],
                            inv_row[5]))
                    elif len(path_elements[0]) == 5:
                        # unknown disk file
                        dirblock.append((path_elements[0][0],
                            path_elements[0][1], path_elements[0][2],
                            path_elements[0][3], None, None))
                    elif len(path_elements[0]) == 6:
                        # versioned, absent file.
                        dirblock.append((path_elements[0][0],
                            path_elements[0][1], 'unknown', None,
                            path_elements[0][4], path_elements[0][5]))
                    else:
                        raise NotImplementedError('unreachable code')
                yield current_inv[0], dirblock
                try:
                    current_inv = inventory_iterator.next()
                except StopIteration:
                    inv_finished = True
                try:
                    current_disk = disk_iterator.next()
                except StopIteration:
                    disk_finished = True

    def _walkdirs(self, prefix=""):
        """Walk the directories of this tree.

           :prefix: is used as the directrory to start with.
           returns a generator which yields items in the form:
                ((curren_directory_path, fileid),
                 [(file1_path, file1_name, file1_kind, None, file1_id,
                   file1_kind), ... ])
        """
        _directory = 'directory'
        # get the root in the inventory
        inv = self.inventory
        top_id = inv.path2id(prefix)
        if top_id is None:
            pending = []
        else:
            pending = [(prefix, '', _directory, None, top_id, None)]
        while pending:
            dirblock = []
            currentdir = pending.pop()
            # 0 - relpath, 1- basename, 2- kind, 3- stat, 4-id, 5-kind
            top_id = currentdir[4]
            if currentdir[0]:
                relroot = currentdir[0] + '/'
            else:
                relroot = ""
            # FIXME: stash the node in pending
            entry = inv[top_id]
            if entry.kind == 'directory':
                for name, child in entry.sorted_children():
                    dirblock.append((relroot + name, name, child.kind, None,
                        child.file_id, child.kind
                        ))
            yield (currentdir[0], entry.file_id), dirblock
            # push the user specified dirs from dirblock
            for dir in reversed(dirblock):
                if dir[2] == _directory:
                    pending.append(dir)

    @needs_tree_write_lock
    def auto_resolve(self):
        """Automatically resolve text conflicts according to contents.

        Only text conflicts are auto_resolvable. Files with no conflict markers
        are considered 'resolved', because bzr always puts conflict markers
        into files that have text conflicts.  The corresponding .THIS .BASE and
        .OTHER files are deleted, as per 'resolve'.
        :return: a tuple of ConflictLists: (un_resolved, resolved).
        """
        un_resolved = _mod_conflicts.ConflictList()
        resolved = _mod_conflicts.ConflictList()
        conflict_re = re.compile('^(<{7}|={7}|>{7})')
        for conflict in self.conflicts():
            if (conflict.typestring != 'text conflict' or
                self.kind(conflict.file_id) != 'file'):
                un_resolved.append(conflict)
                continue
            my_file = open(self.id2abspath(conflict.file_id), 'rb')
            try:
                for line in my_file:
                    if conflict_re.search(line):
                        un_resolved.append(conflict)
                        break
                else:
                    resolved.append(conflict)
            finally:
                my_file.close()
        resolved.remove_files(self)
        self.set_conflicts(un_resolved)
        return un_resolved, resolved

    @needs_read_lock
    def _check(self):
        tree_basis = self.basis_tree()
        tree_basis.lock_read()
        try:
            repo_basis = self.branch.repository.revision_tree(
                self.last_revision())
            if len(list(repo_basis.iter_changes(tree_basis))) > 0:
                raise errors.BzrCheckError(
                    "Mismatched basis inventory content.")
            self._validate()
        finally:
            tree_basis.unlock()

    def _validate(self):
        """Validate internal structures.

        This is meant mostly for the test suite. To give it a chance to detect
        corruption after actions have occurred. The default implementation is a
        just a no-op.

        :return: None. An exception should be raised if there is an error.
        """
        return

    @needs_read_lock
    def _get_rules_searcher(self, default_searcher):
        """See Tree._get_rules_searcher."""
        if self._rules_searcher is None:
            self._rules_searcher = super(WorkingTree,
                self)._get_rules_searcher(default_searcher)
        return self._rules_searcher

    def get_shelf_manager(self):
        """Return the ShelfManager for this WorkingTree."""
        from bzrlib.shelf import ShelfManager
        return ShelfManager(self, self._transport)


class WorkingTree2(WorkingTree):
    """This is the Format 2 working tree.

    This was the first weave based working tree. 
     - uses os locks for locking.
     - uses the branch last-revision.
    """

    def __init__(self, *args, **kwargs):
        super(WorkingTree2, self).__init__(*args, **kwargs)
        # WorkingTree2 has more of a constraint that self._inventory must
        # exist. Because this is an older format, we don't mind the overhead
        # caused by the extra computation here.

        # Newer WorkingTree's should only have self._inventory set when they
        # have a read lock.
        if self._inventory is None:
            self.read_working_inventory()

    def lock_tree_write(self):
        """See WorkingTree.lock_tree_write().

        In Format2 WorkingTrees we have a single lock for the branch and tree
        so lock_tree_write() degrades to lock_write().
        """
        self.branch.lock_write()
        try:
            return self._control_files.lock_write()
        except:
            self.branch.unlock()
            raise

    def unlock(self):
        # do non-implementation specific cleanup
        self._cleanup()

        # we share control files:
        if self._control_files._lock_count == 3:
            # _inventory_is_modified is always False during a read lock.
            if self._inventory_is_modified:
                self.flush()
            self._write_hashcache_if_dirty()
                    
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()


class WorkingTree3(WorkingTree):
    """This is the Format 3 working tree.

    This differs from the base WorkingTree by:
     - having its own file lock
     - having its own last-revision property.

    This is new in bzr 0.8
    """

    @needs_read_lock
    def _last_revision(self):
        """See Mutable.last_revision."""
        try:
            return self._transport.get_bytes('last-revision')
        except errors.NoSuchFile:
            return _mod_revision.NULL_REVISION

    def _change_last_revision(self, revision_id):
        """See WorkingTree._change_last_revision."""
        if revision_id is None or revision_id == NULL_REVISION:
            try:
                self._transport.delete('last-revision')
            except errors.NoSuchFile:
                pass
            return False
        else:
            self._transport.put_bytes('last-revision', revision_id,
                mode=self._control_files._file_mode)
            return True

    @needs_tree_write_lock
    def set_conflicts(self, conflicts):
        self._put_rio('conflicts', conflicts.to_stanzas(), 
                      CONFLICT_HEADER_1)

    @needs_tree_write_lock
    def add_conflicts(self, new_conflicts):
        conflict_set = set(self.conflicts())
        conflict_set.update(set(list(new_conflicts)))
        self.set_conflicts(_mod_conflicts.ConflictList(sorted(conflict_set,
                                       key=_mod_conflicts.Conflict.sort_key)))

    @needs_read_lock
    def conflicts(self):
        try:
            confile = self._transport.get('conflicts')
        except errors.NoSuchFile:
            return _mod_conflicts.ConflictList()
        try:
            try:
                if confile.next() != CONFLICT_HEADER_1 + '\n':
                    raise errors.ConflictFormatError()
            except StopIteration:
                raise errors.ConflictFormatError()
            return _mod_conflicts.ConflictList.from_stanzas(RioReader(confile))
        finally:
            confile.close()

    def unlock(self):
        # do non-implementation specific cleanup
        self._cleanup()
        if self._control_files._lock_count == 1:
            # _inventory_is_modified is always False during a read lock.
            if self._inventory_is_modified:
                self.flush()
            self._write_hashcache_if_dirty()
        # reverse order of locking.
        try:
            return self._control_files.unlock()
        finally:
            self.branch.unlock()


def get_conflicted_stem(path):
    for suffix in _mod_conflicts.CONFLICT_SUFFIXES:
        if path.endswith(suffix):
            return path[:-len(suffix)]


class WorkingTreeFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during workingtree opening. Its not required that these be instances, they
    can be classes themselves with class methods - it simply depends on 
    whether state is needed for a given format or not.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every time regardless.
    """

    _default_format = None
    """The default format used for new trees."""

    _formats = {}
    """The known formats."""

    requires_rich_root = False

    upgrade_recommended = False

    @classmethod
    def find_format(klass, a_bzrdir):
        """Return the format for the working tree object in a_bzrdir."""
        try:
            transport = a_bzrdir.get_workingtree_transport(None)
            format_string = transport.get("format").read()
            return klass._formats[format_string]
        except errors.NoSuchFile:
            raise errors.NoWorkingTree(base=transport.base)
        except KeyError:
            raise errors.UnknownFormatError(format=format_string,
                                            kind="working tree")

    def __eq__(self, other):
        return self.__class__ is other.__class__

    def __ne__(self, other):
        return not (self == other)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def is_supported(self):
        """Is this format supported?

        Supported formats can be initialized and opened.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def set_default_format(klass, format):
        klass._default_format = format

    @classmethod
    def unregister_format(klass, format):
        del klass._formats[format.get_format_string()]


class WorkingTreeFormat2(WorkingTreeFormat):
    """The second working tree format. 

    This format modified the hash cache from the format 1 hash cache.
    """

    upgrade_recommended = True

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 2"

    def _stub_initialize_on_transport(self, transport, file_mode):
        """Workaround: create control files for a remote working tree.

        This ensures that it can later be updated and dealt with locally,
        since BzrDirFormat6 and BzrDirFormat5 cannot represent dirs with
        no working tree.  (See bug #43064).
        """
        sio = StringIO()
        inv = Inventory()
        xml5.serializer_v5.write_inventory(inv, sio, working=True)
        sio.seek(0)
        transport.put_file('inventory', sio, file_mode)
        transport.put_bytes('pending-merges', '', file_mode)

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """See WorkingTreeFormat.initialize()."""
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        if from_branch is not None:
            branch = from_branch
        else:
            branch = a_bzrdir.open_branch()
        if revision_id is None:
            revision_id = _mod_revision.ensure_null(branch.last_revision())
        branch.lock_write()
        try:
            branch.generate_revision_history(revision_id)
        finally:
            branch.unlock()
        inv = Inventory()
        wt = WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir)
        basis_tree = branch.repository.revision_tree(revision_id)
        if basis_tree.inventory.root is not None:
            wt.set_root_id(basis_tree.get_root_id())
        # set the parent list and cache the basis tree.
        if _mod_revision.is_null(revision_id):
            parent_trees = []
        else:
            parent_trees = [(revision_id, basis_tree)]
        wt.set_parent_trees(parent_trees)
        transform.build_tree(basis_tree, wt)
        return wt

    def __init__(self):
        super(WorkingTreeFormat2, self).__init__()
        self._matchingbzrdir = bzrdir.BzrDirFormat6()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        wt = WorkingTree2(a_bzrdir.root_transport.local_abspath('.'),
                           _internal=True,
                           _format=self,
                           _bzrdir=a_bzrdir)
        return wt

class WorkingTreeFormat3(WorkingTreeFormat):
    """The second working tree format updated to record a format marker.

    This format:
        - exists within a metadir controlling .bzr
        - includes an explicit version marker for the workingtree control
          files, separate from the BzrDir format
        - modifies the hash cache format
        - is new in bzr 0.8
        - uses a LockDir to guard access for writes.
    """
    
    upgrade_recommended = True

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Bazaar-NG Working Tree format 3"

    def get_format_description(self):
        """See WorkingTreeFormat.get_format_description()."""
        return "Working tree format 3"

    _lock_file_name = 'lock'
    _lock_class = LockDir

    _tree_class = WorkingTree3

    def __get_matchingbzrdir(self):
        return bzrdir.BzrDirMetaFormat1()

    _matchingbzrdir = property(__get_matchingbzrdir)

    def _open_control_files(self, a_bzrdir):
        transport = a_bzrdir.get_workingtree_transport(None)
        return LockableFiles(transport, self._lock_file_name, 
                             self._lock_class)

    def initialize(self, a_bzrdir, revision_id=None, from_branch=None,
                   accelerator_tree=None, hardlink=False):
        """See WorkingTreeFormat.initialize().
        
        :param revision_id: if supplied, create a working tree at a different
            revision than the branch is at.
        :param accelerator_tree: A tree which can be used for retrieving file
            contents more quickly than the revision tree, i.e. a workingtree.
            The revision tree will be used for cases where accelerator_tree's
            content is different.
        :param hardlink: If true, hard-link files from accelerator_tree,
            where possible.
        """
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        transport = a_bzrdir.get_workingtree_transport(self)
        control_files = self._open_control_files(a_bzrdir)
        control_files.create_lock()
        control_files.lock_write()
        transport.put_bytes('format', self.get_format_string(),
            mode=control_files._file_mode)
        if from_branch is not None:
            branch = from_branch
        else:
            branch = a_bzrdir.open_branch()
        if revision_id is None:
            revision_id = _mod_revision.ensure_null(branch.last_revision())
        # WorkingTree3 can handle an inventory which has a unique root id.
        # as of bzr 0.12. However, bzr 0.11 and earlier fail to handle
        # those trees. And because there isn't a format bump inbetween, we
        # are maintaining compatibility with older clients.
        # inv = Inventory(root_id=gen_root_id())
        inv = self._initial_inventory()
        wt = self._tree_class(a_bzrdir.root_transport.local_abspath('.'),
                         branch,
                         inv,
                         _internal=True,
                         _format=self,
                         _bzrdir=a_bzrdir,
                         _control_files=control_files)
        wt.lock_tree_write()
        try:
            basis_tree = branch.repository.revision_tree(revision_id)
            # only set an explicit root id if there is one to set.
            if basis_tree.inventory.root is not None:
                wt.set_root_id(basis_tree.get_root_id())
            if revision_id == NULL_REVISION:
                wt.set_parent_trees([])
            else:
                wt.set_parent_trees([(revision_id, basis_tree)])
            transform.build_tree(basis_tree, wt)
        finally:
            # Unlock in this order so that the unlock-triggers-flush in
            # WorkingTree is given a chance to fire.
            control_files.unlock()
            wt.unlock()
        return wt

    def _initial_inventory(self):
        return Inventory()

    def __init__(self):
        super(WorkingTreeFormat3, self).__init__()

    def open(self, a_bzrdir, _found=False):
        """Return the WorkingTree object for a_bzrdir

        _found is a private parameter, do not use it. It is used to indicate
               if format probing has already been done.
        """
        if not _found:
            # we are being called directly and must probe.
            raise NotImplementedError
        if not isinstance(a_bzrdir.transport, LocalTransport):
            raise errors.NotLocalUrl(a_bzrdir.transport.base)
        wt = self._open(a_bzrdir, self._open_control_files(a_bzrdir))
        return wt

    def _open(self, a_bzrdir, control_files):
        """Open the tree itself.
        
        :param a_bzrdir: the dir for the tree.
        :param control_files: the control files for the tree.
        """
        return self._tree_class(a_bzrdir.root_transport.local_abspath('.'),
                                _internal=True,
                                _format=self,
                                _bzrdir=a_bzrdir,
                                _control_files=control_files)

    def __str__(self):
        return self.get_format_string()


__default_format = WorkingTreeFormat4()
WorkingTreeFormat.register_format(__default_format)
WorkingTreeFormat.register_format(WorkingTreeFormat3())
WorkingTreeFormat.set_default_format(__default_format)
# formats which have no format string are not discoverable
# and not independently creatable, so are not registered.
_legacy_formats = [WorkingTreeFormat2(),
                   ]
