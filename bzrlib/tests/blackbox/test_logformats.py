# Copyright (C) 2005, 2006 Canonical Ltd
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
"""Black-box tests for default log_formats/log_formatters
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from bzrlib.config import (ensure_config_dir_exists, config_filename)


class TestLogFormats(TestCaseInTempDir):

    def bzr(self, *args, **kwargs):
        return self.run_bzr(*args, **kwargs)[0]

    def test_log_default_format(self):
        self.setup_config()

        self.bzr('init')
        open('a', 'wb').write('foo\n')
        self.bzr('add a')

        self.bzr('commit -m 1')
        open('a', 'wb').write('baz\n')

        self.bzr('commit -m 2')

        # only the lines formatter is this short
        self.assertEquals(3, len(self.bzr('log').split('\n')))

    def test_log_format_arg(self):
        self.bzr('init')
        open('a', 'wb').write('foo\n')
        self.bzr('add a')

        self.bzr('commit -m 1')
        open('a', 'wb').write('baz\n')

        self.bzr('commit -m 2')

        # only the lines formatter is this short
        self.assertEquals(7, len(self.bzr('log --log-format short').split('\n')))

    def test_missing_default_format(self):
        self.setup_config()

        os.mkdir('a')
        os.chdir('a')
        self.bzr('init')

        open('a', 'wb').write('foo\n')
        self.bzr('add a')
        self.bzr('commit -m 1')

        os.chdir('..')
        self.bzr('branch a b')
        os.chdir('a')

        open('a', 'wb').write('bar\n')
        self.bzr('commit -m 2')

        open('a', 'wb').write('baz\n')
        self.bzr('commit -m 3')

        os.chdir('../b')

        self.assertEquals(5, len(self.bzr('missing', retcode=1).split('\n')))

        os.chdir('..')

    def test_missing_format_arg(self):
        self.setup_config()

        os.mkdir('a')
        os.chdir('a')
        self.bzr('init')

        open('a', 'wb').write('foo\n')
        self.bzr('add a')
        self.bzr('commit -m 1')

        os.chdir('..')
        self.bzr('branch a b')
        os.chdir('a')

        open('a', 'wb').write('bar\n')
        self.bzr('commit -m 2')

        open('a', 'wb').write('baz\n')
        self.bzr('commit -m 3')

        os.chdir('../b')

        self.assertEquals(9, len(self.bzr('missing --log-format short',
                                          retcode=1).split('\n')))

        os.chdir('..')


    def setup_config(self):
        if os.path.isfile(config_filename()):
                # Something is wrong in environment, 
                # we risk overwriting users config 
                self.assert_(config_filename() + "exists, abort")
            
        ensure_config_dir_exists()
        CONFIG=("[DEFAULT]\n"
                "email=Joe Foo <joe@foo.com>\n"
                "log_format=line\n")

        open(config_filename(),'wb').write(CONFIG)
