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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""

import sys

from bzrlib.tests import (
                          adapt_modules,
                          TestCaseWithTransport,
                          iter_suite_tests,
                          )
from bzrlib.tests.EncodingAdapter import EncodingTestAdapter
from bzrlib.symbol_versioning import (
    deprecated_method,
    )
import bzrlib.ui as ui


def load_tests(basic_tests, module, loader):
    suite = loader.suiteClass()
    # add the tests for this module
    suite.addTests(basic_tests)

    testmod_names = [
                     'bzrlib.tests.blackbox.test_add',
                     'bzrlib.tests.blackbox.test_added',
                     'bzrlib.tests.blackbox.test_alias',
                     'bzrlib.tests.blackbox.test_aliases',
                     'bzrlib.tests.blackbox.test_ancestry',
                     'bzrlib.tests.blackbox.test_annotate',
                     'bzrlib.tests.blackbox.test_branch',
                     'bzrlib.tests.blackbox.test_break_lock',
                     'bzrlib.tests.blackbox.test_breakin',
                     'bzrlib.tests.blackbox.test_bound_branches',
                     'bzrlib.tests.blackbox.test_bundle_info',
                     'bzrlib.tests.blackbox.test_cat',
                     'bzrlib.tests.blackbox.test_cat_revision',
                     'bzrlib.tests.blackbox.test_check',
                     'bzrlib.tests.blackbox.test_checkout',
                     'bzrlib.tests.blackbox.test_command_encoding',
                     'bzrlib.tests.blackbox.test_commit',
                     'bzrlib.tests.blackbox.test_conflicts',
                     'bzrlib.tests.blackbox.test_debug',
                     'bzrlib.tests.blackbox.test_diff',
                     'bzrlib.tests.blackbox.test_dump_btree',
                     'bzrlib.tests.blackbox.test_exceptions',
                     'bzrlib.tests.blackbox.test_export',
                     'bzrlib.tests.blackbox.test_find_merge_base',
                     'bzrlib.tests.blackbox.test_help',
                     'bzrlib.tests.blackbox.test_hooks',
                     'bzrlib.tests.blackbox.test_ignore',
                     'bzrlib.tests.blackbox.test_ignored',
                     'bzrlib.tests.blackbox.test_info',
                     'bzrlib.tests.blackbox.test_init',
                     'bzrlib.tests.blackbox.test_inventory',
                     'bzrlib.tests.blackbox.test_join',
                     'bzrlib.tests.blackbox.test_locale',
                     'bzrlib.tests.blackbox.test_log',
                     'bzrlib.tests.blackbox.test_logformats',
                     'bzrlib.tests.blackbox.test_ls',
                     'bzrlib.tests.blackbox.test_lsprof',
                     'bzrlib.tests.blackbox.test_merge',
                     'bzrlib.tests.blackbox.test_merge_directive',
                     'bzrlib.tests.blackbox.test_missing',
                     'bzrlib.tests.blackbox.test_modified',
                     'bzrlib.tests.blackbox.test_mv',
                     'bzrlib.tests.blackbox.test_nick',
                     'bzrlib.tests.blackbox.test_outside_wt',
                     'bzrlib.tests.blackbox.test_pack',
                     'bzrlib.tests.blackbox.test_pull',
                     'bzrlib.tests.blackbox.test_push',
                     'bzrlib.tests.blackbox.test_reconcile',
                     'bzrlib.tests.blackbox.test_reconfigure',
                     'bzrlib.tests.blackbox.test_remerge',
                     'bzrlib.tests.blackbox.test_remove',
                     'bzrlib.tests.blackbox.test_re_sign',
                     'bzrlib.tests.blackbox.test_remove_tree',
                     'bzrlib.tests.blackbox.test_revert',
                     'bzrlib.tests.blackbox.test_revno',
                     'bzrlib.tests.blackbox.test_revision_history',
                     'bzrlib.tests.blackbox.test_revision_info',
                     'bzrlib.tests.blackbox.test_selftest',
                     'bzrlib.tests.blackbox.test_send',
                     'bzrlib.tests.blackbox.test_serve',
                     'bzrlib.tests.blackbox.test_shared_repository',
                     'bzrlib.tests.blackbox.test_sign_my_commits',
                     'bzrlib.tests.blackbox.test_split',
                     'bzrlib.tests.blackbox.test_status',
                     'bzrlib.tests.blackbox.test_switch',
                     'bzrlib.tests.blackbox.test_tags',
                     'bzrlib.tests.blackbox.test_testament',
                     'bzrlib.tests.blackbox.test_too_much',
                     'bzrlib.tests.blackbox.test_uncommit',
                     'bzrlib.tests.blackbox.test_unknowns',
                     'bzrlib.tests.blackbox.test_update',
                     'bzrlib.tests.blackbox.test_upgrade',
                     'bzrlib.tests.blackbox.test_version',
                     'bzrlib.tests.blackbox.test_version_info',
                     'bzrlib.tests.blackbox.test_versioning',
                     'bzrlib.tests.blackbox.test_whoami',
                     ]
    # add the tests for the sub modules
    suite.addTests(loader.loadTestsFromModuleNames(testmod_names))

    test_encodings = [
        'bzrlib.tests.blackbox.test_non_ascii',
    ]

    adapter = EncodingTestAdapter()
    adapt_modules(test_encodings, adapter, loader, suite)

    return suite


class ExternalBase(TestCaseWithTransport):

    def check_output(self, output, *args):
        """Verify that the expected output matches what bzr says.

        The output is supplied first, so that you can supply a variable
        number of arguments to bzr.
        """
        self.assertEquals(self.run_bzr(*args)[0], output)
