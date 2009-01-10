# Copyright (C) 2004, 2005 Canonical Ltd
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

from cStringIO import StringIO
import errno
import sys

from bzrlib import (
    commands,
    config,
    errors,
    tests,
    )
from bzrlib.commands import display_command
from bzrlib.tests import TestSkipped


class TestCommands(tests.TestCase):

    def test_display_command(self):
        """EPIPE message is selectively suppressed"""
        def pipe_thrower():
            raise IOError(errno.EPIPE, "Bogus pipe error")
        self.assertRaises(IOError, pipe_thrower)
        @display_command
        def non_thrower():
            pipe_thrower()
        non_thrower()
        @display_command
        def other_thrower():
            raise IOError(errno.ESPIPE, "Bogus pipe error")
        self.assertRaises(IOError, other_thrower)

    def test_unicode_command(self):
        # This error is thrown when we can't find the command in the
        # list of available commands
        self.assertRaises(errors.BzrCommandError,
                          commands.run_bzr, [u'cmd\xb5'])

    def test_unicode_option(self):
        # This error is actually thrown by optparse, when it
        # can't find the given option
        import optparse
        if optparse.__version__ == "1.5.3":
            raise TestSkipped("optparse 1.5.3 can't handle unicode options")
        self.assertRaises(errors.BzrCommandError,
                          commands.run_bzr, ['log', u'--option\xb5'])


class TestGetAlias(tests.TestCase):

    def _get_config(self, config_text):
        my_config = config.GlobalConfig()
        config_file = StringIO(config_text.encode('utf-8'))
        my_config._parser = my_config._get_parser(file=config_file)
        return my_config

    def test_simple(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1'],
            commands.get_alias("diff", config=my_config))

    def test_single_quotes(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1 --diff-options "
            "'--strip-trailing-cr -wp'\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1', u'--diff-options',
                          u'--strip-trailing-cr -wp'],
                          commands.get_alias("diff", config=my_config))

    def test_double_quotes(self):
        my_config = self._get_config("[ALIASES]\n"
            "diff=diff -r -2..-1 --diff-options "
            "\"--strip-trailing-cr -wp\"\n")
        self.assertEqual([u'diff', u'-r', u'-2..-1', u'--diff-options',
                          u'--strip-trailing-cr -wp'],
                          commands.get_alias("diff", config=my_config))

    def test_unicode(self):
        my_config = self._get_config("[ALIASES]\n"
            u"iam=whoami 'Erik B\u00e5gfors <erik@bagfors.nu>'\n")
        self.assertEqual([u'whoami', u'Erik B\u00e5gfors <erik@bagfors.nu>'],
                          commands.get_alias("iam", config=my_config))


class TestSeeAlso(tests.TestCase):
    """Tests for the see also functional of Command."""

    def test_default_subclass_no_see_also(self):
        class ACommand(commands.Command):
            """A sample command."""
        command = ACommand()
        self.assertEqual([], command.get_see_also())

    def test__see_also(self):
        """When _see_also is defined, it sets the result of get_see_also()."""
        class ACommand(commands.Command):
            _see_also = ['bar', 'foo']
        command = ACommand()
        self.assertEqual(['bar', 'foo'], command.get_see_also())

    def test_deduplication(self):
        """Duplicates in _see_also are stripped out."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'foo']
        command = ACommand()
        self.assertEqual(['foo'], command.get_see_also())

    def test_sorted(self):
        """_see_also is sorted by get_see_also."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'bar']
        command = ACommand()
        self.assertEqual(['bar', 'foo'], command.get_see_also())

    def test_additional_terms(self):
        """Additional terms can be supplied and are deduped and sorted."""
        class ACommand(commands.Command):
            _see_also = ['foo', 'bar']
        command = ACommand()
        self.assertEqual(['bar', 'foo', 'gam'],
            command.get_see_also(['gam', 'bar', 'gam']))


class TestRegisterLazy(tests.TestCase):

    def setUp(self):
        import bzrlib.tests.fake_command
        del sys.modules['bzrlib.tests.fake_command']
        global lazy_command_imported
        lazy_command_imported = False

    @staticmethod
    def remove_fake():
        commands.plugin_cmds.remove('fake')

    def assertIsFakeCommand(self, cmd_obj):
        from bzrlib.tests.fake_command import cmd_fake
        self.assertIsInstance(cmd_obj, cmd_fake)

    def test_register_lazy(self):
        """Ensure lazy registration works"""
        commands.plugin_cmds.register_lazy('cmd_fake', [],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        self.assertFalse(lazy_command_imported)
        fake_instance = commands.get_cmd_object('fake')
        self.assertTrue(lazy_command_imported)
        self.assertIsFakeCommand(fake_instance)

    def test_get_unrelated_does_not_import(self):
        commands.plugin_cmds.register_lazy('cmd_fake', [],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        commands.get_cmd_object('status')
        self.assertFalse(lazy_command_imported)

    def test_aliases(self):
        commands.plugin_cmds.register_lazy('cmd_fake', ['fake_alias'],
                                           'bzrlib.tests.fake_command')
        self.addCleanup(self.remove_fake)
        fake_instance = commands.get_cmd_object('fake_alias')
        self.assertIsFakeCommand(fake_instance)
