# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

from bzrlib.tests import TestCase
from bzrlib.errors import SSHVendorNotFound, UnknownSSH
from bzrlib.transport.ssh import (
    OpenSSHSubprocessVendor,
    PLinkSubprocessVendor,
    SSHCorpSubprocessVendor,
    SSHVendorManager,
    )


class TestSSHVendorManager(SSHVendorManager):

    _ssh_version_string = ""

    def set_ssh_version_string(self, version):
        self._ssh_version_string = version

    def _get_ssh_version_string(self, args):
        return self._ssh_version_string


class SSHVendorManagerTests(TestCase):

    def test_register_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        vendor = object()
        manager.register_vendor("vendor", vendor)
        self.assertIs(manager.get_vendor({"BZR_SSH": "vendor"}), vendor)

    def test_default_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        vendor = object()
        manager.register_default_vendor(vendor)
        self.assertIs(manager.get_vendor({}), vendor)

    def test_get_vendor_by_environment(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        self.assertRaises(UnknownSSH,
            manager.get_vendor, {"BZR_SSH": "vendor"})
        vendor = object()
        manager.register_vendor("vendor", vendor)
        self.assertIs(manager.get_vendor({"BZR_SSH": "vendor"}), vendor)

    def test_get_vendor_by_inspection_openssh(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("OpenSSH")
        self.assertIsInstance(manager.get_vendor({}), OpenSSHSubprocessVendor)

    def test_get_vendor_by_inspection_sshcorp(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("SSH Secure Shell")
        self.assertIsInstance(manager.get_vendor({}), SSHCorpSubprocessVendor)

    def test_get_vendor_by_inspection_plink(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        manager.set_ssh_version_string("plink")
        self.assertIsInstance(manager.get_vendor({}), PLinkSubprocessVendor)

    def test_cached_vendor(self):
        manager = TestSSHVendorManager()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        vendor = object()
        manager.register_vendor("vendor", vendor)
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})
        # Once the vendor is found the result is cached (mainly because of the
        # 'get_vendor' sometimes can be an expensive operation) and later
        # invocations of the 'get_vendor' just returns the cached value.
        self.assertIs(manager.get_vendor({"BZR_SSH": "vendor"}), vendor)
        self.assertIs(manager.get_vendor({}), vendor)
        # The cache can be cleared by the 'clear_cache' method
        manager.clear_cache()
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})

    def test_get_vendor_search_order(self):
        # The 'get_vendor' method search for SSH vendors as following:
        #
        #   1. Check previously cached value
        #   2. Check BZR_SSH environment variable
        #   3. Check the system for known SSH vendors
        #   4. Fall back to the default vendor if registered
        #
        # Let's now check the each check method in the reverse order
        # clearing the cache between each invocation:

        manager = TestSSHVendorManager()
        # At first no vendors are found
        self.assertRaises(SSHVendorNotFound, manager.get_vendor, {})

        # If the default vendor is registered it will be returned
        default_vendor = object()
        manager.register_default_vendor(default_vendor)
        self.assertIs(manager.get_vendor({}), default_vendor)

        # If the known vendor is found in the system it will be returned
        manager.clear_cache()
        manager.set_ssh_version_string("OpenSSH")
        self.assertIsInstance(manager.get_vendor({}), OpenSSHSubprocessVendor)

        # If the BZR_SSH environment variable is found it will be treated as
        # the vendor name
        manager.clear_cache()
        vendor = object()
        manager.register_vendor("vendor", vendor)
        self.assertIs(manager.get_vendor({"BZR_SSH": "vendor"}), vendor)

        # Last cached value always checked first
        self.assertIs(manager.get_vendor({}), vendor)


class SubprocessVendorsTests(TestCase):

    def test_openssh_command_arguments(self):
        vendor = OpenSSHSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["ssh", "-oForwardX11=no", "-oForwardAgent=no",
                "-oClearAllForwardings=yes", "-oProtocol=2",
                "-oNoHostAuthenticationForLocalhost=yes",
                "-p", "100",
                "-l", "user",
                "host", "bzr"]
            )

    def test_openssh_subsystem_arguments(self):
        vendor = OpenSSHSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, subsystem="sftp"),
            ["ssh", "-oForwardX11=no", "-oForwardAgent=no",
                "-oClearAllForwardings=yes", "-oProtocol=2",
                "-oNoHostAuthenticationForLocalhost=yes",
                "-p", "100",
                "-l", "user",
                "-s", "host", "sftp"]
            )

    def test_sshcorp_command_arguments(self):
        vendor = SSHCorpSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["ssh", "-x",
                "-p", "100",
                "-l", "user",
                "host", "bzr"]
            )

    def test_sshcorp_subsystem_arguments(self):
        vendor = SSHCorpSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, subsystem="sftp"),
            ["ssh", "-x",
                "-p", "100",
                "-l", "user",
                "-s", "sftp", "host"]
            )

    def test_plink_command_arguments(self):
        vendor = PLinkSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, command=["bzr"]),
            ["plink", "-x", "-a", "-ssh", "-2", "-batch",
                "-P", "100",
                "-l", "user",
                "host", "bzr"]
            )

    def test_plink_subsystem_arguments(self):
        vendor = PLinkSubprocessVendor()
        self.assertEqual(
            vendor._get_vendor_specific_argv(
                "user", "host", 100, subsystem="sftp"),
            ["plink", "-x", "-a", "-ssh", "-2", "-batch",
                "-P", "100",
                "-l", "user",
                "-s", "host", "sftp"]
            )
