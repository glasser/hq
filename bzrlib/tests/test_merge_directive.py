# Copyright (C) 2007 Canonical Ltd
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

import re

from bzrlib import (
    errors,
    gpg,
    merge_directive,
    tests,
    )


OUTPUT1 = """# Bazaar merge directive format 1
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
#\x20
booga"""

OUTPUT1_2 = """# Bazaar merge directive format 2 (Bazaar 0.90)
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# base_revision_id: null:
#\x20
# Begin bundle
booga"""

OUTPUT2 = """# Bazaar merge directive format 1
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# message: Hi mom!
#\x20
booga"""

OUTPUT2_2 = """# Bazaar merge directive format 2 (Bazaar 0.90)
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# message: Hi mom!
# base_revision_id: null:
#\x20
# Begin patch
booga"""

INPUT1 = """
I was thinking today about creating a merge directive.

So I did.

Here it is.

(I've pasted it in the body of this message)

Aaron

# Bazaar merge directive format 1\r
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# message: Hi mom!
#\x20
booga""".splitlines(True)


INPUT1_2 = """
I was thinking today about creating a merge directive.

So I did.

Here it is.

(I've pasted it in the body of this message)

Aaron

# Bazaar merge directive format 2 (Bazaar 0.90)\r
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# base_revision_id: null:
# message: Hi mom!
#\x20
# Begin patch
booga""".splitlines(True)


INPUT1_2_OLD = """
I was thinking today about creating a merge directive.

So I did.

Here it is.

(I've pasted it in the body of this message)

Aaron

# Bazaar merge directive format 2 (Bazaar 0.19)\r
# revision_id: example:
# target_branch: http://example.com
# testament_sha1: sha
# timestamp: 1970-01-01 00:09:33 +0002
# source_branch: http://example.org
# base_revision_id: null:
# message: Hi mom!
#\x20
# Begin patch
booga""".splitlines(True)


OLD_DIRECTIVE_2 = """# Bazaar merge directive format 2 (Bazaar 0.19)
# revision_id: abentley@panoramicfeedback.com-20070807234458-\
#   nzhkoyza56lan7z5
# target_branch: http://panoramicfeedback.com/opensource/bzr/repo\
#   /bzr.ab
# testament_sha1: d825a5cdb267a90ec2ba86b00895f3d8a9bed6bf
# timestamp: 2007-08-10 16:15:02 -0400
# source_branch: http://panoramicfeedback.com/opensource/bzr/repo\
#   /bzr.ab
# base_revision_id: abentley@panoramicfeedback.com-20070731163346-\
#   623xwcycwij91xen
#
""".splitlines(True)


class TestMergeDirective(object):

    def test_merge_source(self):
        time = 500000.0
        timezone = 5 * 3600
        self.assertRaises(errors.NoMergeSource, self.make_merge_directive,
            'example:', 'sha', time, timezone, 'http://example.com')
        self.assertRaises(errors.NoMergeSource, self.make_merge_directive,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='diff')
        self.make_merge_directive('example:', 'sha', time, timezone,
            'http://example.com', source_branch='http://example.org')
        md = self.make_merge_directive('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle')
        self.assertIs(None, md.source_branch)
        md2 = self.make_merge_directive('null:', 'sha', time, timezone,
            'http://example.com', patch='blah', patch_type='bundle',
            source_branch='bar')
        self.assertEqual('bar', md2.source_branch)

    def test_serialization(self):
        time = 453
        timezone = 120
        md = self.make_merge_directive('example:', 'sha', time, timezone,
            'http://example.com', patch='booga', patch_type='bundle')
        self.assertEqualDiff(self.OUTPUT1, ''.join(md.to_lines()))
        md = self.make_merge_directive('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff', message="Hi mom!")
        self.assertEqualDiff(self.OUTPUT2, ''.join(md.to_lines()))

    def test_deserialize_junk(self):
        time = 501
        self.assertRaises(errors.NotAMergeDirective,
                          merge_directive.MergeDirective.from_lines, 'lala')

    def test_deserialize_empty(self):
        self.assertRaises(errors.NotAMergeDirective,
                          merge_directive.MergeDirective.from_lines, [])

    def test_deserialize_leading_junk(self):
        md = merge_directive.MergeDirective.from_lines(self.INPUT1)
        self.assertEqual('example:', md.revision_id)
        self.assertEqual('sha', md.testament_sha1)
        self.assertEqual('http://example.com', md.target_branch)
        self.assertEqual('http://example.org', md.source_branch)
        self.assertEqual(453, md.time)
        self.assertEqual(120, md.timezone)
        self.assertEqual('booga', md.patch)
        self.assertEqual('diff', md.patch_type)
        self.assertEqual('Hi mom!', md.message)

    def test_roundtrip(self):
        time = 500000
        timezone = 7.5 * 3600
        md = self.make_merge_directive('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff')
        md2 = merge_directive.MergeDirective.from_lines(md.to_lines())
        self.assertEqual('example:', md2.revision_id)
        self.assertIsInstance(md2.revision_id, str)
        self.assertEqual('sha', md2.testament_sha1)
        self.assertEqual('http://example.com', md2.target_branch)
        self.assertEqual('http://example.org', md2.source_branch)
        self.assertEqual(time, md2.time)
        self.assertEqual(timezone, md2.timezone)
        self.assertEqual('diff', md2.patch_type)
        self.assertEqual('booga', md2.patch)
        self.assertEqual(None, md2.message)
        self.set_bundle(md, "# Bazaar revision bundle v0.9\n#\n")
        md.message = "Hi mom!"
        lines = md.to_lines()
        md3 = merge_directive.MergeDirective.from_lines(lines)
        self.assertEqual("# Bazaar revision bundle v0.9\n#\n", md3.bundle)
        self.assertEqual("bundle", md3.patch_type)
        self.assertContainsRe(md3.to_lines()[0],
            '^# Bazaar merge directive format ')
        self.assertEqual("Hi mom!", md3.message)
        md3.clear_payload()
        self.assertIs(None, md3.get_raw_bundle())
        md4 = merge_directive.MergeDirective.from_lines(md3.to_lines())
        self.assertIs(None, md4.patch_type)


class TestMergeDirective1(tests.TestCase, TestMergeDirective):
    """Test merge directive format 1"""

    INPUT1 = INPUT1

    OUTPUT1 = OUTPUT1

    OUTPUT2 = OUTPUT2

    def make_merge_directive(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, patch_type=None,
                 source_branch=None, message=None):
        return merge_directive.MergeDirective(revision_id, testament_sha1,
                 time, timezone, target_branch, patch, patch_type,
                 source_branch, message)

    @staticmethod
    def set_bundle(md, value):
        md.patch = value

    def test_require_patch(self):
        time = 500.0
        timezone = 120
        self.assertRaises(errors.PatchMissing, merge_directive.MergeDirective,
            'example:', 'sha', time, timezone, 'http://example.com',
            patch_type='bundle')
        md = merge_directive.MergeDirective('example:', 'sha1', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='', patch_type='diff')
        self.assertEqual(md.patch, '')


class TestMergeDirective2(tests.TestCase, TestMergeDirective):
    """Test merge directive format 2"""

    INPUT1 = INPUT1_2

    OUTPUT1 = OUTPUT1_2

    OUTPUT2 = OUTPUT2_2

    def make_merge_directive(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, patch_type=None,
                 source_branch=None, message=None, base_revision_id='null:'):
        if patch_type == 'bundle':
            bundle = patch
            patch = None
        else:
            bundle = None
        return merge_directive.MergeDirective2(revision_id, testament_sha1,
            time, timezone, target_branch, patch, source_branch, message,
            bundle, base_revision_id)

    @staticmethod
    def set_bundle(md, value):
        md.bundle = value


EMAIL1 = """From: "J. Random Hacker" <jrandom@example.com>
Subject: Commit of rev2a
To: pqm@example.com
User-Agent: Bazaar \(.*\)

# Bazaar merge directive format 1
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
"""


EMAIL1_2 = """From: "J. Random Hacker" <jrandom@example.com>
Subject: Commit of rev2a
To: pqm@example.com
User-Agent: Bazaar \(.*\)

# Bazaar merge directive format 2 \\(Bazaar 0.90\\)
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
"""


EMAIL2 = """From: "J. Random Hacker" <jrandom@example.com>
Subject: Commit of rev2a with special message
To: pqm@example.com
User-Agent: Bazaar \(.*\)

# Bazaar merge directive format 1
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
# message: Commit of rev2a with special message
"""

EMAIL2_2 = """From: "J. Random Hacker" <jrandom@example.com>
Subject: Commit of rev2a with special message
To: pqm@example.com
User-Agent: Bazaar \(.*\)

# Bazaar merge directive format 2 \\(Bazaar 0.90\\)
# revision_id: rev2a
# target_branch: (.|\n)*
# testament_sha1: .*
# timestamp: 1970-01-01 00:08:56 \\+0001
# source_branch: (.|\n)*
# message: Commit of rev2a with special message
"""

class TestMergeDirectiveBranch(object):

    def make_trees(self):
        tree_a = self.make_branch_and_tree('tree_a')
        tree_a.branch.get_config().set_user_option('email',
            'J. Random Hacker <jrandom@example.com>')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_b\n'),
                                  ('tree_a/file_2', 'content_x\rcontent_y\r')])
        tree_a.add(['file', 'file_2'])
        tree_a.commit('message', rev_id='rev1')
        tree_b = tree_a.bzrdir.sprout('tree_b').open_workingtree()
        branch_c = tree_a.bzrdir.sprout('branch_c').open_branch()
        tree_b.commit('message', rev_id='rev2b')
        self.build_tree_contents([('tree_a/file', 'content_a\ncontent_c \n'),
                                  ('tree_a/file_2', 'content_x\rcontent_z\r')])
        tree_a.commit('Commit of rev2a', rev_id='rev2a')
        return tree_a, tree_b, branch_c

    def test_empty_target(self):
        tree_a, tree_b, branch_c = self.make_trees()
        tree_d = self.make_branch_and_tree('tree_d')
        md2 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 120,
            tree_d.branch.base, patch_type='diff',
            public_branch=tree_a.branch.base)

    def test_disk_name(self):
        tree_a, tree_b, branch_c = self.make_trees()
        tree_a.branch.nick = 'fancy <name>'
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 120,
            tree_b.branch.base)
        self.assertEqual('fancy-name-2', md.get_disk_name(tree_a.branch))

    def test_disk_name_old_revno(self):
        tree_a, tree_b, branch_c = self.make_trees()
        tree_a.branch.nick = 'fancy-name'
        md = self.from_objects(tree_a.branch.repository, 'rev1', 500, 120,
            tree_b.branch.base)
        self.assertEqual('fancy-name-1', md.get_disk_name(tree_a.branch))

    def test_generate_patch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md2 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 120,
            tree_b.branch.base, patch_type='diff',
            public_branch=tree_a.branch.base)
        self.assertNotContainsRe(md2.patch, 'Bazaar revision bundle')
        self.assertContainsRe(md2.patch, '\\+content_c')
        self.assertNotContainsRe(md2.patch, '\\+\\+\\+ b/')
        self.assertContainsRe(md2.patch, '\\+\\+\\+ file')

    def test_public_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        self.assertRaises(errors.PublicBranchOutOfDate,
            self.from_objects, tree_a.branch.repository, 'rev2a', 500, 144,
            tree_b.branch.base, public_branch=branch_c.base, patch_type='diff')
        self.assertRaises(errors.PublicBranchOutOfDate,
            self.from_objects, tree_a.branch.repository, 'rev2a', 500, 144,
            tree_b.branch.base, public_branch=branch_c.base, patch_type=None)
        # public branch is not checked if patch format is bundle.
        md1 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 144,
            tree_b.branch.base, public_branch=branch_c.base)
        # public branch is provided with a bundle, despite possibly being out
        # of date, because it's not required if a bundle is present.
        self.assertEqual(md1.source_branch, branch_c.base)
        # Once we update the public branch, we can generate a diff.
        branch_c.pull(tree_a.branch)
        md3 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 144,
            tree_b.branch.base, patch_type=None, public_branch=branch_c.base)

    def test_use_public_submit_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        branch_c.pull(tree_a.branch)
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 144,
            tree_b.branch.base, patch_type=None, public_branch=branch_c.base)
        self.assertEqual(md.target_branch, tree_b.branch.base)
        tree_b.branch.set_public_branch('http://example.com')
        md2 = self.from_objects(
              tree_a.branch.repository, 'rev2a', 500, 144, tree_b.branch.base,
              patch_type=None, public_branch=branch_c.base)
        self.assertEqual(md2.target_branch, 'http://example.com')

    def test_message(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md3 = self.from_objects(tree_a.branch.repository, 'rev1', 500, 120,
            tree_b.branch.base, patch_type=None, public_branch=branch_c.base,
            message='Merge message')
        md3.to_lines()
        self.assertIs(None, md3.patch)
        self.assertEqual('Merge message', md3.message)

    def test_generate_bundle(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md1 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 120,
            tree_b.branch.base, public_branch=branch_c.base)

        self.assertContainsRe(md1.get_raw_bundle(), 'Bazaar revision bundle')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')
        self.assertContainsRe(md1.patch, '\\+content_c')
        self.assertNotContainsRe(md1.patch, '\\+content_a')

    def test_broken_bundle(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md1 = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 120,
            tree_b.branch.base, public_branch=branch_c.base)
        lines = md1.to_lines()
        lines = [l.replace('\n', '\r\n') for l in lines]
        md2 = merge_directive.MergeDirective.from_lines(lines)
        self.assertEqual('rev2a', md2.revision_id)

    def test_signing(self):
        time = 453
        timezone = 7200
        class FakeBranch(object):
            def get_config(self):
                return self
            def gpg_signing_command(self):
                return 'loopback'
        md = self.make_merge_directive('example:', 'sha', time, timezone,
            'http://example.com', source_branch="http://example.org",
            patch='booga', patch_type='diff')
        old_strategy = gpg.GPGStrategy
        gpg.GPGStrategy = gpg.LoopbackGPGStrategy
        try:
            signed = md.to_signed(FakeBranch())
        finally:
            gpg.GPGStrategy = old_strategy
        self.assertContainsRe(signed, '^-----BEGIN PSEUDO-SIGNED CONTENT')
        self.assertContainsRe(signed, 'example.org')
        self.assertContainsRe(signed, 'booga')

    def test_email(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 476, 60,
            tree_b.branch.base, patch_type=None,
            public_branch=tree_a.branch.base)
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), self.EMAIL1)
        md.message = 'Commit of rev2a with special message'
        message = md.to_email('pqm@example.com', tree_a.branch)
        self.assertContainsRe(message.as_string(), self.EMAIL2)

    def test_install_revisions_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type=None,
            public_branch=tree_a.branch.base)
        self.assertFalse(tree_b.branch.repository.has_revision('rev2a'))
        revision = md.install_revisions(tree_b.branch.repository)
        self.assertEqual('rev2a', revision)
        self.assertTrue(tree_b.branch.repository.has_revision('rev2a'))

    def test_get_merge_request(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type='bundle',
            public_branch=tree_a.branch.base)
        self.assertFalse(tree_b.branch.repository.has_revision('rev2a'))
        md.install_revisions(tree_b.branch.repository)
        base, revision, verified = md.get_merge_request(
            tree_b.branch.repository)
        if isinstance(md, merge_directive.MergeDirective):
            self.assertIs(None, base)
            self.assertEqual('inapplicable', verified)
        else:
            self.assertEqual('rev1', base)
            self.assertEqual('verified', verified)
        self.assertEqual('rev2a', revision)
        self.assertTrue(tree_b.branch.repository.has_revision('rev2a'))
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type=None,
            public_branch=tree_a.branch.base)
        base, revision, verified = md.get_merge_request(
            tree_b.branch.repository)
        if isinstance(md, merge_directive.MergeDirective):
            self.assertIs(None, base)
            self.assertEqual('inapplicable', verified)
        else:
            self.assertEqual('rev1', base)
            self.assertEqual('inapplicable', verified)
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type='diff',
            public_branch=tree_a.branch.base)
        base, revision, verified = md.get_merge_request(
            tree_b.branch.repository)
        if isinstance(md, merge_directive.MergeDirective):
            self.assertIs(None, base)
            self.assertEqual('inapplicable', verified)
        else:
            self.assertEqual('rev1', base)
            self.assertEqual('verified', verified)
        md.patch='asdf'
        base, revision, verified = md.get_merge_request(
            tree_b.branch.repository)
        if isinstance(md, merge_directive.MergeDirective):
            self.assertIs(None, base)
            self.assertEqual('inapplicable', verified)
        else:
            self.assertEqual('rev1', base)
            self.assertEqual('failed', verified)

    def test_install_revisions_bundle(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type='bundle',
            public_branch=tree_a.branch.base)
        self.assertFalse(tree_b.branch.repository.has_revision('rev2a'))
        revision = md.install_revisions(tree_b.branch.repository)
        self.assertEqual('rev2a', revision)
        self.assertTrue(tree_b.branch.repository.has_revision('rev2a'))

    def test_get_target_revision_nofetch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        tree_b.branch.fetch(tree_a.branch)
        md = self.from_objects( tree_a.branch.repository, 'rev2a', 500, 36,
            tree_b.branch.base, patch_type=None,
            public_branch=tree_a.branch.base)
        md.source_branch = '/dev/null'
        revision = md.install_revisions(tree_b.branch.repository)
        self.assertEqual('rev2a', revision)

    def test_use_submit_for_missing_dependency(self):
        tree_a, tree_b, branch_c = self.make_trees()
        branch_c.pull(tree_a.branch)
        self.build_tree_contents([('tree_a/file', 'content_q\ncontent_r\n')])
        tree_a.commit('rev3a', rev_id='rev3a')
        md = self.from_objects(tree_a.branch.repository, 'rev3a', 500, 36,
            branch_c.base, base_revision_id='rev2a')
        revision = md.install_revisions(tree_b.branch.repository)

    def test_handle_target_not_a_branch(self):
        tree_a, tree_b, branch_c = self.make_trees()
        branch_c.pull(tree_a.branch)
        self.build_tree_contents([('tree_a/file', 'content_q\ncontent_r\n')])
        tree_a.commit('rev3a', rev_id='rev3a')
        md = self.from_objects(tree_a.branch.repository, 'rev3a', 500, 36,
            branch_c.base, base_revision_id='rev2a')
        md.target_branch = self.get_url('not-a-branch')
        self.assertRaises(errors.TargetNotBranch, md.install_revisions,
                tree_b.branch.repository)


class TestMergeDirective1Branch(tests.TestCaseWithTransport,
    TestMergeDirectiveBranch):
    """Test merge directive format 1 with a branch"""

    EMAIL1 = EMAIL1

    EMAIL2 = EMAIL2

    def from_objects(self, repository, revision_id, time, timezone,
        target_branch, patch_type='bundle', local_target_branch=None,
        public_branch=None, message=None, base_revision_id=None):
        if base_revision_id is not None:
            raise tests.TestNotApplicable('This format does not support'
                                          ' explicit bases.')
        repository.lock_write()
        try:
            return merge_directive.MergeDirective.from_objects( repository,
                revision_id, time, timezone, target_branch, patch_type,
                local_target_branch, public_branch, message)
        finally:
            repository.unlock()

    def make_merge_directive(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, patch_type=None,
                 source_branch=None, message=None):
        return merge_directive.MergeDirective(revision_id, testament_sha1,
                 time, timezone, target_branch, patch, patch_type,
                 source_branch, message)


class TestMergeDirective2Branch(tests.TestCaseWithTransport,
    TestMergeDirectiveBranch):
    """Test merge directive format 2 with a branch"""

    EMAIL1 = EMAIL1_2

    EMAIL2 = EMAIL2_2

    def from_objects(self, repository, revision_id, time, timezone,
        target_branch, patch_type='bundle', local_target_branch=None,
        public_branch=None, message=None, base_revision_id=None):
        include_patch = (patch_type in ('bundle', 'diff'))
        include_bundle = (patch_type == 'bundle')
        self.assertTrue(patch_type in ('bundle', 'diff', None))
        return merge_directive.MergeDirective2.from_objects(
            repository, revision_id, time, timezone, target_branch,
            include_patch, include_bundle, local_target_branch, public_branch,
            message, base_revision_id)

    def make_merge_directive(self, revision_id, testament_sha1, time, timezone,
                 target_branch, patch=None, patch_type=None,
                 source_branch=None, message=None, base_revision_id='null:'):
        if patch_type == 'bundle':
            bundle = patch
            patch = None
        else:
            bundle = None
        return merge_directive.MergeDirective2(revision_id, testament_sha1,
            time, timezone, target_branch, patch, source_branch, message,
            bundle, base_revision_id)

    def test_base_revision(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 60,
            tree_b.branch.base, patch_type='bundle',
            public_branch=tree_a.branch.base, base_revision_id=None)
        self.assertEqual('rev1', md.base_revision_id)
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 60,
            tree_b.branch.base, patch_type='bundle',
            public_branch=tree_a.branch.base, base_revision_id='null:')
        self.assertEqual('null:', md.base_revision_id)
        lines = md.to_lines()
        md2 = merge_directive.MergeDirective.from_lines(lines)
        self.assertEqual(md2.base_revision_id, md.base_revision_id)

    def test_patch_verification(self):
        tree_a, tree_b, branch_c = self.make_trees()
        md = self.from_objects(tree_a.branch.repository, 'rev2a', 500, 60,
            tree_b.branch.base, patch_type='bundle',
            public_branch=tree_a.branch.base)
        lines = md.to_lines()
        md2 = merge_directive.MergeDirective.from_lines(lines)
        md2._verify_patch(tree_a.branch.repository)
        # Strip trailing whitespace
        md2.patch = md2.patch.replace(' \n', '\n')
        md2._verify_patch(tree_a.branch.repository)
        # Convert to Mac line-endings
        md2.patch = re.sub('(\r\n|\r|\n)', '\r', md2.patch)
        self.assertTrue(md2._verify_patch(tree_a.branch.repository))
        # Convert to DOS line-endings
        md2.patch = re.sub('(\r\n|\r|\n)', '\r\n', md2.patch)
        self.assertTrue(md2._verify_patch(tree_a.branch.repository))
        md2.patch = md2.patch.replace('content_c', 'content_d')
        self.assertFalse(md2._verify_patch(tree_a.branch.repository))


class TestParseOldMergeDirective2(tests.TestCase):

    def test_parse_old_merge_directive(self):
        md = merge_directive.MergeDirective.from_lines(INPUT1_2_OLD)
        self.assertEqual('example:', md.revision_id)
        self.assertEqual('sha', md.testament_sha1)
        self.assertEqual('http://example.com', md.target_branch)
        self.assertEqual('http://example.org', md.source_branch)
        self.assertEqual(453, md.time)
        self.assertEqual(120, md.timezone)
        self.assertEqual('booga', md.patch)
        self.assertEqual('diff', md.patch_type)
        self.assertEqual('Hi mom!', md.message)
