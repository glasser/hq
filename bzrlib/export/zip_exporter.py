# Copyright (C) 2005 Canonical Ltd
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

"""Export a Tree to a non-versioned directory.
"""

import os
import stat
import time
import zipfile

from bzrlib import (
    osutils,
    )
from bzrlib.export import _export_iter_entries
from bzrlib.trace import mutter


# Windows expects this bit to be set in the 'external_attr' section
# Or it won't consider the entry a directory
ZIP_DIRECTORY_BIT = (1 << 4)

_FILE_ATTR = stat.S_IFREG
_DIR_ATTR = stat.S_IFDIR | ZIP_DIRECTORY_BIT


def zip_exporter(tree, dest, root, subdir):
    """ Export this tree to a new zip file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be overwritten".
    """
    mutter('export version %r', tree)

    now = time.localtime()[:6]

    compression = zipfile.ZIP_DEFLATED
    zipf = zipfile.ZipFile(dest, "w", compression)

    try:
        for dp, ie in _export_iter_entries(tree, subdir):
            file_id = ie.file_id
            mutter("  export {%s} kind %s to %s", file_id, ie.kind, dest)

            # zipfile.ZipFile switches all paths to forward
            # slashes anyway, so just stick with that.
            filename = osutils.pathjoin(root, dp).encode('utf8')
            if ie.kind == "file":
                zinfo = zipfile.ZipInfo(
                            filename=filename,
                            date_time=now)
                zinfo.compress_type = compression
                zinfo.external_attr = _FILE_ATTR
                zipf.writestr(zinfo, tree.get_file_text(file_id))
            elif ie.kind == "directory":
                # Directories must contain a trailing slash, to indicate
                # to the zip routine that they are really directories and
                # not just empty files.
                zinfo = zipfile.ZipInfo(
                            filename=filename + '/',
                            date_time=now)
                zinfo.compress_type = compression
                zinfo.external_attr = _DIR_ATTR
                zipf.writestr(zinfo,'')
            elif ie.kind == "symlink":
                zinfo = zipfile.ZipInfo(
                            filename=(filename + '.lnk'),
                            date_time=now)
                zinfo.compress_type = compression
                zinfo.external_attr = _FILE_ATTR
                zipf.writestr(zinfo, ie.symlink_target)

        zipf.close()

    except UnicodeEncodeError:
        zipf.close()
        os.remove(dest)
        from bzrlib.errors import BzrError
        raise BzrError("Can't export non-ascii filenames to zip")

