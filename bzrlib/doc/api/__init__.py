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

"""API Documentation for bzrlib.

This documentation is made up of doctest testable examples.

Look for bzrlib/doc/api/*.txt to read it.

This documentation documents the current best practice in using the library.
For details on specific apis, see pydoc on the api, or read the source.
"""

import doctest
import os

from bzrlib import tests

def load_tests(basic_tests, module, loader):
    """This module creates its own test suite with DocFileSuite."""

    dir_ = os.path.dirname(__file__)
    if os.path.isdir(dir_):
        candidates = os.listdir(dir_)
    else:
        candidates = []
    scripts = [candidate for candidate in candidates
               if candidate.endswith('.txt')]
    # since this module doesn't define tests, we ignore basic_tests
    suite = doctest.DocFileSuite(*scripts)
    # DocFileCase reduces the test id to the base name of the tested file, we
    # want the module to appears there.
    for t in tests.iter_suite_tests(suite):
        def make_new_test_id():
            new_id = '%s.DocFileTest(%s)' % ( __name__, t)
            return lambda: new_id
        t.id = make_new_test_id()
    return suite
