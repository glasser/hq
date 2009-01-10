# Copyright (C) 2005 Robey Pointer <robey@lag.net>
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

"""Foundation SSH support for SFTP and smart server."""

import errno
import getpass
import os
import socket
import subprocess
import sys

from bzrlib import (
    config,
    errors,
    osutils,
    trace,
    ui,
    )

try:
    import paramiko
except ImportError, e:
    # If we have an ssh subprocess, we don't strictly need paramiko for all ssh
    # access
    paramiko = None
else:
    from paramiko.sftp_client import SFTPClient


SYSTEM_HOSTKEYS = {}
BZR_HOSTKEYS = {}


_paramiko_version = getattr(paramiko, '__version_info__', (0, 0, 0))

# Paramiko 1.5 tries to open a socket.AF_UNIX in order to connect
# to ssh-agent. That attribute doesn't exist on win32 (it does in cygwin)
# so we get an AttributeError exception. So we will not try to
# connect to an agent if we are on win32 and using Paramiko older than 1.6
_use_ssh_agent = (sys.platform != 'win32' or _paramiko_version >= (1, 6, 0))


class SSHVendorManager(object):
    """Manager for manage SSH vendors."""

    # Note, although at first sign the class interface seems similar to
    # bzrlib.registry.Registry it is not possible/convenient to directly use
    # the Registry because the class just has "get()" interface instead of the
    # Registry's "get(key)".

    def __init__(self):
        self._ssh_vendors = {}
        self._cached_ssh_vendor = None
        self._default_ssh_vendor = None

    def register_default_vendor(self, vendor):
        """Register default SSH vendor."""
        self._default_ssh_vendor = vendor

    def register_vendor(self, name, vendor):
        """Register new SSH vendor by name."""
        self._ssh_vendors[name] = vendor

    def clear_cache(self):
        """Clear previously cached lookup result."""
        self._cached_ssh_vendor = None

    def _get_vendor_by_environment(self, environment=None):
        """Return the vendor or None based on BZR_SSH environment variable.

        :raises UnknownSSH: if the BZR_SSH environment variable contains
                            unknown vendor name
        """
        if environment is None:
            environment = os.environ
        if 'BZR_SSH' in environment:
            vendor_name = environment['BZR_SSH']
            try:
                vendor = self._ssh_vendors[vendor_name]
            except KeyError:
                raise errors.UnknownSSH(vendor_name)
            return vendor
        return None

    def _get_ssh_version_string(self, args):
        """Return SSH version string from the subprocess."""
        try:
            p = subprocess.Popen(args,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 **os_specific_subprocess_params())
            stdout, stderr = p.communicate()
        except OSError:
            stdout = stderr = ''
        return stdout + stderr

    def _get_vendor_by_version_string(self, version, args):
        """Return the vendor or None based on output from the subprocess.

        :param version: The output of 'ssh -V' like command.
        :param args: Command line that was run.
        """
        vendor = None
        if 'OpenSSH' in version:
            trace.mutter('ssh implementation is OpenSSH')
            vendor = OpenSSHSubprocessVendor()
        elif 'SSH Secure Shell' in version:
            trace.mutter('ssh implementation is SSH Corp.')
            vendor = SSHCorpSubprocessVendor()
        elif 'plink' in version and args[0] == 'plink':
            # Checking if "plink" was the executed argument as Windows
            # sometimes reports 'ssh -V' incorrectly with 'plink' in it's
            # version.  See https://bugs.launchpad.net/bzr/+bug/107155
            trace.mutter("ssh implementation is Putty's plink.")
            vendor = PLinkSubprocessVendor()
        return vendor

    def _get_vendor_by_inspection(self):
        """Return the vendor or None by checking for known SSH implementations."""
        for args in (['ssh', '-V'], ['plink', '-V']):
            version = self._get_ssh_version_string(args)
            vendor = self._get_vendor_by_version_string(version, args)
            if vendor is not None:
                return vendor
        return None

    def get_vendor(self, environment=None):
        """Find out what version of SSH is on the system.

        :raises SSHVendorNotFound: if no any SSH vendor is found
        :raises UnknownSSH: if the BZR_SSH environment variable contains
                            unknown vendor name
        """
        if self._cached_ssh_vendor is None:
            vendor = self._get_vendor_by_environment(environment)
            if vendor is None:
                vendor = self._get_vendor_by_inspection()
                if vendor is None:
                    trace.mutter('falling back to default implementation')
                    vendor = self._default_ssh_vendor
                    if vendor is None:
                        raise errors.SSHVendorNotFound()
            self._cached_ssh_vendor = vendor
        return self._cached_ssh_vendor

_ssh_vendor_manager = SSHVendorManager()
_get_ssh_vendor = _ssh_vendor_manager.get_vendor
register_default_ssh_vendor = _ssh_vendor_manager.register_default_vendor
register_ssh_vendor = _ssh_vendor_manager.register_vendor


def _ignore_sigint():
    # TODO: This should possibly ignore SIGHUP as well, but bzr currently
    # doesn't handle it itself.
    # <https://launchpad.net/products/bzr/+bug/41433/+index>
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)


class SocketAsChannelAdapter(object):
    """Simple wrapper for a socket that pretends to be a paramiko Channel."""

    def __init__(self, sock):
        self.__socket = sock

    def get_name(self):
        return "bzr SocketAsChannelAdapter"
    
    def send(self, data):
        return self.__socket.send(data)

    def recv(self, n):
        try:
            return self.__socket.recv(n)
        except socket.error, e:
            if e.args[0] in (errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED,
                             errno.EBADF):
                # Connection has closed.  Paramiko expects an empty string in
                # this case, not an exception.
                return ''
            raise

    def recv_ready(self):
        # TODO: jam 20051215 this function is necessary to support the
        # pipelined() function. In reality, it probably should use
        # poll() or select() to actually return if there is data
        # available, otherwise we probably don't get any benefit
        return True

    def close(self):
        self.__socket.close()


class SSHVendor(object):
    """Abstract base class for SSH vendor implementations."""

    def connect_sftp(self, username, password, host, port):
        """Make an SSH connection, and return an SFTPClient.
        
        :param username: an ascii string
        :param password: an ascii string
        :param host: a host name as an ascii string
        :param port: a port number
        :type port: int

        :raises: ConnectionError if it cannot connect.

        :rtype: paramiko.sftp_client.SFTPClient
        """
        raise NotImplementedError(self.connect_sftp)

    def connect_ssh(self, username, password, host, port, command):
        """Make an SSH connection.
        
        :returns: something with a `close` method, and a `get_filelike_channels`
            method that returns a pair of (read, write) filelike objects.
        """
        raise NotImplementedError(self.connect_ssh)

    def _raise_connection_error(self, host, port=None, orig_error=None,
                                msg='Unable to connect to SSH host'):
        """Raise a SocketConnectionError with properly formatted host.

        This just unifies all the locations that try to raise ConnectionError,
        so that they format things properly.
        """
        raise errors.SocketConnectionError(host=host, port=port, msg=msg,
                                           orig_error=orig_error)


class LoopbackVendor(SSHVendor):
    """SSH "vendor" that connects over a plain TCP socket, not SSH."""

    def connect_sftp(self, username, password, host, port):
        sock = socket.socket()
        try:
            sock.connect((host, port))
        except socket.error, e:
            self._raise_connection_error(host, port=port, orig_error=e)
        return SFTPClient(SocketAsChannelAdapter(sock))

register_ssh_vendor('loopback', LoopbackVendor())


class _ParamikoSSHConnection(object):
    def __init__(self, channel):
        self.channel = channel

    def get_filelike_channels(self):
        return self.channel.makefile('rb'), self.channel.makefile('wb')

    def close(self):
        return self.channel.close()


class ParamikoVendor(SSHVendor):
    """Vendor that uses paramiko."""

    def _connect(self, username, password, host, port):
        global SYSTEM_HOSTKEYS, BZR_HOSTKEYS

        load_host_keys()

        try:
            t = paramiko.Transport((host, port or 22))
            t.set_log_channel('bzr.paramiko')
            t.start_client()
        except (paramiko.SSHException, socket.error), e:
            self._raise_connection_error(host, port=port, orig_error=e)

        server_key = t.get_remote_server_key()
        server_key_hex = paramiko.util.hexify(server_key.get_fingerprint())
        keytype = server_key.get_name()
        if host in SYSTEM_HOSTKEYS and keytype in SYSTEM_HOSTKEYS[host]:
            our_server_key = SYSTEM_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(
                our_server_key.get_fingerprint())
        elif host in BZR_HOSTKEYS and keytype in BZR_HOSTKEYS[host]:
            our_server_key = BZR_HOSTKEYS[host][keytype]
            our_server_key_hex = paramiko.util.hexify(
                our_server_key.get_fingerprint())
        else:
            trace.warning('Adding %s host key for %s: %s'
                          % (keytype, host, server_key_hex))
            add = getattr(BZR_HOSTKEYS, 'add', None)
            if add is not None: # paramiko >= 1.X.X
                BZR_HOSTKEYS.add(host, keytype, server_key)
            else:
                BZR_HOSTKEYS.setdefault(host, {})[keytype] = server_key
            our_server_key = server_key
            our_server_key_hex = paramiko.util.hexify(
                our_server_key.get_fingerprint())
            save_host_keys()
        if server_key != our_server_key:
            filename1 = os.path.expanduser('~/.ssh/known_hosts')
            filename2 = osutils.pathjoin(config.config_dir(), 'ssh_host_keys')
            raise errors.TransportError(
                'Host keys for %s do not match!  %s != %s' %
                (host, our_server_key_hex, server_key_hex),
                ['Try editing %s or %s' % (filename1, filename2)])

        _paramiko_auth(username, password, host, port, t)
        return t

    def connect_sftp(self, username, password, host, port):
        t = self._connect(username, password, host, port)
        try:
            return t.open_sftp_client()
        except paramiko.SSHException, e:
            self._raise_connection_error(host, port=port, orig_error=e,
                                         msg='Unable to start sftp client')

    def connect_ssh(self, username, password, host, port, command):
        t = self._connect(username, password, host, port)
        try:
            channel = t.open_session()
            cmdline = ' '.join(command)
            channel.exec_command(cmdline)
            return _ParamikoSSHConnection(channel)
        except paramiko.SSHException, e:
            self._raise_connection_error(host, port=port, orig_error=e,
                                         msg='Unable to invoke remote bzr')

if paramiko is not None:
    vendor = ParamikoVendor()
    register_ssh_vendor('paramiko', vendor)
    register_ssh_vendor('none', vendor)
    register_default_ssh_vendor(vendor)
    _sftp_connection_errors = (EOFError, paramiko.SSHException)
    del vendor
else:
    _sftp_connection_errors = (EOFError,)


class SubprocessVendor(SSHVendor):
    """Abstract base class for vendors that use pipes to a subprocess."""

    def _connect(self, argv):
        proc = subprocess.Popen(argv,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                **os_specific_subprocess_params())
        return SSHSubprocess(proc)

    def connect_sftp(self, username, password, host, port):
        try:
            argv = self._get_vendor_specific_argv(username, host, port,
                                                  subsystem='sftp')
            sock = self._connect(argv)
            return SFTPClient(SocketAsChannelAdapter(sock))
        except _sftp_connection_errors, e:
            self._raise_connection_error(host, port=port, orig_error=e)
        except (OSError, IOError), e:
            # If the machine is fast enough, ssh can actually exit
            # before we try and send it the sftp request, which
            # raises a Broken Pipe
            if e.errno not in (errno.EPIPE,):
                raise
            self._raise_connection_error(host, port=port, orig_error=e)

    def connect_ssh(self, username, password, host, port, command):
        try:
            argv = self._get_vendor_specific_argv(username, host, port,
                                                  command=command)
            return self._connect(argv)
        except (EOFError), e:
            self._raise_connection_error(host, port=port, orig_error=e)
        except (OSError, IOError), e:
            # If the machine is fast enough, ssh can actually exit
            # before we try and send it the sftp request, which
            # raises a Broken Pipe
            if e.errno not in (errno.EPIPE,):
                raise
            self._raise_connection_error(host, port=port, orig_error=e)

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        """Returns the argument list to run the subprocess with.
        
        Exactly one of 'subsystem' and 'command' must be specified.
        """
        raise NotImplementedError(self._get_vendor_specific_argv)


class OpenSSHSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from OpenSSH."""

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        args = ['ssh',
                '-oForwardX11=no', '-oForwardAgent=no',
                '-oClearAllForwardings=yes', '-oProtocol=2',
                '-oNoHostAuthenticationForLocalhost=yes']
        if port is not None:
            args.extend(['-p', str(port)])
        if username is not None:
            args.extend(['-l', username])
        if subsystem is not None:
            args.extend(['-s', host, subsystem])
        else:
            args.extend([host] + command)
        return args

register_ssh_vendor('openssh', OpenSSHSubprocessVendor())


class SSHCorpSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'ssh' executable from SSH Corporation."""

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        args = ['ssh', '-x']
        if port is not None:
            args.extend(['-p', str(port)])
        if username is not None:
            args.extend(['-l', username])
        if subsystem is not None:
            args.extend(['-s', subsystem, host])
        else:
            args.extend([host] + command)
        return args

register_ssh_vendor('ssh', SSHCorpSubprocessVendor())


class PLinkSubprocessVendor(SubprocessVendor):
    """SSH vendor that uses the 'plink' executable from Putty."""

    def _get_vendor_specific_argv(self, username, host, port, subsystem=None,
                                  command=None):
        args = ['plink', '-x', '-a', '-ssh', '-2', '-batch']
        if port is not None:
            args.extend(['-P', str(port)])
        if username is not None:
            args.extend(['-l', username])
        if subsystem is not None:
            args.extend(['-s', host, subsystem])
        else:
            args.extend([host] + command)
        return args

register_ssh_vendor('plink', PLinkSubprocessVendor())


def _paramiko_auth(username, password, host, port, paramiko_transport):
    # paramiko requires a username, but it might be none if nothing was
    # supplied.  If so, use the local username.
    if username is None:
        username = getpass.getuser()

    if _use_ssh_agent:
        agent = paramiko.Agent()
        for key in agent.get_keys():
            trace.mutter('Trying SSH agent key %s'
                         % paramiko.util.hexify(key.get_fingerprint()))
            try:
                paramiko_transport.auth_publickey(username, key)
                return
            except paramiko.SSHException, e:
                pass

    # okay, try finding id_rsa or id_dss?  (posix only)
    if _try_pkey_auth(paramiko_transport, paramiko.RSAKey, username, 'id_rsa'):
        return
    if _try_pkey_auth(paramiko_transport, paramiko.DSSKey, username, 'id_dsa'):
        return

    if password:
        try:
            paramiko_transport.auth_password(username, password)
            return
        except paramiko.SSHException, e:
            pass

    # give up and ask for a password
    auth = config.AuthenticationConfig()
    password = auth.get_password('ssh', host, username, port=port)
    try:
        paramiko_transport.auth_password(username, password)
    except paramiko.SSHException, e:
        raise errors.ConnectionError(
            'Unable to authenticate to SSH host as %s@%s' % (username, host), e)


def _try_pkey_auth(paramiko_transport, pkey_class, username, filename):
    filename = os.path.expanduser('~/.ssh/' + filename)
    try:
        key = pkey_class.from_private_key_file(filename)
        paramiko_transport.auth_publickey(username, key)
        return True
    except paramiko.PasswordRequiredException:
        password = ui.ui_factory.get_password(
            prompt='SSH %(filename)s password', filename=filename)
        try:
            key = pkey_class.from_private_key_file(filename, password)
            paramiko_transport.auth_publickey(username, key)
            return True
        except paramiko.SSHException:
            trace.mutter('SSH authentication via %s key failed.'
                         % (os.path.basename(filename),))
    except paramiko.SSHException:
        trace.mutter('SSH authentication via %s key failed.'
                     % (os.path.basename(filename),))
    except IOError:
        pass
    return False


def load_host_keys():
    """
    Load system host keys (probably doesn't work on windows) and any
    "discovered" keys from previous sessions.
    """
    global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
    try:
        SYSTEM_HOSTKEYS = paramiko.util.load_host_keys(
            os.path.expanduser('~/.ssh/known_hosts'))
    except IOError, e:
        trace.mutter('failed to load system host keys: ' + str(e))
    bzr_hostkey_path = osutils.pathjoin(config.config_dir(), 'ssh_host_keys')
    try:
        BZR_HOSTKEYS = paramiko.util.load_host_keys(bzr_hostkey_path)
    except IOError, e:
        trace.mutter('failed to load bzr host keys: ' + str(e))
        save_host_keys()


def save_host_keys():
    """
    Save "discovered" host keys in $(config)/ssh_host_keys/.
    """
    global SYSTEM_HOSTKEYS, BZR_HOSTKEYS
    bzr_hostkey_path = osutils.pathjoin(config.config_dir(), 'ssh_host_keys')
    config.ensure_config_dir_exists()

    try:
        f = open(bzr_hostkey_path, 'w')
        f.write('# SSH host keys collected by bzr\n')
        for hostname, keys in BZR_HOSTKEYS.iteritems():
            for keytype, key in keys.iteritems():
                f.write('%s %s %s\n' % (hostname, keytype, key.get_base64()))
        f.close()
    except IOError, e:
        trace.mutter('failed to save bzr host keys: ' + str(e))


def os_specific_subprocess_params():
    """Get O/S specific subprocess parameters."""
    if sys.platform == 'win32':
        # setting the process group and closing fds is not supported on 
        # win32
        return {}
    else:
        # We close fds other than the pipes as the child process does not need 
        # them to be open.
        #
        # We also set the child process to ignore SIGINT.  Normally the signal
        # would be sent to every process in the foreground process group, but
        # this causes it to be seen only by bzr and not by ssh.  Python will
        # generate a KeyboardInterrupt in bzr, and we will then have a chance
        # to release locks or do other cleanup over ssh before the connection
        # goes away.  
        # <https://launchpad.net/products/bzr/+bug/5987>
        #
        # Running it in a separate process group is not good because then it
        # can't get non-echoed input of a password or passphrase.
        # <https://launchpad.net/products/bzr/+bug/40508>
        return {'preexec_fn': _ignore_sigint,
                'close_fds': True,
                }


class SSHSubprocess(object):
    """A socket-like object that talks to an ssh subprocess via pipes."""

    def __init__(self, proc):
        self.proc = proc

    def send(self, data):
        return os.write(self.proc.stdin.fileno(), data)

    def recv(self, count):
        return os.read(self.proc.stdout.fileno(), count)

    def close(self):
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.wait()

    def get_filelike_channels(self):
        return (self.proc.stdout, self.proc.stdin)

