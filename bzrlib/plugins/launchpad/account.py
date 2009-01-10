# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Functions to manage the user's Launchpad user ID.

This allows the user to configure their Launchpad user ID once, rather
than once for each place that needs to take it into account.
"""

from bzrlib import errors, trace
from bzrlib.config import AuthenticationConfig, GlobalConfig
from bzrlib.transport import get_transport


LAUNCHPAD_BASE = 'https://launchpad.net/'


class UnknownLaunchpadUsername(errors.BzrError):
    _fmt = "The user name %(user)s is not registered on Launchpad."


class NoRegisteredSSHKeys(errors.BzrError):
    _fmt = "The user %(user)s has not registered any SSH keys with Launchpad.\n" \
        "See <https://launchpad.net/people/+me>"


class MismatchedUsernames(errors.BzrError):

    _fmt = ('bazaar.conf and authentication.conf disagree about launchpad'
            ' account name.  Please re-run launchpad-login.')


def get_lp_login(_config=None):
    """Return the user's Launchpad username.

    :raises: MismatchedUsername if authentication.conf and bazaar.conf
        disagree about username.
    """
    if _config is None:
        _config = GlobalConfig()

    username = _config.get_user_option('launchpad_username')
    if username is not None:
        auth = AuthenticationConfig()
        auth_username = _get_auth_user(auth)
        # Auto-upgrading
        if auth_username is None:
            trace.note('Setting ssh/sftp usernames for launchpad.net.')
            _set_auth_user(username, auth)
        elif auth_username != username:
            raise MismatchedUsernames()
    return username


def _set_global_option(username, _config=None):
    if _config is None:
        _config = GlobalConfig()
    _config.set_user_option('launchpad_username', username)


def set_lp_login(username, _config=None):
    """Set the user's Launchpad username"""
    _set_global_option(username, _config)
    _set_auth_user(username)


def _get_auth_user(auth=None):
    if auth is None:
        auth = AuthenticationConfig()
    return auth.get_user('ssh', '.launchpad.net')

def _set_auth_user(username, auth=None):
    if auth is None:
        auth = AuthenticationConfig()
    auth.set_credentials(
        'Launchpad', '.launchpad.net', username, 'ssh')


def check_lp_login(username, _transport=None):
    """Check whether the given Launchpad username is okay.

    This will check for both existence and whether the user has
    uploaded SSH keys.
    """
    if _transport is None:
        _transport = get_transport(LAUNCHPAD_BASE)

    try:
        data = _transport.get_bytes('~%s/+sshkeys' % username)
    except errors.NoSuchFile:
        raise UnknownLaunchpadUsername(user=username)

    if not data:
        raise NoRegisteredSSHKeys(user=username)
