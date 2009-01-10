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

# FIXME: This refactoring of the workingtree code doesn't seem to keep 
# the WorkingTree's copy of the inventory in sync with the branch.  The
# branch modifies its working inventory when it does a commit to make
# missing files permanently removed.

# TODO: Maybe also keep the full path of the entry, and the children?
# But those depend on its position within a particular inventory, and
# it would be nice not to need to hold the backpointer here.

# This should really be an id randomly assigned when the tree is
# created, but it's not for now.
ROOT_ID = "TREE_ROOT"

import os
import re
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import collections
import tarfile

import bzrlib
from bzrlib import (
    errors,
    generate_ids,
    osutils,
    symbol_versioning,
    workingtree,
    )
""")

from bzrlib.errors import (
    BzrCheckError,
    BzrError,
    )
from bzrlib.symbol_versioning import deprecated_in, deprecated_method
from bzrlib.trace import mutter


class InventoryEntry(object):
    """Description of a versioned file.

    An InventoryEntry has the following fields, which are also
    present in the XML inventory-entry element:

    file_id

    name
        (within the parent directory)

    parent_id
        file_id of the parent directory, or ROOT_ID

    revision
        the revision_id in which this variation of this file was 
        introduced.

    executable
        Indicates that this file should be executable on systems
        that support it.

    text_sha1
        sha-1 of the text of the file
        
    text_size
        size in bytes of the text of the file
        
    (reading a version 4 tree created a text_id field.)

    >>> i = Inventory()
    >>> i.path2id('')
    'TREE_ROOT'
    >>> i.add(InventoryDirectory('123', 'src', ROOT_ID))
    InventoryDirectory('123', 'src', parent_id='TREE_ROOT', revision=None)
    >>> i.add(InventoryFile('2323', 'hello.c', parent_id='123'))
    InventoryFile('2323', 'hello.c', parent_id='123', sha1=None, len=None)
    >>> shouldbe = {0: '', 1: 'src', 2: 'src/hello.c'}
    >>> for ix, j in enumerate(i.iter_entries()):
    ...   print (j[0] == shouldbe[ix], j[1])
    ... 
    (True, InventoryDirectory('TREE_ROOT', u'', parent_id=None, revision=None))
    (True, InventoryDirectory('123', 'src', parent_id='TREE_ROOT', revision=None))
    (True, InventoryFile('2323', 'hello.c', parent_id='123', sha1=None, len=None))
    >>> i.add(InventoryFile('2324', 'bye.c', '123'))
    InventoryFile('2324', 'bye.c', parent_id='123', sha1=None, len=None)
    >>> i.add(InventoryDirectory('2325', 'wibble', '123'))
    InventoryDirectory('2325', 'wibble', parent_id='123', revision=None)
    >>> i.path2id('src/wibble')
    '2325'
    >>> '2325' in i
    True
    >>> i.add(InventoryFile('2326', 'wibble.c', '2325'))
    InventoryFile('2326', 'wibble.c', parent_id='2325', sha1=None, len=None)
    >>> i['2326']
    InventoryFile('2326', 'wibble.c', parent_id='2325', sha1=None, len=None)
    >>> for path, entry in i.iter_entries():
    ...     print path
    ... 
    <BLANKLINE>
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path('2326')
    'src/wibble/wibble.c'
    """

    # Constants returned by describe_change()
    #
    # TODO: These should probably move to some kind of FileChangeDescription 
    # class; that's like what's inside a TreeDelta but we want to be able to 
    # generate them just for one file at a time.
    RENAMED = 'renamed'
    MODIFIED_AND_RENAMED = 'modified and renamed'
    
    __slots__ = []

    def detect_changes(self, old_entry):
        """Return a (text_modified, meta_modified) from this to old_entry.
        
        _read_tree_state must have been called on self and old_entry prior to 
        calling detect_changes.
        """
        return False, False

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """Perform a diff between two entries of the same kind."""
    
    def parent_candidates(self, previous_inventories):
        """Find possible per-file graph parents.

        This is currently defined by:
         - Select the last changed revision in the parent inventory.
         - Do deal with a short lived bug in bzr 0.8's development two entries
           that have the same last changed but different 'x' bit settings are
           changed in-place.
        """
        # revision:ie mapping for each ie found in previous_inventories.
        candidates = {}
        # identify candidate head revision ids.
        for inv in previous_inventories:
            if self.file_id in inv:
                ie = inv[self.file_id]
                if ie.revision in candidates:
                    # same revision value in two different inventories:
                    # correct possible inconsistencies:
                    #     * there was a bug in revision updates with 'x' bit 
                    #       support.
                    try:
                        if candidates[ie.revision].executable != ie.executable:
                            candidates[ie.revision].executable = False
                            ie.executable = False
                    except AttributeError:
                        pass
                else:
                    # add this revision as a candidate.
                    candidates[ie.revision] = ie
        return candidates

    @deprecated_method(deprecated_in((1, 6, 0)))
    def get_tar_item(self, root, dp, now, tree):
        """Get a tarfile item and a file stream for its content."""
        item = tarfile.TarInfo(osutils.pathjoin(root, dp).encode('utf8'))
        # TODO: would be cool to actually set it to the timestamp of the
        # revision it was last changed
        item.mtime = now
        fileobj = self._put_in_tar(item, tree)
        return item, fileobj

    def has_text(self):
        """Return true if the object this entry represents has textual data.

        Note that textual data includes binary content.

        Also note that all entries get weave files created for them.
        This attribute is primarily used when upgrading from old trees that
        did not have the weave index for all inventory entries.
        """
        return False

    def __init__(self, file_id, name, parent_id, text_id=None):
        """Create an InventoryEntry
        
        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryFile('123', 'hello.c', ROOT_ID)
        >>> e.name
        'hello.c'
        >>> e.file_id
        '123'
        >>> e = InventoryFile('123', 'src/hello.c', ROOT_ID)
        Traceback (most recent call last):
        InvalidEntryName: Invalid entry name: src/hello.c
        """
        if '/' in name or '\\' in name:
            raise errors.InvalidEntryName(name=name)
        self.executable = False
        self.revision = None
        self.text_sha1 = None
        self.text_size = None
        self.file_id = file_id
        self.name = name
        self.text_id = text_id
        self.parent_id = parent_id
        self.symlink_target = None
        self.reference_revision = None

    def kind_character(self):
        """Return a short kind indicator useful for appending to names."""
        raise BzrError('unknown kind %r' % self.kind)

    known_kinds = ('file', 'directory', 'symlink')

    def _put_in_tar(self, item, tree):
        """populate item for stashing in a tar, and return the content stream.

        If no content is available, return None.
        """
        raise BzrError("don't know how to export {%s} of kind %r" %
                       (self.file_id, self.kind))

    @deprecated_method(deprecated_in((1, 6, 0)))
    def put_on_disk(self, dest, dp, tree):
        """Create a representation of self on disk in the prefix dest.
        
        This is a template method - implement _put_on_disk in subclasses.
        """
        fullpath = osutils.pathjoin(dest, dp)
        self._put_on_disk(fullpath, tree)
        # mutter("  export {%s} kind %s to %s", self.file_id,
        #         self.kind, fullpath)

    def _put_on_disk(self, fullpath, tree):
        """Put this entry onto disk at fullpath, from tree tree."""
        raise BzrError("don't know how to export {%s} of kind %r" % (self.file_id, self.kind))

    def sorted_children(self):
        return sorted(self.children.items())

    @staticmethod
    def versionable_kind(kind):
        return (kind in ('file', 'directory', 'symlink', 'tree-reference'))

    def check(self, checker, rev_id, inv, tree):
        """Check this inventory entry is intact.

        This is a template method, override _check for kind specific
        tests.

        :param checker: Check object providing context for the checks; 
             can be used to find out what parts of the repository have already
             been checked.
        :param rev_id: Revision id from which this InventoryEntry was loaded.
             Not necessarily the last-changed revision for this file.
        :param inv: Inventory from which the entry was loaded.
        :param tree: RevisionTree for this entry.
        """
        if self.parent_id is not None:
            if not inv.has_id(self.parent_id):
                raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
                        % (self.parent_id, rev_id))
        self._check(checker, rev_id, tree)

    def _check(self, checker, rev_id, tree):
        """Check this inventory entry for kind specific errors."""
        raise BzrCheckError('unknown entry kind %r in revision {%s}' % 
                            (self.kind, rev_id))

    def copy(self):
        """Clone this inventory entry."""
        raise NotImplementedError

    @staticmethod
    def describe_change(old_entry, new_entry):
        """Describe the change between old_entry and this.
        
        This smells of being an InterInventoryEntry situation, but as its
        the first one, we're making it a static method for now.

        An entry with a different parent, or different name is considered 
        to be renamed. Reparenting is an internal detail.
        Note that renaming the parent does not trigger a rename for the
        child entry itself.
        """
        # TODO: Perhaps return an object rather than just a string
        if old_entry is new_entry:
            # also the case of both being None
            return 'unchanged'
        elif old_entry is None:
            return 'added'
        elif new_entry is None:
            return 'removed'
        if old_entry.kind != new_entry.kind:
            return 'modified'
        text_modified, meta_modified = new_entry.detect_changes(old_entry)
        if text_modified or meta_modified:
            modified = True
        else:
            modified = False
        # TODO 20060511 (mbp, rbc) factor out 'detect_rename' here.
        if old_entry.parent_id != new_entry.parent_id:
            renamed = True
        elif old_entry.name != new_entry.name:
            renamed = True
        else:
            renamed = False
        if renamed and not modified:
            return InventoryEntry.RENAMED
        if modified and not renamed:
            return 'modified'
        if modified and renamed:
            return InventoryEntry.MODIFIED_AND_RENAMED
        return 'unchanged'

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, revision=%r)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.revision))

    def __eq__(self, other):
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return ((self.file_id == other.file_id)
                and (self.name == other.name)
                and (other.symlink_target == self.symlink_target)
                and (self.text_sha1 == other.text_sha1)
                and (self.text_size == other.text_size)
                and (self.text_id == other.text_id)
                and (self.parent_id == other.parent_id)
                and (self.kind == other.kind)
                and (self.revision == other.revision)
                and (self.executable == other.executable)
                and (self.reference_revision == other.reference_revision)
                )

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError('not hashable')

    def _unchanged(self, previous_ie):
        """Has this entry changed relative to previous_ie.

        This method should be overridden in child classes.
        """
        compatible = True
        # different inv parent
        if previous_ie.parent_id != self.parent_id:
            compatible = False
        # renamed
        elif previous_ie.name != self.name:
            compatible = False
        elif previous_ie.kind != self.kind:
            compatible = False
        return compatible

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree.
        
        Note that this should be modified to be a noop on virtual trees
        as all entries created there are prepopulated.
        """
        # TODO: Rather than running this manually, we should check the 
        # working sha1 and other expensive properties when they're
        # first requested, or preload them if they're already known
        pass            # nothing to do by default

    def _forget_tree_state(self):
        pass


class RootEntry(InventoryEntry):

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""

    def __init__(self, file_id):
        self.file_id = file_id
        self.children = {}
        self.kind = 'directory'
        self.parent_id = None
        self.name = u''
        self.revision = None
        symbol_versioning.warn('RootEntry is deprecated as of bzr 0.10.'
                               '  Please use InventoryDirectory instead.',
                               DeprecationWarning, stacklevel=2)

    def __eq__(self, other):
        if not isinstance(other, RootEntry):
            return NotImplemented
        
        return (self.file_id == other.file_id) \
               and (self.children == other.children)


class InventoryDirectory(InventoryEntry):
    """A directory in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 is not None or self.text_size is not None or self.text_id is not None:
            raise BzrCheckError('directory {%s} has text in revision {%s}'
                                % (self.file_id, rev_id))

    def copy(self):
        other = InventoryDirectory(self.file_id, self.name, self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other

    def __init__(self, file_id, name, parent_id):
        super(InventoryDirectory, self).__init__(file_id, name, parent_id)
        self.children = {}
        self.kind = 'directory'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.DIRTYPE
        fileobj = None
        item.name += '/'
        item.size = 0
        item.mode = 0755
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        os.mkdir(fullpath)


class InventoryFile(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, tree_revision_id, tree):
        """See InventoryEntry._check"""
        key = (self.file_id, self.revision)
        if key in checker.checked_texts:
            prev_sha = checker.checked_texts[key]
            if prev_sha != self.text_sha1:
                raise BzrCheckError(
                    'mismatched sha1 on {%s} in {%s} (%s != %s) %r' %
                    (self.file_id, tree_revision_id, prev_sha, self.text_sha1,
                     t))
            else:
                checker.repeated_text_cnt += 1
                return

        mutter('check version {%s} of {%s}', tree_revision_id, self.file_id)
        checker.checked_text_cnt += 1
        # We can't check the length, because Weave doesn't store that
        # information, and the whole point of looking at the weave's
        # sha1sum is that we don't have to extract the text.
        if (self.text_sha1 != tree._repository.texts.get_sha1s([key])[key]):
            raise BzrCheckError('text {%s} version {%s} wrong sha1' % key)
        checker.checked_texts[key] = self.text_sha1

    def copy(self):
        other = InventoryFile(self.file_id, self.name, self.parent_id)
        other.executable = self.executable
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        text_modified = (self.text_sha1 != old_entry.text_sha1)
        meta_modified = (self.executable != old_entry.executable)
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from bzrlib.diff import DiffText
        from_file_id = self.file_id
        if to_entry:
            to_file_id = to_entry.file_id
        else:
            to_file_id = None
        if reverse:
            to_file_id, from_file_id = from_file_id, to_file_id
            tree, to_tree = to_tree, tree
            from_label, to_label = to_label, from_label
        differ = DiffText(tree, to_tree, output_to, 'utf-8', '', '',
                          text_diff)
        return differ.diff_text(from_file_id, to_file_id, from_label, to_label)

    def has_text(self):
        """See InventoryEntry.has_text."""
        return True

    def __init__(self, file_id, name, parent_id):
        super(InventoryFile, self).__init__(file_id, name, parent_id)
        self.kind = 'file'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.REGTYPE
        fileobj = tree.get_file(self.file_id)
        item.size = self.text_size
        if tree.is_executable(self.file_id):
            item.mode = 0755
        else:
            item.mode = 0644
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        osutils.pumpfile(tree.get_file(self.file_id), file(fullpath, 'wb'))
        if tree.is_executable(self.file_id):
            os.chmod(fullpath, 0755)

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.text_sha1 = work_tree.get_file_sha1(self.file_id, path=path)
        # FIXME: 20050930 probe for the text size when getting sha1
        # in _read_tree_state
        self.executable = work_tree.is_executable(self.file_id, path=path)

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, sha1=%r, len=%s)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.text_sha1,
                   self.text_size))

    def _forget_tree_state(self):
        self.text_sha1 = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryFile, self)._unchanged(previous_ie)
        if self.text_sha1 != previous_ie.text_sha1:
            compatible = False
        else:
            # FIXME: 20050930 probe for the text size when getting sha1
            # in _read_tree_state
            self.text_size = previous_ie.text_size
        if self.executable != previous_ie.executable:
            compatible = False
        return compatible


class InventoryLink(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 is not None or self.text_size is not None or self.text_id is not None:
            raise BzrCheckError('symlink {%s} has text in revision {%s}'
                    % (self.file_id, rev_id))
        if self.symlink_target is None:
            raise BzrCheckError('symlink {%s} has no target in revision {%s}'
                    % (self.file_id, rev_id))

    def copy(self):
        other = InventoryLink(self.file_id, self.name, self.parent_id)
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        # FIXME: which _modified field should we use ? RBC 20051003
        text_modified = (self.symlink_target != old_entry.symlink_target)
        if text_modified:
            mutter("    symlink target changed")
        meta_modified = False
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from bzrlib.diff import DiffSymlink
        old_target = self.symlink_target
        if to_entry is not None:
            new_target = to_entry.symlink_target
        else:
            new_target = None
        if not reverse:
            old_tree = tree
            new_tree = to_tree
        else:
            old_tree = to_tree
            new_tree = tree
            new_target, old_target = old_target, new_target
        differ = DiffSymlink(old_tree, new_tree, output_to)
        return differ.diff_symlink(old_target, new_target)

    def __init__(self, file_id, name, parent_id):
        super(InventoryLink, self).__init__(file_id, name, parent_id)
        self.kind = 'symlink'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.SYMTYPE
        fileobj = None
        item.size = 0
        item.mode = 0755
        item.linkname = self.symlink_target
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        try:
            os.symlink(self.symlink_target, fullpath)
        except OSError,e:
            raise BzrError("Failed to create symlink %r -> %r, error: %s" % (fullpath, self.symlink_target, e))

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.symlink_target = work_tree.get_symlink_target(self.file_id)

    def _forget_tree_state(self):
        self.symlink_target = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryLink, self)._unchanged(previous_ie)
        if self.symlink_target != previous_ie.symlink_target:
            compatible = False
        return compatible


class TreeReference(InventoryEntry):
    
    kind = 'tree-reference'
    
    def __init__(self, file_id, name, parent_id, revision=None,
                 reference_revision=None):
        InventoryEntry.__init__(self, file_id, name, parent_id)
        self.revision = revision
        self.reference_revision = reference_revision

    def copy(self):
        return TreeReference(self.file_id, self.name, self.parent_id,
                             self.revision, self.reference_revision)

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree.
        """
        self.reference_revision = work_tree.get_reference_revision(
            self.file_id, path)

    def _forget_tree_state(self):
        self.reference_revision = None 

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(TreeReference, self)._unchanged(previous_ie)
        if self.reference_revision != previous_ie.reference_revision:
            compatible = False
        return compatible


class Inventory(object):
    """Inventory of versioned files in a tree.

    This describes which file_id is present at each point in the tree,
    and possibly the SHA-1 or other information about the file.
    Entries can be looked up either by path or by file_id.

    The inventory represents a typical unix file tree, with
    directories containing files and subdirectories.  We never store
    the full path to a file, because renaming a directory implicitly
    moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    InventoryEntry objects must not be modified after they are
    inserted, other than through the Inventory API.

    >>> inv = Inventory()
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT', sha1=None, len=None)
    >>> inv['123-123'].name
    'hello.c'

    May be treated as an iterator or set to look up file ids:
    
    >>> bool(inv.path2id('hello.c'))
    True
    >>> '123-123' in inv
    True

    May also look up by name:

    >>> [x[0] for x in inv.iter_entries()]
    ['', u'hello.c']
    >>> inv = Inventory('TREE_ROOT-12345678-12345678')
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    Traceback (most recent call last):
    BzrError: parent_id {TREE_ROOT} not in inventory
    >>> inv.add(InventoryFile('123-123', 'hello.c', 'TREE_ROOT-12345678-12345678'))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT-12345678-12345678', sha1=None, len=None)
    """
    def __init__(self, root_id=ROOT_ID, revision_id=None):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.

        The inventory is created with a default root directory, with
        an id of None.
        """
        if root_id is not None:
            self._set_root(InventoryDirectory(root_id, u'', None))
        else:
            self.root = None
            self._byid = {}
        self.revision_id = revision_id

    def __repr__(self):
        return "<Inventory object at %x, contents=%r>" % (id(self), self._byid)

    def apply_delta(self, delta):
        """Apply a delta to this inventory.

        :param delta: A list of changes to apply. After all the changes are
            applied the final inventory must be internally consistent, but it
            is ok to supply changes which, if only half-applied would have an
            invalid result - such as supplying two changes which rename two
            files, 'A' and 'B' with each other : [('A', 'B', 'A-id', a_entry),
            ('B', 'A', 'B-id', b_entry)].

            Each change is a tuple, of the form (old_path, new_path, file_id,
            new_entry).
            
            When new_path is None, the change indicates the removal of an entry
            from the inventory and new_entry will be ignored (using None is
            appropriate). If new_path is not None, then new_entry must be an
            InventoryEntry instance, which will be incorporated into the
            inventory (and replace any existing entry with the same file id).
            
            When old_path is None, the change indicates the addition of
            a new entry to the inventory.
            
            When neither new_path nor old_path are None, the change is a
            modification to an entry, such as a rename, reparent, kind change
            etc. 

            The children attribute of new_entry is ignored. This is because
            this method preserves children automatically across alterations to
            the parent of the children, and cases where the parent id of a
            child is changing require the child to be passed in as a separate
            change regardless. E.g. in the recursive deletion of a directory -
            the directory's children must be included in the delta, or the
            final inventory will be invalid.
        """
        children = {}
        # Remove all affected items which were in the original inventory,
        # starting with the longest paths, thus ensuring parents are examined
        # after their children, which means that everything we examine has no
        # modified children remaining by the time we examine it.
        for old_path, file_id in sorted(((op, f) for op, np, f, e in delta
                                        if op is not None), reverse=True):
            if file_id not in self:
                # adds come later
                continue
            # Preserve unaltered children of file_id for later reinsertion.
            file_id_children = getattr(self[file_id], 'children', {})
            if len(file_id_children):
                children[file_id] = file_id_children
            # Remove file_id and the unaltered children. If file_id is not
            # being deleted it will be reinserted back later.
            self.remove_recursive_id(file_id)
        # Insert all affected which should be in the new inventory, reattaching
        # their children if they had any. This is done from shortest path to
        # longest, ensuring that items which were modified and whose parents in
        # the resulting inventory were also modified, are inserted after their
        # parents.
        for new_path, new_entry in sorted((np, e) for op, np, f, e in
                                          delta if np is not None):
            if new_entry.kind == 'directory':
                # Pop the child which to allow detection of children whose
                # parents were deleted and which were not reattached to a new
                # parent.
                new_entry.children = children.pop(new_entry.file_id, {})
            self.add(new_entry)
        if len(children):
            # Get the parent id that was deleted
            parent_id, children = children.popitem()
            raise errors.InconsistentDelta("<deleted>", parent_id,
                "The file id was deleted but its children were not deleted.")

    def _set_root(self, ie):
        self.root = ie
        self._byid = {self.root.file_id: self.root}

    def copy(self):
        # TODO: jam 20051218 Should copy also copy the revision_id?
        entries = self.iter_entries()
        if self.root is None:
            return Inventory(root_id=None)
        other = Inventory(entries.next()[1].file_id)
        other.root.revision = self.root.revision
        # copy recursively so we know directories will be added before
        # their children.  There are more efficient ways than this...
        for path, entry in entries:
            other.add(entry.copy())
        return other

    def __iter__(self):
        return iter(self._byid)

    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)

    def iter_entries(self, from_dir=None):
        """Return (path, entry) pairs, in order by name."""
        if from_dir is None:
            if self.root is None:
                return
            from_dir = self.root
            yield '', self.root
        elif isinstance(from_dir, basestring):
            from_dir = self._byid[from_dir]
            
        # unrolling the recursive called changed the time from
        # 440ms/663ms (inline/total) to 116ms/116ms
        children = from_dir.children.items()
        children.sort()
        children = collections.deque(children)
        stack = [(u'', children)]
        while stack:
            from_dir_relpath, children = stack[-1]

            while children:
                name, ie = children.popleft()

                # we know that from_dir_relpath never ends in a slash
                # and 'f' doesn't begin with one, we can do a string op, rather
                # than the checks of pathjoin(), though this means that all paths
                # start with a slash
                path = from_dir_relpath + '/' + name

                yield path[1:], ie

                if ie.kind != 'directory':
                    continue

                # But do this child first
                new_children = ie.children.items()
                new_children.sort()
                new_children = collections.deque(new_children)
                stack.append((path, new_children))
                # Break out of inner loop, so that we start outer loop with child
                break
            else:
                # if we finished all children, pop it off the stack
                stack.pop()

    def iter_entries_by_dir(self, from_dir=None, specific_file_ids=None,
        yield_parents=False):
        """Iterate over the entries in a directory first order.

        This returns all entries for a directory before returning
        the entries for children of a directory. This is not
        lexicographically sorted order, and is a hybrid between
        depth-first and breadth-first.

        :param yield_parents: If True, yield the parents from the root leading
            down to specific_file_ids that have been requested. This has no
            impact if specific_file_ids is None.
        :return: This yields (path, entry) pairs
        """
        if specific_file_ids and not isinstance(specific_file_ids, set):
            specific_file_ids = set(specific_file_ids)
        # TODO? Perhaps this should return the from_dir so that the root is
        # yielded? or maybe an option?
        if from_dir is None:
            if self.root is None:
                return
            # Optimize a common case
            if (not yield_parents and specific_file_ids is not None and
                len(specific_file_ids) == 1):
                file_id = list(specific_file_ids)[0]
                if file_id in self:
                    yield self.id2path(file_id), self[file_id]
                return 
            from_dir = self.root
            if (specific_file_ids is None or yield_parents or
                self.root.file_id in specific_file_ids):
                yield u'', self.root
        elif isinstance(from_dir, basestring):
            from_dir = self._byid[from_dir]

        if specific_file_ids is not None:
            # TODO: jam 20070302 This could really be done as a loop rather
            #       than a bunch of recursive calls.
            parents = set()
            byid = self._byid
            def add_ancestors(file_id):
                if file_id not in byid:
                    return
                parent_id = byid[file_id].parent_id
                if parent_id is None:
                    return
                if parent_id not in parents:
                    parents.add(parent_id)
                    add_ancestors(parent_id)
            for file_id in specific_file_ids:
                add_ancestors(file_id)
        else:
            parents = None
            
        stack = [(u'', from_dir)]
        while stack:
            cur_relpath, cur_dir = stack.pop()

            child_dirs = []
            for child_name, child_ie in sorted(cur_dir.children.iteritems()):

                child_relpath = cur_relpath + child_name

                if (specific_file_ids is None or 
                    child_ie.file_id in specific_file_ids or
                    (yield_parents and child_ie.file_id in parents)):
                    yield child_relpath, child_ie

                if child_ie.kind == 'directory':
                    if parents is None or child_ie.file_id in parents:
                        child_dirs.append((child_relpath+'/', child_ie))
            stack.extend(reversed(child_dirs))

    def make_entry(self, kind, name, parent_id, file_id=None):
        """Simple thunk to bzrlib.inventory.make_entry."""
        return make_entry(kind, name, parent_id, file_id)

    def entries(self):
        """Return list of (path, ie) for all entries except the root.

        This may be faster than iter_entries.
        """
        accum = []
        def descend(dir_ie, dir_path):
            kids = dir_ie.children.items()
            kids.sort()
            for name, ie in kids:
                child_path = osutils.pathjoin(dir_path, name)
                accum.append((child_path, ie))
                if ie.kind == 'directory':
                    descend(ie, child_path)

        descend(self.root, u'')
        return accum

    def directories(self):
        """Return (path, entry) pairs for all directories, including the root.
        """
        accum = []
        def descend(parent_ie, parent_path):
            accum.append((parent_path, parent_ie))
            
            kids = [(ie.name, ie) for ie in parent_ie.children.itervalues() if ie.kind == 'directory']
            kids.sort()

            for name, child_ie in kids:
                child_path = osutils.pathjoin(parent_path, name)
                descend(child_ie, child_path)
        descend(self.root, u'')
        return accum
        
    def __contains__(self, file_id):
        """True if this entry contains a file with given id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT', sha1=None, len=None)
        >>> '123' in inv
        True
        >>> '456' in inv
        False
        """
        return (file_id in self._byid)

    def __getitem__(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123123', 'hello.c', ROOT_ID))
        InventoryFile('123123', 'hello.c', parent_id='TREE_ROOT', sha1=None, len=None)
        >>> inv['123123'].name
        'hello.c'
        """
        try:
            return self._byid[file_id]
        except KeyError:
            # really we're passing an inventory, not a tree...
            raise errors.NoSuchId(self, file_id)

    def get_file_kind(self, file_id):
        return self._byid[file_id].kind

    def get_child(self, parent_id, filename):
        return self[parent_id].children.get(filename)

    def _add_child(self, entry):
        """Add an entry to the inventory, without adding it to its parent"""
        if entry.file_id in self._byid:
            raise BzrError("inventory already contains entry with id {%s}" %
                           entry.file_id)
        self._byid[entry.file_id] = entry
        for child in getattr(entry, 'children', {}).itervalues():
            self._add_child(child)
        return entry

    def add(self, entry):
        """Add entry to inventory.

        To add  a file to a branch ready to be committed, use Branch.add,
        which calls this.

        Returns the new entry object.
        """
        if entry.file_id in self._byid:
            raise errors.DuplicateFileId(entry.file_id,
                                         self._byid[entry.file_id])

        if entry.parent_id is None:
            self.root = entry
        else:
            try:
                parent = self._byid[entry.parent_id]
            except KeyError:
                raise BzrError("parent_id {%s} not in inventory" %
                               entry.parent_id)

            if entry.name in parent.children:
                raise BzrError("%s is already versioned" %
                        osutils.pathjoin(self.id2path(parent.file_id),
                        entry.name).encode('utf-8'))
            parent.children[entry.name] = entry
        return self._add_child(entry)

    def add_path(self, relpath, kind, file_id=None, parent_id=None):
        """Add entry from a path.

        The immediate parent must already be versioned.

        Returns the new entry object."""
        
        parts = osutils.splitpath(relpath)

        if len(parts) == 0:
            if file_id is None:
                file_id = generate_ids.gen_root_id()
            self.root = InventoryDirectory(file_id, '', None)
            self._byid = {self.root.file_id: self.root}
            return self.root
        else:
            parent_path = parts[:-1]
            parent_id = self.path2id(parent_path)
            if parent_id is None:
                raise errors.NotVersionedError(path=parent_path)
        ie = make_entry(kind, parts[-1], parent_id, file_id)
        return self.add(ie)

    def __delitem__(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT', sha1=None, len=None)
        >>> '123' in inv
        True
        >>> del inv['123']
        >>> '123' in inv
        False
        """
        ie = self[file_id]
        del self._byid[file_id]
        if ie.parent_id is not None:
            del self[ie.parent_id].children[ie.name]

    def __eq__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT', sha1=None, len=None)
        >>> i1 == i2
        False
        >>> i2.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT', sha1=None, len=None)
        >>> i1 == i2
        True
        """
        if not isinstance(other, Inventory):
            return NotImplemented

        return self._byid == other._byid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        raise ValueError('not hashable')

    def _iter_file_id_parents(self, file_id):
        """Yield the parents of file_id up to the root."""
        while file_id is not None:
            try:
                ie = self._byid[file_id]
            except KeyError:
                raise errors.NoSuchId(tree=None, file_id=file_id)
            yield ie
            file_id = ie.parent_id

    def get_idpath(self, file_id):
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        p = []
        for parent in self._iter_file_id_parents(file_id):
            p.insert(0, parent.file_id)
        return p

    def id2path(self, file_id):
        """Return as a string the path to file_id.
        
        >>> i = Inventory()
        >>> e = i.add(InventoryDirectory('src-id', 'src', ROOT_ID))
        >>> e = i.add(InventoryFile('foo-id', 'foo.c', parent_id='src-id'))
        >>> print i.id2path('foo-id')
        src/foo.c
        """
        # get all names, skipping root
        return '/'.join(reversed(
            [parent.name for parent in 
             self._iter_file_id_parents(file_id)][:-1]))
            
    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None IFF the path is not found.
        """
        if isinstance(name, basestring):
            name = osutils.splitpath(name)

        # mutter("lookup path %r" % name)

        parent = self.root
        if parent is None:
            return None
        for f in name:
            try:
                children = getattr(parent, 'children', None)
                if children is None:
                    return None
                cie = children[f]
                parent = cie
            except KeyError:
                # or raise an error?
                return None

        return parent.file_id

    def has_filename(self, names):
        return bool(self.path2id(names))

    def has_id(self, file_id):
        return (file_id in self._byid)

    def remove_recursive_id(self, file_id):
        """Remove file_id, and children, from the inventory.
        
        :param file_id: A file_id to remove.
        """
        to_find_delete = [self._byid[file_id]]
        to_delete = []
        while to_find_delete:
            ie = to_find_delete.pop()
            to_delete.append(ie.file_id)
            if ie.kind == 'directory':
                to_find_delete.extend(ie.children.values())
        for file_id in reversed(to_delete):
            ie = self[file_id]
            del self._byid[file_id]
        if ie.parent_id is not None:
            del self[ie.parent_id].children[ie.name]
        else:
            self.root = None

    def rename(self, file_id, new_parent_id, new_name):
        """Move a file within the inventory.

        This can change either the name, or the parent, or both.

        This does not move the working file.
        """
        new_name = ensure_normalized_name(new_name)
        if not is_valid_name(new_name):
            raise BzrError("not an acceptable filename: %r" % new_name)

        new_parent = self._byid[new_parent_id]
        if new_name in new_parent.children:
            raise BzrError("%r already exists in %r" % (new_name, self.id2path(new_parent_id)))

        new_parent_idpath = self.get_idpath(new_parent_id)
        if file_id in new_parent_idpath:
            raise BzrError("cannot move directory %r into a subdirectory of itself, %r"
                    % (self.id2path(file_id), self.id2path(new_parent_id)))

        file_ie = self._byid[file_id]
        old_parent = self._byid[file_ie.parent_id]

        # TODO: Don't leave things messed up if this fails

        del old_parent.children[file_ie.name]
        new_parent.children[new_name] = file_ie
        
        file_ie.name = new_name
        file_ie.parent_id = new_parent_id

    def is_root(self, file_id):
        return self.root is not None and file_id == self.root.file_id


entry_factory = {
    'directory': InventoryDirectory,
    'file': InventoryFile,
    'symlink': InventoryLink,
    'tree-reference': TreeReference
}

def make_entry(kind, name, parent_id, file_id=None):
    """Create an inventory entry.

    :param kind: the type of inventory entry to create.
    :param name: the basename of the entry.
    :param parent_id: the parent_id of the entry.
    :param file_id: the file_id to use. if None, one will be created.
    """
    if file_id is None:
        file_id = generate_ids.gen_file_id(name)
    name = ensure_normalized_name(name)
    try:
        factory = entry_factory[kind]
    except KeyError:
        raise BzrError("unknown kind %r" % kind)
    return factory(file_id, name, parent_id)


def ensure_normalized_name(name):
    """Normalize name.

    :raises InvalidNormalization: When name is not normalized, and cannot be
        accessed on this platform by the normalized path.
    :return: The NFC normalised version of name.
    """
    #------- This has been copied to bzrlib.dirstate.DirState.add, please
    # keep them synchronised.
    # we dont import normalized_filename directly because we want to be
    # able to change the implementation at runtime for tests.
    norm_name, can_access = osutils.normalized_filename(name)
    if norm_name != name:
        if can_access:
            return norm_name
        else:
            # TODO: jam 20060701 This would probably be more useful
            #       if the error was raised with the full path
            raise errors.InvalidNormalization(name)
    return name


_NAME_RE = None

def is_valid_name(name):
    global _NAME_RE
    if _NAME_RE is None:
        _NAME_RE = re.compile(r'^[^/\\]+$')
        
    return bool(_NAME_RE.match(name))
