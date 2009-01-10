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

"""Test for setup.py build process"""

import os
import sys
import subprocess
import shutil
from tempfile import TemporaryFile

import bzrlib
from bzrlib.tests import TestCase, TestSkipped
import bzrlib.osutils as osutils

# XXX: This clobbers the build directory in the real source tree; it'd be nice
# to avoid that.
#
# TODO: Run bzr from the installed copy to see if it works.  Really we need to
# run something that exercises every module, just starting it may not detect
# some missing modules.
#
# TODO: Check that the version numbers are in sync.  (Or avoid this...)

class TestSetup(TestCase):

    def test_build_and_install(self):
        """ test cmd `python setup.py build`

        This tests that the build process and man generator run correctly.
        It also can catch new subdirectories that weren't added to setup.py.
        """
        if not os.path.isfile('setup.py'):
            raise TestSkipped('There is no setup.py file in current directory')
        try:
            import distutils.sysconfig
            makefile_path = distutils.sysconfig.get_makefile_filename()
            if not os.path.exists(makefile_path):
                raise TestSkipped('You must have the python Makefile installed to run this test.'
                                  ' Usually this can be found by installing "python-dev"')
        except ImportError:
            raise TestSkipped('You must have distutils installed to run this test.'
                              ' Usually this can be found by installing "python-dev"')
        self.log('test_build running in %s' % os.getcwd())
        install_dir = osutils.mkdtemp()
        # setup.py must be run from the root source directory, but the tests
        # are not necessarily invoked from there
        self.source_dir = os.path.dirname(os.path.dirname(bzrlib.__file__))
        try:
            self.run_setup(['clean'])
            # build is implied by install
            ## self.run_setup(['build'])
            self.run_setup(['install', '--prefix', install_dir])
            self.run_setup(['clean'])
        finally:
            osutils.rmtree(install_dir)

    def run_setup(self, args):
        args = [sys.executable, './setup.py', ] + args
        self.log('source base directory: %s', self.source_dir)
        self.log('args: %r', args)
        p = subprocess.Popen(args,
                             cwd=self.source_dir,
                             stdout=self._log_file,
                             stderr=self._log_file,
                             )
        s = p.communicate()
        self.assertEqual(0, p.returncode,
                         'invocation of %r failed' % args)
