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

"""UI abstraction.

This tells the library how to display things to the user.  Through this
layer different applications can choose the style of UI.

At the moment this layer is almost trivial: the application can just
choose the style of progress bar.

Set the ui_factory member to define the behaviour.  The default
displays no output.
"""

import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import getpass

from bzrlib import (
    errors,
    osutils,
    progress,
    trace,
    )
""")


class UIFactory(object):
    """UI abstraction.

    This tells the library how to display things to the user.  Through this
    layer different applications can choose the style of UI.
    """

    def __init__(self):
        super(UIFactory, self).__init__()
        self._progress_bar_stack = None

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.

        :return: The password string, return None if the user canceled the
                 request. Note that we do not touch the encoding, users may
                 have whatever they see fit and the password should be
                 transported as is.
        """
        raise NotImplementedError(self.get_password)

    def nested_progress_bar(self):
        """Return a nested progress bar.

        When the bar has been finished with, it should be released by calling
        bar.finished().
        """
        raise NotImplementedError(self.nested_progress_bar)

    def clear_term(self):
        """Prepare the terminal for output.

        This will, for example, clear text progress bars, and leave the
        cursor at the leftmost position."""
        raise NotImplementedError(self.clear_term)

    def get_boolean(self, prompt):
        """Get a boolean question answered from the user. 

        :param prompt: a message to prompt the user with. Should be a single
        line without terminating \n.
        :return: True or False for y/yes or n/no.
        """
        raise NotImplementedError(self.get_boolean)

    def recommend_upgrade(self,
        current_format_name,
        basedir):
        # this should perhaps be in the TextUIFactory and the default can do
        # nothing
        trace.warning("%s is deprecated "
            "and a better format is available.\n"
            "It is recommended that you upgrade by "
            "running the command\n"
            "  bzr upgrade %s",
            current_format_name,
            basedir)


class CLIUIFactory(UIFactory):
    """Common behaviour for command line UI factories."""

    def __init__(self):
        super(CLIUIFactory, self).__init__()
        self.stdin = sys.stdin

    def get_boolean(self, prompt):
        self.clear_term()
        # FIXME: make a regexp and handle case variations as well.
        while True:
            self.prompt(prompt + "? [y/n]: ")
            line = self.stdin.readline()
            if line in ('y\n', 'yes\n'):
                return True
            if line in ('n\n', 'no\n'):
                return False

    def get_non_echoed_password(self, prompt):
        if not sys.stdin.isatty():
            raise errors.NotATerminal()
        encoding = osutils.get_terminal_encoding()
        return getpass.getpass(prompt.encode(encoding, 'replace'))

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user 
                 canceled the request.
        """
        prompt += ': '
        prompt = (prompt % kwargs)
        # There's currently no way to say 'i decline to enter a password'
        # as opposed to 'my password is empty' -- does it matter?
        return self.get_non_echoed_password(prompt)

    def prompt(self, prompt):
        """Emit prompt on the CLI."""


class SilentUIFactory(CLIUIFactory):
    """A UI Factory which never prints anything.

    This is the default UI, if another one is never registered.
    """

    def get_password(self, prompt='', **kwargs):
        return None

    def nested_progress_bar(self):
        if self._progress_bar_stack is None:
            self._progress_bar_stack = progress.ProgressBarStack(
                klass=progress.DummyProgress)
        return self._progress_bar_stack.get_nested()

    def clear_term(self):
        pass

    def recommend_upgrade(self, *args):
        pass


def clear_decorator(func, *args, **kwargs):
    """Decorator that clears the term"""
    ui_factory.clear_term()
    func(*args, **kwargs)


ui_factory = SilentUIFactory()
"""IMPORTANT: never import this symbol directly. ONLY ever access it as 
ui.ui_factory."""
