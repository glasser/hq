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



"""Text UI, write output to the console.
"""

import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import getpass

from bzrlib import (
    progress,
    osutils,
    )
""")

from bzrlib.ui import CLIUIFactory


class TextUIFactory(CLIUIFactory):
    """A UI factory for Text user interefaces."""

    def __init__(self,
                 bar_type=None,
                 stdout=None,
                 stderr=None):
        """Create a TextUIFactory.

        :param bar_type: The type of progress bar to create. It defaults to 
                         letting the bzrlib.progress.ProgressBar factory auto
                         select.
        """
        super(TextUIFactory, self).__init__()
        self._bar_type = bar_type
        if stdout is None:
            self.stdout = sys.stdout
        else:
            self.stdout = stdout
        if stderr is None:
            self.stderr = sys.stderr
        else:
            self.stderr = stderr

    def prompt(self, prompt):
        """Emit prompt on the CLI."""
        self.stdout.write(prompt)
        
    def nested_progress_bar(self):
        """Return a nested progress bar.
        
        The actual bar type returned depends on the progress module which
        may return a tty or dots bar depending on the terminal.
        """
        if self._progress_bar_stack is None:
            self._progress_bar_stack = progress.ProgressBarStack(
                klass=self._bar_type)
        return self._progress_bar_stack.get_nested()

    def clear_term(self):
        """Prepare the terminal for output.

        This will, clear any progress bars, and leave the cursor at the
        leftmost position."""
        if self._progress_bar_stack is None:
            return
        overall_pb = self._progress_bar_stack.bottom()
        if overall_pb is not None:
            overall_pb.clear()
