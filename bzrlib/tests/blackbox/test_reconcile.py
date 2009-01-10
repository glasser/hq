# Copyright (C) 2006 Canonical Ltd
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

"""Black box tests for the reconcile command."""


import bzrlib
import bzrlib.bzrdir as bzrdir
from bzrlib.inventory import Inventory
import bzrlib.repository as repository
from bzrlib.tests import TestCaseWithTransport
from bzrlib.tests import TestUIFactory
from bzrlib.transport import get_transport
import bzrlib.ui as ui


class TrivialTest(TestCaseWithTransport):

    def setUp(self):
        super(TrivialTest, self).setUp()
        self.old_format = bzrdir.BzrDirFormat.get_default_format()
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)
        ui.ui_factory = TestUIFactory()

    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory

    def test_trivial_reconcile(self):
        t = bzrdir.BzrDir.create_standalone_workingtree('.')
        (out, err) = self.run_bzr('reconcile')
        if t.branch.repository._reconcile_backsup_inventory:
            does_backup_text = "Inventory ok.\n"
        else:
            does_backup_text = ""
        self.assertEqualDiff(out, "Reconciling branch %s\n"
                                  "revision_history ok.\n"
                                  "Reconciling repository %s\n"
                                  "%s"
                                  "Reconciliation complete.\n" %
                                  (t.branch.base,
                                   t.bzrdir.root_transport.base,
                                   does_backup_text))
        self.assertEqualDiff(err, "")

    def test_does_something_reconcile(self):
        t = bzrdir.BzrDir.create_standalone_workingtree('.')
        # an empty inventory with no revision will trigger reconciliation.
        repo = t.branch.repository
        inv = Inventory(revision_id='missing')
        inv.root.revision='missing'
        repo.lock_write()
        repo.start_write_group()
        repo.add_inventory('missing', inv, [])
        repo.commit_write_group()
        repo.unlock()
        (out, err) = self.run_bzr('reconcile')
        if repo._reconcile_backsup_inventory:
            does_backup_text = (
                "Backup Inventory created.\n"
                "Inventory regenerated.\n")
        else:
            does_backup_text = ""
        expected = ("Reconciling branch %s\n"
                    "revision_history ok.\n"
                    "Reconciling repository %s\n"
                    "%s"
                    "Reconciliation complete.\n" %
                    (t.branch.base,
                     t.bzrdir.root_transport.base,
                     does_backup_text))
        self.assertEqualDiff(expected, out)
        self.assertEqualDiff(err, "")
