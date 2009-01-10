# Copyright (C) 2006, 2008 Canonical Ltd
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

"""Python implementation of readdir interface."""


import os
import stat


_directory = 'directory'
_chardev = 'chardev'
_block = 'block'
_file = 'file'
_fifo = 'fifo'
_symlink = 'symlink'
_socket = 'socket'
_unknown = 'unknown'

_formats = {
    stat.S_IFDIR:'directory',
    stat.S_IFCHR:'chardev',
    stat.S_IFBLK:'block',
    stat.S_IFREG:'file',
    stat.S_IFIFO:'fifo',
    stat.S_IFLNK:'symlink',
    stat.S_IFSOCK:'socket',
}


def _kind_from_mode(stat_mode, _formats=_formats, _unknown='unknown'):
    """Generate a file kind from a stat mode. This is used in walkdirs.

    It's performance is critical: Do not mutate without careful benchmarking.
    """
    try:
        return _formats[stat_mode & 0170000]
    except KeyError:
        return _unknown
