# Copyright (C) 2005, 2007, 2008 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            and others
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

"""Configuration that affects the behaviour of Bazaar.

Currently this configuration resides in ~/.bazaar/bazaar.conf
and ~/.bazaar/locations.conf, which is written to by bzr.

In bazaar.conf the following options may be set:
[DEFAULT]
editor=name-of-program
email=Your Name <your@email.address>
check_signatures=require|ignore|check-available(default)
create_signatures=always|never|when-required(default)
gpg_signing_command=name-of-program
log_format=name-of-format

in locations.conf, you specify the url of a branch and options for it.
Wildcards may be used - * and ? as normal in shell completion. Options
set in both bazaar.conf and locations.conf are overridden by the locations.conf
setting.
[/home/robertc/source]
recurse=False|True(default)
email= as above
check_signatures= as above 
create_signatures= as above.

explanation of options
----------------------
editor - this option sets the pop up editor to use during commits.
email - this option sets the user id bzr will use when committing.
check_signatures - this option controls whether bzr will require good gpg
                   signatures, ignore them, or check them if they are 
                   present.
create_signatures - this option controls whether bzr will always create 
                    gpg signatures, never create them, or create them if the
                    branch is configured to require them.
log_format - this option sets the default log format.  Possible values are
             long, short, line, or a plugin can register new formats.

In bazaar.conf you can also define aliases in the ALIASES sections, example

[ALIASES]
lastlog=log --line -r-10..-1
ll=log --line -r-10..-1
h=help
up=pull
"""

import os
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
from fnmatch import fnmatch
import re
from cStringIO import StringIO

import bzrlib
from bzrlib import (
    debug,
    errors,
    mail_client,
    osutils,
    symbol_versioning,
    trace,
    ui,
    urlutils,
    win32utils,
    )
from bzrlib.util.configobj import configobj
""")


CHECK_IF_POSSIBLE=0
CHECK_ALWAYS=1
CHECK_NEVER=2


SIGN_WHEN_REQUIRED=0
SIGN_ALWAYS=1
SIGN_NEVER=2


POLICY_NONE = 0
POLICY_NORECURSE = 1
POLICY_APPENDPATH = 2

_policy_name = {
    POLICY_NONE: None,
    POLICY_NORECURSE: 'norecurse',
    POLICY_APPENDPATH: 'appendpath',
    }
_policy_value = {
    None: POLICY_NONE,
    'none': POLICY_NONE,
    'norecurse': POLICY_NORECURSE,
    'appendpath': POLICY_APPENDPATH,
    }


STORE_LOCATION = POLICY_NONE
STORE_LOCATION_NORECURSE = POLICY_NORECURSE
STORE_LOCATION_APPENDPATH = POLICY_APPENDPATH
STORE_BRANCH = 3
STORE_GLOBAL = 4

_ConfigObj = None
def ConfigObj(*args, **kwargs):
    global _ConfigObj
    if _ConfigObj is None:
        class ConfigObj(configobj.ConfigObj):

            def get_bool(self, section, key):
                return self[section].as_bool(key)

            def get_value(self, section, name):
                # Try [] for the old DEFAULT section.
                if section == "DEFAULT":
                    try:
                        return self[name]
                    except KeyError:
                        pass
                return self[section][name]
        _ConfigObj = ConfigObj
    return _ConfigObj(*args, **kwargs)


class Config(object):
    """A configuration policy - what username, editor, gpg needs etc."""

    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def get_mail_client(self):
        """Get a mail client to use"""
        selected_client = self.get_user_option('mail_client')
        _registry = mail_client.mail_client_registry
        try:
            mail_client_class = _registry.get(selected_client)
        except KeyError:
            raise errors.UnknownMailClient(selected_client)
        return mail_client_class(self)

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def _get_signing_policy(self):
        """Template method to override signature creation policy."""

    def _get_user_option(self, option_name):
        """Template method to provide a user option."""
        return None

    def get_user_option(self, option_name):
        """Get a generic option - no special process, no default."""
        return self._get_user_option(option_name)

    def gpg_signing_command(self):
        """What program should be used to sign signatures?"""
        result = self._gpg_signing_command()
        if result is None:
            result = "gpg"
        return result

    def _gpg_signing_command(self):
        """See gpg_signing_command()."""
        return None

    def log_format(self):
        """What log format should be used"""
        result = self._log_format()
        if result is None:
            result = "long"
        return result

    def _log_format(self):
        """See log_format()."""
        return None

    def __init__(self):
        super(Config, self).__init__()

    def post_commit(self):
        """An ordered list of python functions to call.

        Each function takes branch, rev_id as parameters.
        """
        return self._post_commit()

    def _post_commit(self):
        """See Config.post_commit."""
        return None

    def user_email(self):
        """Return just the email component of a username."""
        return extract_email_address(self.username())

    def username(self):
        """Return email-style username.
    
        Something similar to 'Martin Pool <mbp@sourcefrog.net>'
        
        $BZR_EMAIL can be set to override this (as well as the
        deprecated $BZREMAIL), then
        the concrete policy type is checked, and finally
        $EMAIL is examined.
        If none is found, a reasonable default is (hopefully)
        created.
    
        TODO: Check it's reasonably well-formed.
        """
        v = os.environ.get('BZR_EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())

        v = self._get_user_id()
        if v:
            return v

        v = os.environ.get('EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())

        name, email = _auto_user_id()
        if name:
            return '%s <%s>' % (name, email)
        else:
            return email

    def signature_checking(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signature_checking()
        if policy is not None:
            return policy
        return CHECK_IF_POSSIBLE

    def signing_policy(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signing_policy()
        if policy is not None:
            return policy
        return SIGN_WHEN_REQUIRED

    def signature_needed(self):
        """Is a signature needed when committing ?."""
        policy = self._get_signing_policy()
        if policy is None:
            policy = self._get_signature_checking()
            if policy is not None:
                trace.warning("Please use create_signatures,"
                              " not check_signatures to set signing policy.")
            if policy == CHECK_ALWAYS:
                return True
        elif policy == SIGN_ALWAYS:
            return True
        return False

    def get_alias(self, value):
        return self._get_alias(value)

    def _get_alias(self, value):
        pass

    def get_nickname(self):
        return self._get_nickname()

    def _get_nickname(self):
        return None

    def get_bzr_remote_path(self):
        try:
            return os.environ['BZR_REMOTE_PATH']
        except KeyError:
            path = self.get_user_option("bzr_remote_path")
            if path is None:
                path = 'bzr'
            return path


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def _get_parser(self, file=None):
        if self._parser is not None:
            return self._parser
        if file is None:
            input = self._get_filename()
        else:
            input = file
        try:
            self._parser = ConfigObj(input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        return self._parser

    def _get_matching_sections(self):
        """Return an ordered list of (section_name, extra_path) pairs.

        If the section contains inherited configuration, extra_path is
        a string containing the additional path components.
        """
        section = self._get_section()
        if section is not None:
            return [(section, '')]
        else:
            return []

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        return POLICY_NONE

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        policy = self._get_user_option('check_signatures')
        if policy:
            return self._string_to_signature_policy(policy)

    def _get_signing_policy(self):
        """See Config._get_signing_policy"""
        policy = self._get_user_option('create_signatures')
        if policy:
            return self._string_to_signing_policy(policy)

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option('email')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for (section, extra_path) in self._get_matching_sections():
            try:
                value = self._get_parser().get_value(section, option_name)
            except KeyError:
                continue
            policy = self._get_option_policy(section, option_name)
            if policy == POLICY_NONE:
                return value
            elif policy == POLICY_NORECURSE:
                # norecurse items only apply to the exact path
                if extra_path:
                    continue
                else:
                    return value
            elif policy == POLICY_APPENDPATH:
                if extra_path:
                    value = urlutils.join(value, extra_path)
                return value
            else:
                raise AssertionError('Unexpected config policy %r' % policy)
        else:
            return None

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_user_option('gpg_signing_command')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_user_option('log_format')

    def __init__(self, get_filename):
        super(IniBasedConfig, self).__init__()
        self._get_filename = get_filename
        self._parser = None
        
    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_user_option('post_commit')

    def _string_to_signature_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'check-available':
            return CHECK_IF_POSSIBLE
        if signature_string.lower() == 'ignore':
            return CHECK_NEVER
        if signature_string.lower() == 'require':
            return CHECK_ALWAYS
        raise errors.BzrError("Invalid signatures policy '%s'"
                              % signature_string)

    def _string_to_signing_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'when-required':
            return SIGN_WHEN_REQUIRED
        if signature_string.lower() == 'never':
            return SIGN_NEVER
        if signature_string.lower() == 'always':
            return SIGN_ALWAYS
        raise errors.BzrError("Invalid signing policy '%s'"
                              % signature_string)

    def _get_alias(self, value):
        try:
            return self._get_parser().get_value("ALIASES", 
                                                value)
        except KeyError:
            pass

    def _get_nickname(self):
        return self.get_user_option('nickname')


class GlobalConfig(IniBasedConfig):
    """The configuration that should be used for a specific location."""

    def get_editor(self):
        return self._get_user_option('editor')

    def __init__(self):
        super(GlobalConfig, self).__init__(config_filename)

    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        self._set_option(option, value, 'DEFAULT')

    def get_aliases(self):
        """Return the aliases section."""
        if 'ALIASES' in self._get_parser():
            return self._get_parser()['ALIASES']
        else:
            return {}

    def set_alias(self, alias_name, alias_command):
        """Save the alias in the configuration."""
        self._set_option(alias_name, alias_command, 'ALIASES')

    def unset_alias(self, alias_name):
        """Unset an existing alias."""
        aliases = self._get_parser().get('ALIASES')
        if not aliases or alias_name not in aliases:
            raise errors.NoSuchAlias(alias_name)
        del aliases[alias_name]
        self._write_config_file()

    def _set_option(self, option, value, section):
        # FIXME: RBC 20051029 This should refresh the parser and also take a
        # file lock on bazaar.conf.
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        self._get_parser().setdefault(section, {})[option] = value
        self._write_config_file()

    def _write_config_file(self):
        f = open(self._get_filename(), 'wb')
        self._get_parser().write(f)
        f.close()


class LocationConfig(IniBasedConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        name_generator = locations_config_filename
        if (not os.path.exists(name_generator()) and
                os.path.exists(branches_config_filename())):
            if sys.platform == 'win32':
                trace.warning('Please rename %s to %s'
                              % (branches_config_filename(),
                                 locations_config_filename()))
            else:
                trace.warning('Please rename ~/.bazaar/branches.conf'
                              ' to ~/.bazaar/locations.conf')
            name_generator = branches_config_filename
        super(LocationConfig, self).__init__(name_generator)
        # local file locations are looked up by local path, rather than
        # by file url. This is because the config file is a user
        # file, and we would rather not expose the user to file urls.
        if location.startswith('file://'):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def _get_matching_sections(self):
        """Return an ordered list of section names matching this location."""
        sections = self._get_parser()
        location_names = self.location.split('/')
        if self.location.endswith('/'):
            del location_names[-1]
        matches=[]
        for section in sections:
            # location is a local path if possible, so we need
            # to convert 'file://' urls to local paths if necessary.
            # This also avoids having file:///path be a more exact
            # match than '/path'.
            if section.startswith('file://'):
                section_path = urlutils.local_path_from_url(section)
            else:
                section_path = section
            section_names = section_path.split('/')
            if section.endswith('/'):
                del section_names[-1]
            names = zip(location_names, section_names)
            matched = True
            for name in names:
                if not fnmatch(name[0], name[1]):
                    matched = False
                    break
            if not matched:
                continue
            # so, for the common prefix they matched.
            # if section is longer, no match.
            if len(section_names) > len(location_names):
                continue
            matches.append((len(section_names), section,
                            '/'.join(location_names[len(section_names):])))
        matches.sort(reverse=True)
        sections = []
        for (length, section, extra_path) in matches:
            sections.append((section, extra_path))
            # should we stop looking for parent configs here?
            try:
                if self._get_parser()[section].as_bool('ignore_parents'):
                    break
            except KeyError:
                pass
        return sections

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        # check for the old 'recurse=False' flag
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            recurse = True
        if not recurse:
            return POLICY_NORECURSE

        policy_key = option_name + ':policy'
        try:
            policy_name = self._get_parser()[section][policy_key]
        except KeyError:
            policy_name = None

        return _policy_value[policy_name]

    def _set_option_policy(self, section, option_name, option_policy):
        """Set the policy for the given option name in the given section."""
        # The old recurse=False option affects all options in the
        # section.  To handle multiple policies in the section, we
        # need to convert it to a policy_norecurse key.
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            pass
        else:
            symbol_versioning.warn(
                'The recurse option is deprecated as of 0.14.  '
                'The section "%s" has been converted to use policies.'
                % section,
                DeprecationWarning)
            del self._get_parser()[section]['recurse']
            if not recurse:
                for key in self._get_parser()[section].keys():
                    if not key.endswith(':policy'):
                        self._get_parser()[section][key +
                                                    ':policy'] = 'norecurse'

        policy_key = option_name + ':policy'
        policy_name = _policy_name[option_policy]
        if policy_name is not None:
            self._get_parser()[section][policy_key] = policy_name
        else:
            if policy_key in self._get_parser()[section]:
                del self._get_parser()[section][policy_key]

    def set_user_option(self, option, value, store=STORE_LOCATION):
        """Save option and its value in the configuration."""
        if store not in [STORE_LOCATION,
                         STORE_LOCATION_NORECURSE,
                         STORE_LOCATION_APPENDPATH]:
            raise ValueError('bad storage policy %r for %r' %
                (store, option))
        # FIXME: RBC 20051029 This should refresh the parser and also take a
        # file lock on locations.conf.
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        location = self.location
        if location.endswith('/'):
            location = location[:-1]
        if (not location in self._get_parser() and
            not location + '/' in self._get_parser()):
            self._get_parser()[location]={}
        elif location + '/' in self._get_parser():
            location = location + '/'
        self._get_parser()[location][option]=value
        # the allowed values of store match the config policies
        self._set_option_policy(location, option, store)
        self._get_parser().write(file(self._get_filename(), 'wb'))


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def _get_branch_data_config(self):
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch)
        return self._branch_data_config

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_global_config(self):
        if self._global_config is None:
            self._global_config = GlobalConfig()
        return self._global_config

    def _get_best_value(self, option_name):
        """This returns a user option from local, tree or global config.

        They are tried in that order.  Use get_safe_value if trusted values
        are necessary.
        """
        for source in self.option_sources:
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_safe_value(self, option_name):
        """This variant of get_best_value never returns untrusted values.
        
        It does not return values from the branch data, because the branch may
        not be controlled by the user.

        We may wish to allow locations.conf to control whether branches are
        trusted in the future.
        """
        for source in (self._get_location_config, self._get_global_config):
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_user_id(self):
        """Return the full user id for the branch.
    
        e.g. "John Hacker <jhacker@example.com>"
        This is looked up in the email controlfile for the branch.
        """
        try:
            return (self.branch._transport.get_bytes("email")
                    .decode(osutils.get_user_encoding())
                    .rstrip("\r\n"))
        except errors.NoSuchFile, e:
            pass
        
        return self._get_best_value('_get_user_id')

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        return self._get_best_value('_get_signature_checking')

    def _get_signing_policy(self):
        """See Config._get_signing_policy."""
        return self._get_best_value('_get_signing_policy')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for source in self.option_sources:
            value = source()._get_user_option(option_name)
            if value is not None:
                return value
        return None

    def set_user_option(self, name, value, store=STORE_BRANCH,
        warn_masked=False):
        if store == STORE_BRANCH:
            self._get_branch_data_config().set_option(value, name)
        elif store == STORE_GLOBAL:
            self._get_global_config().set_user_option(name, value)
        else:
            self._get_location_config().set_user_option(name, value, store)
        if not warn_masked:
            return
        if store in (STORE_GLOBAL, STORE_BRANCH):
            mask_value = self._get_location_config().get_user_option(name)
            if mask_value is not None:
                trace.warning('Value "%s" is masked by "%s" from'
                              ' locations.conf', value, mask_value)
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning('Value "%s" is masked by "%s" from'
                                      ' branch.conf', value, mask_value)


    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_safe_value('_gpg_signing_command')
        
    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._branch_data_config = None
        self._global_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config, 
                               self._get_branch_data_config,
                               self._get_global_config)

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_safe_value('_post_commit')

    def _get_nickname(self):
        value = self._get_explicit_nickname()
        if value is not None:
            return value
        return urlutils.unescape(self.branch.base.split('/')[-2])

    def has_explicit_nickname(self):
        """Return true if a nickname has been explicitly assigned."""
        return self._get_explicit_nickname() is not None

    def _get_explicit_nickname(self):
        return self._get_best_value('_get_nickname')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_best_value('_log_format')


def ensure_config_dir_exists(path=None):
    """Make sure a configuration directory exists.
    This makes sure that the directory exists.
    On windows, since configuration directories are 2 levels deep,
    it makes sure both the directory and the parent directory exists.
    """
    if path is None:
        path = config_dir()
    if not os.path.isdir(path):
        if sys.platform == 'win32':
            parent_dir = os.path.dirname(path)
            if not os.path.isdir(parent_dir):
                trace.mutter('creating config parent directory: %r', parent_dir)
            os.mkdir(parent_dir)
        trace.mutter('creating config directory: %r', path)
        os.mkdir(path)


def config_dir():
    """Return per-user configuration directory.

    By default this is ~/.bazaar/
    
    TODO: Global option --config-dir to override this.
    """
    base = os.environ.get('BZR_HOME', None)
    if sys.platform == 'win32':
        if base is None:
            base = win32utils.get_appdata_location_unicode()
        if base is None:
            base = os.environ.get('HOME', None)
        if base is None:
            raise errors.BzrError('You must have one of BZR_HOME, APPDATA,'
                                  ' or HOME set')
        return osutils.pathjoin(base, 'bazaar', '2.0')
    else:
        # cygwin, linux, and darwin all have a $HOME directory
        if base is None:
            base = os.path.expanduser("~")
        return osutils.pathjoin(base, ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'bazaar.conf')


def branches_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'branches.conf')


def locations_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'locations.conf')


def authentication_config_filename():
    """Return per-user authentication ini file filename."""
    return osutils.pathjoin(config_dir(), 'authentication.conf')


def user_ignore_config_filename():
    """Return the user default ignore filename"""
    return osutils.pathjoin(config_dir(), 'ignore')


def _auto_user_id():
    """Calculate automatic user identification.

    Returns (realname, email).

    Only used when none is set in the environment or the id file.

    This previously used the FQDN as the default domain, but that can
    be very slow on machines where DNS is broken.  So now we simply
    use the hostname.
    """
    import socket

    if sys.platform == 'win32':
        name = win32utils.get_user_name_unicode()
        if name is None:
            raise errors.BzrError("Cannot autodetect user name.\n"
                                  "Please, set your name with command like:\n"
                                  'bzr whoami "Your Name <name@domain.com>"')
        host = win32utils.get_host_name_unicode()
        if host is None:
            host = socket.gethostname()
        return name, (name + '@' + host)

    try:
        import pwd
        uid = os.getuid()
        try:
            w = pwd.getpwuid(uid)
        except KeyError:
            raise errors.BzrCommandError('Unable to determine your name.  '
                'Please use "bzr whoami" to set it.')

        # we try utf-8 first, because on many variants (like Linux),
        # /etc/passwd "should" be in utf-8, and because it's unlikely to give
        # false positives.  (many users will have their user encoding set to
        # latin-1, which cannot raise UnicodeError.)
        try:
            gecos = w.pw_gecos.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeError:
            try:
                encoding = osutils.get_user_encoding()
                gecos = w.pw_gecos.decode(encoding)
            except UnicodeError:
                raise errors.BzrCommandError('Unable to determine your name.  '
                   'Use "bzr whoami" to set it.')
        try:
            username = w.pw_name.decode(encoding)
        except UnicodeError:
            raise errors.BzrCommandError('Unable to determine your name.  '
                'Use "bzr whoami" to set it.')

        comma = gecos.find(',')
        if comma == -1:
            realname = gecos
        else:
            realname = gecos[:comma]
        if not realname:
            realname = username

    except ImportError:
        import getpass
        try:
            user_encoding = osutils.get_user_encoding()
            realname = username = getpass.getuser().decode(user_encoding)
        except UnicodeDecodeError:
            raise errors.BzrError("Can't decode username as %s." % \
                    user_encoding)

    return realname, (username + '@' + socket.gethostname())


def parse_username(username):
    """Parse e-mail username and return a (name, address) tuple."""
    match = re.match(r'(.*?)\s*<?([\w+.-]+@[\w+.-]+)>?', username)
    if match is None:
        return (username, '')
    else:
        return (match.group(1), match.group(2))


def extract_email_address(e):
    """Return just the address part of an email string.

    That is just the user@domain part, nothing else. 
    This part is required to contain only ascii characters.
    If it can't be extracted, raises an error.

    >>> extract_email_address('Jane Tester <jane@test.com>')
    "jane@test.com"
    """
    name, email = parse_username(e)
    if not email:
        raise errors.NoEmailInUsername(e)
    return email


class TreeConfig(IniBasedConfig):
    """Branch configuration data associated with its contents, not location"""

    # XXX: Really needs a better name, as this is not part of the tree! -- mbp 20080507

    def __init__(self, branch):
        # XXX: Really this should be asking the branch for its configuration
        # data, rather than relying on a Transport, so that it can work 
        # more cleanly with a RemoteBranch that has no transport.
        self._config = TransportConfig(branch._transport, 'branch.conf')
        self.branch = branch

    def _get_parser(self, file=None):
        if file is not None:
            return IniBasedConfig._get_parser(file)
        return self._config._get_configobj()

    def get_option(self, name, section=None, default=None):
        self.branch.lock_read()
        try:
            return self._config.get_option(name, section, default)
        finally:
            self.branch.unlock()
        return result

    def set_option(self, value, name, section=None):
        """Set a per-branch configuration option"""
        self.branch.lock_write()
        try:
            self._config.set_option(value, name, section)
        finally:
            self.branch.unlock()


class AuthenticationConfig(object):
    """The authentication configuration file based on a ini file.

    Implements the authentication.conf file described in
    doc/developers/authentication-ring.txt.
    """

    def __init__(self, _file=None):
        self._config = None # The ConfigObj
        if _file is None:
            self._filename = authentication_config_filename()
            self._input = self._filename = authentication_config_filename()
        else:
            # Tests can provide a string as _file
            self._filename = None
            self._input = _file

    def _get_config(self):
        if self._config is not None:
            return self._config
        try:
            # FIXME: Should we validate something here ? Includes: empty
            # sections are useless, at least one of
            # user/password/password_encoding should be defined, etc.

            # Note: the encoding below declares that the file itself is utf-8
            # encoded, but the values in the ConfigObj are always Unicode.
            self._config = ConfigObj(self._input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        return self._config

    def _save(self):
        """Save the config file, only tests should use it for now."""
        conf_dir = os.path.dirname(self._filename)
        ensure_config_dir_exists(conf_dir)
        self._get_config().write(file(self._filename, 'wb'))

    def _set_option(self, section_name, option_name, value):
        """Set an authentication configuration option"""
        conf = self._get_config()
        section = conf.get(section_name)
        if section is None:
            conf[section] = {}
            section = conf[section]
        section[option_name] = value
        self._save()

    def get_credentials(self, scheme, host, port=None, user=None, path=None):
        """Returns the matching credentials from authentication.conf file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login (optional)

        :param path: the absolute path on the server (optional)

        :return: A dict containing the matching credentials or None.
           This includes:
           - name: the section name of the credentials in the
             authentication.conf file,
           - user: can't de different from the provided user if any,
           - password: the decoded password, could be None if the credential
             defines only the user
           - verify_certificates: https specific, True if the server
             certificate should be verified, False otherwise.
        """
        credentials = None
        for auth_def_name, auth_def in self._get_config().items():
            if type(auth_def) is not configobj.Section:
                raise ValueError("%s defined outside a section" % auth_def_name)

            a_scheme, a_host, a_user, a_path = map(
                auth_def.get, ['scheme', 'host', 'user', 'path'])

            try:
                a_port = auth_def.as_int('port')
            except KeyError:
                a_port = None
            except ValueError:
                raise ValueError("'port' not numeric in %s" % auth_def_name)
            try:
                a_verify_certificates = auth_def.as_bool('verify_certificates')
            except KeyError:
                a_verify_certificates = True
            except ValueError:
                raise ValueError(
                    "'verify_certificates' not boolean in %s" % auth_def_name)

            # Attempt matching
            if a_scheme is not None and scheme != a_scheme:
                continue
            if a_host is not None:
                if not (host == a_host
                        or (a_host.startswith('.') and host.endswith(a_host))):
                    continue
            if a_port is not None and port != a_port:
                continue
            if (a_path is not None and path is not None
                and not path.startswith(a_path)):
                continue
            if (a_user is not None and user is not None
                and a_user != user):
                # Never contradict the caller about the user to be used
                continue
            if a_user is None:
                # Can't find a user
                continue
            credentials = dict(name=auth_def_name,
                               user=a_user,
                               password=auth_def.get('password', None),
                               verify_certificates=a_verify_certificates)
            self.decode_password(credentials,
                                 auth_def.get('password_encoding', None))
            if 'auth' in debug.debug_flags:
                trace.mutter("Using authentication section: %r", auth_def_name)
            break

        return credentials

    def set_credentials(self, name, host, user, scheme=None, password=None,
                        port=None, path=None, verify_certificates=None):
        """Set authentication credentials for a host.

        Any existing credentials with matching scheme, host, port and path
        will be deleted, regardless of name.

        :param name: An arbitrary name to describe this set of credentials.
        :param host: Name of the host that accepts these credentials.
        :param user: The username portion of these credentials.
        :param scheme: The URL scheme (e.g. ssh, http) the credentials apply
            to.
        :param password: Password portion of these credentials.
        :param port: The IP port on the host that these credentials apply to.
        :param path: A filesystem path on the host that these credentials
            apply to.
        :param verify_certificates: On https, verify server certificates if
            True.
        """
        values = {'host': host, 'user': user}
        if password is not None:
            values['password'] = password
        if scheme is not None:
            values['scheme'] = scheme
        if port is not None:
            values['port'] = '%d' % port
        if path is not None:
            values['path'] = path
        if verify_certificates is not None:
            values['verify_certificates'] = str(verify_certificates)
        config = self._get_config()
        for_deletion = []
        for section, existing_values in config.items():
            for key in ('scheme', 'host', 'port', 'path'):
                if existing_values.get(key) != values.get(key):
                    break
            else:
                del config[section]
        config.update({name: values})
        self._save()

    def get_user(self, scheme, host, port=None,
                 realm=None, path=None, prompt=None):
        """Get a user from authentication file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :return: The found user.
        """
        credentials = self.get_credentials(scheme, host, port, user=None,
                                           path=path)
        if credentials is not None:
            user = credentials['user']
        else:
            user = None
        return user

    def get_password(self, scheme, host, user, port=None,
                     realm=None, path=None, prompt=None):
        """Get a password from authentication file or prompt the user for one.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :return: The found password or the one entered by the user.
        """
        credentials = self.get_credentials(scheme, host, port, user, path)
        if credentials is not None:
            password = credentials['password']
            if password is not None and scheme is 'ssh':
                trace.warning('password ignored in section [%s],'
                              ' use an ssh agent instead'
                              % credentials['name'])
                password = None
        else:
            password = None
        # Prompt user only if we could't find a password
        if password is None:
            if prompt is None:
                # Create a default prompt suitable for most cases
                prompt = '%s' % scheme.upper() + ' %(user)s@%(host)s password'
            # Special handling for optional fields in the prompt
            if port is not None:
                prompt_host = '%s:%d' % (host, port)
            else:
                prompt_host = host
            password = ui.ui_factory.get_password(prompt,
                                                  host=prompt_host, user=user)
        return password

    def decode_password(self, credentials, encoding):
        return credentials


class BzrDirConfig(object):

    def __init__(self, transport):
        self._config = TransportConfig(transport, 'control.conf')

    def set_default_stack_on(self, value):
        """Set the default stacking location.

        It may be set to a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        if value is None:
            self._config.set_option('', 'default_stack_on')
        else:
            self._config.set_option(value, 'default_stack_on')

    def get_default_stack_on(self):
        """Return the default stacking location.

        This will either be a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        value = self._config.get_option('default_stack_on')
        if value == '':
            value = None
        return value


class TransportConfig(object):
    """A Config that reads/writes a config file on a Transport.

    It is a low-level object that considers config data to be name/value pairs
    that may be associated with a section.  Assigning meaning to the these
    values is done at higher levels like TreeConfig.
    """

    def __init__(self, transport, filename):
        self._transport = transport
        self._filename = filename

    def get_option(self, name, section=None, default=None):
        """Return the value associated with a named option.

        :param name: The name of the value
        :param section: The section the option is in (if any)
        :param default: The value to return if the value is not set
        :return: The value or default value
        """
        configobj = self._get_configobj()
        if section is None:
            section_obj = configobj
        else:
            try:
                section_obj = configobj[section]
            except KeyError:
                return default
        return section_obj.get(name, default)

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        :param value: The value to set
        :param name: The name of the value to set
        :param section: The section the option is in (if any)
        """
        configobj = self._get_configobj()
        if section is None:
            configobj[name] = value
        else:
            configobj.setdefault(section, {})[name] = value
        self._set_configobj(configobj)

    def _get_configobj(self):
        try:
            return ConfigObj(self._transport.get(self._filename),
                             encoding='utf-8')
        except errors.NoSuchFile:
            return ConfigObj(encoding='utf-8')

    def _set_configobj(self, configobj):
        out_file = StringIO()
        configobj.write(out_file)
        out_file.seek(0)
        self._transport.put_file(self._filename, out_file)
