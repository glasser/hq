# Copyright (C) 2006 Canonical Ltd
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

"""Common code for generating file or revision ids."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import time
import unicodedata

from bzrlib import (
    config,
    errors,
    osutils,
    )
""")

from bzrlib import (
    lazy_regex,
    )

# the regex removes any weird characters; we don't escape them 
# but rather just pull them out
_file_id_chars_re = lazy_regex.lazy_compile(r'[^\w.]')
_rev_id_chars_re = lazy_regex.lazy_compile(r'[^-\w.+@]')
_gen_file_id_suffix = None
_gen_file_id_serial = 0


def _next_id_suffix():
    """Create a new file id suffix that is reasonably unique.
    
    On the first call we combine the current time with 64 bits of randomness to
    give a highly probably globally unique number. Then each call in the same
    process adds 1 to a serial number we append to that unique value.
    """
    # XXX TODO: change bzrlib.add.smart_add_tree to call workingtree.add() rather 
    # than having to move the id randomness out of the inner loop like this.
    # XXX TODO: for the global randomness this uses we should add the thread-id
    # before the serial #.
    # XXX TODO: jam 20061102 I think it would be good to reset every 100 or
    #           1000 calls, or perhaps if time.time() increases by a certain
    #           amount. time.time() shouldn't be terribly expensive to call,
    #           and it means that long-lived processes wouldn't use the same
    #           suffix forever.
    global _gen_file_id_suffix, _gen_file_id_serial
    if _gen_file_id_suffix is None:
        _gen_file_id_suffix = "-%s-%s-" % (osutils.compact_date(time.time()),
                                           osutils.rand_chars(16))
    _gen_file_id_serial += 1
    return _gen_file_id_suffix + str(_gen_file_id_serial)


def gen_file_id(name):
    """Return new file id for the basename 'name'.

    The uniqueness is supplied from _next_id_suffix.
    """
    # The real randomness is in the _next_id_suffix, the
    # rest of the identifier is just to be nice.
    # So we:
    # 1) Remove non-ascii word characters to keep the ids portable
    # 2) squash to lowercase, so the file id doesn't have to
    #    be escaped (case insensitive filesystems would bork for ids
    #    that only differ in case without escaping).
    # 3) truncate the filename to 20 chars. Long filenames also bork on some
    #    filesystems
    # 4) Removing starting '.' characters to prevent the file ids from
    #    being considered hidden.
    ascii_word_only = str(_file_id_chars_re.sub('', name.lower()))
    short_no_dots = ascii_word_only.lstrip('.')[:20]
    return short_no_dots + _next_id_suffix()


def gen_root_id():
    """Return a new tree-root file id."""
    return gen_file_id('tree_root')


def gen_revision_id(username, timestamp=None):
    """Return new revision-id.

    :param username: This is the value returned by config.username(), which is
        typically a real name, followed by an email address. If found, we will
        use just the email address portion. Otherwise we flatten the real name,
        and use that.
    :return: A new revision id.
    """
    try:
        user_or_email = config.extract_email_address(username)
    except errors.NoEmailInUsername:
        user_or_email = username

    user_or_email = user_or_email.lower()
    user_or_email = user_or_email.replace(' ', '_')
    user_or_email = _rev_id_chars_re.sub('', user_or_email)

    # This gives 36^16 ~= 2^82.7 ~= 83 bits of entropy
    unique_chunk = osutils.rand_chars(16)

    if timestamp is None:
        timestamp = time.time()

    rev_id = u'-'.join((user_or_email,
                        osutils.compact_date(timestamp),
                        unique_chunk))
    return rev_id.encode('utf8')
