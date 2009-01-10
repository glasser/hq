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

"""A collection of extra help information for using bzr.

Help topics are meant to be help for items that aren't commands, but will
help bzr become fully learnable without referring to a tutorial.

Limited formatting of help text is permitted to make the text useful
both within the reference manual (reStructuredText) and on the screen.
The help text should be reStructuredText with formatting kept to a
minimum and, in particular, no headings. The onscreen renderer applies
the following simple rules before rendering the text:

    1. A '::' appearing on the end of a line is replaced with ':'.
    2. Lines starting with a ':' have it stripped.

These rules mean that literal blocks and field lists respectively can
be used in the help text, producing sensible input to a manual while
rendering on the screen naturally.
"""

import sys

import bzrlib
from bzrlib import (
    osutils,
    registry,
    )


# Section identifiers (map topics to the right place in the manual)
SECT_COMMAND = "command"
SECT_CONCEPT = "concept"
SECT_HIDDEN =  "hidden"
SECT_LIST    = "list"
SECT_PLUGIN  = "plugin"


class HelpTopicRegistry(registry.Registry):
    """A Registry customized for handling help topics."""

    def register(self, topic, detail, summary, section=SECT_LIST):
        """Register a new help topic.

        :param topic: Name of documentation entry
        :param detail: Function or string object providing detailed
            documentation for topic.  Function interface is detail(topic).
            This should return a text string of the detailed information.
            See the module documentation for details on help text formatting.
        :param summary: String providing single-line documentation for topic.
        :param section: Section in reference manual - see SECT_* identifiers.
        """
        # The detail is stored as the 'object' and the metadata as the info
        info=(summary,section)
        super(HelpTopicRegistry, self).register(topic, detail, info=info)

    def register_lazy(self, topic, module_name, member_name, summary,
                      section=SECT_LIST):
        """Register a new help topic, and import the details on demand.

        :param topic: Name of documentation entry
        :param module_name: The module to find the detailed help.
        :param member_name: The member of the module to use for detailed help.
        :param summary: String providing single-line documentation for topic.
        :param section: Section in reference manual - see SECT_* identifiers.
        """
        # The detail is stored as the 'object' and the metadata as the info
        info=(summary,section)
        super(HelpTopicRegistry, self).register_lazy(topic, module_name,
                                                     member_name, info=info)

    def get_detail(self, topic):
        """Get the detailed help on a given topic."""
        obj = self.get(topic)
        if callable(obj):
            return obj(topic)
        else:
            return obj

    def get_summary(self, topic):
        """Get the single line summary for the topic."""
        info = self.get_info(topic)
        if info is None:
            return None
        else:
            return info[0]

    def get_section(self, topic):
        """Get the section for the topic."""
        info = self.get_info(topic)
        if info is None:
            return None
        else:
            return info[1]

    def get_topics_for_section(self, section):
        """Get the set of topics in a section."""
        result = set()
        for topic in self.keys():
            if section == self.get_section(topic):
                result.add(topic)
        return result


topic_registry = HelpTopicRegistry()


#----------------------------------------------------

def _help_on_topics(dummy):
    """Write out the help for topics to outfile"""

    topics = topic_registry.keys()
    lmax = max(len(topic) for topic in topics)
        
    out = []
    for topic in topics:
        summary = topic_registry.get_summary(topic)
        out.append("%-*s %s\n" % (lmax, topic, summary))
    return ''.join(out)


def _load_from_file(topic_name):
    """Load help from a file.

    Topics are expected to be txt files in bzrlib.help_topics.
    """
    resource_name = osutils.pathjoin("en", "%s.txt" % (topic_name,))
    return osutils.resource_string('bzrlib.help_topics', resource_name)


def _help_on_revisionspec(name):
    """Generate the help for revision specs."""
    import re
    import bzrlib.revisionspec

    out = []
    out.append(
"""Revision Identifiers

A revision identifier refers to a specific state of a branch's history. It can
be a revision number, or a keyword followed by ':' and often other
parameters. Some examples of identifiers are '3', 'last:1', 'before:yesterday'
and 'submit:'.

If 'REV1' and 'REV2' are revision identifiers, then 'REV1..REV2' denotes a
revision range. Examples: '3647..3649', 'date:yesterday..-1' and
'branch:/path/to/branch1/..branch:/branch2' (note that there are no quotes or
spaces around the '..').

Ranges are interpreted differently by different commands. To the "log" command,
a range is a sequence of log messages, but to the "diff" command, the range
denotes a change between revisions (and not a sequence of changes).  In
addition, "log" considers a closed range whereas "diff" and "merge" consider it
to be open-ended, that is, they include one end but not the other.  For example:
"bzr log -r 3647..3649" shows the messages of revisions 3647, 3648 and 3649,
while "bzr diff -r 3647..3649" includes the changes done in revisions 3647 and
3648, but not 3649.

The keywords used as revision selection methods are the following:
""")
    details = []
    details.append("\nIn addition, plugins can provide other keywords.")
    details.append("\nA detailed description of each keyword is given below.\n")

    # The help text is indented 4 spaces - this re cleans that up below
    indent_re = re.compile(r'^    ', re.MULTILINE)
    for i in bzrlib.revisionspec.SPEC_TYPES:
        doc = i.help_txt
        if doc == bzrlib.revisionspec.RevisionSpec.help_txt:
            summary = "N/A"
            doc = summary + "\n"
        else:
            # Extract out the top line summary from the body and
            # clean-up the unwanted whitespace
            summary,doc = doc.split("\n", 1)
            #doc = indent_re.sub('', doc)
            while (doc[-2:] == '\n\n' or doc[-1:] == ' '):
                doc = doc[:-1]
        
        # Note: The leading : here are HACKs to get reStructuredText
        # 'field' formatting - we know that the prefix ends in a ':'.
        out.append(":%s\n\t%s" % (i.prefix, summary))
        details.append(":%s\n%s" % (i.prefix, doc))

    return '\n'.join(out + details)


def _help_on_transport(name):
    from bzrlib.transport import (
        transport_list_registry,
    )
    import textwrap

    def add_string(proto, help, maxl, prefix_width=20):
       help_lines = textwrap.wrap(help, maxl - prefix_width)
       line_with_indent = '\n' + ' ' * prefix_width
       help_text = line_with_indent.join(help_lines)
       return "%-20s%s\n" % (proto, help_text)

    def sort_func(a,b):
        a1 = a[:a.rfind("://")]
        b1 = b[:b.rfind("://")]
        if a1>b1:
            return +1
        elif a1<b1:
            return -1
        else:
            return 0

    protl = []
    decl = []
    protos = transport_list_registry.keys( )
    protos.sort(sort_func)
    for proto in protos:
        shorthelp = transport_list_registry.get_help(proto)
        if not shorthelp:
            continue
        if proto.endswith("://"):
            protl.append(add_string(proto, shorthelp, 79))
        else:
            decl.append(add_string(proto, shorthelp, 79))


    out = "URL Identifiers\n\n" + \
            "Supported URL prefixes::\n\n  " + \
            '  '.join(protl)

    if len(decl):
        out += "\nSupported modifiers::\n\n  " + \
            '  '.join(decl)

    return out


_basic_help = \
"""Bazaar -- a free distributed version-control tool
http://bazaar-vcs.org/

Basic commands:
  bzr init           makes this directory a versioned branch
  bzr branch         make a copy of another branch

  bzr add            make files or directories versioned
  bzr ignore         ignore a file or pattern
  bzr mv             move or rename a versioned file

  bzr status         summarize changes in working copy
  bzr diff           show detailed diffs

  bzr merge          pull in changes from another branch
  bzr commit         save some or all changes
  bzr send           send changes via email

  bzr log            show history of changes
  bzr check          validate storage

  bzr help init      more help on e.g. init command
  bzr help commands  list all commands
  bzr help topics    list all help topics
"""


_global_options = \
"""Global Options

These options may be used with any command, and may appear in front of any
command.  (e.g. "bzr --profile help").

--version      Print the version number. Must be supplied before the command.
--no-aliases   Do not process command aliases when running this command.
--builtin      Use the built-in version of a command, not the plugin version.
               This does not suppress other plugin effects.
--no-plugins   Do not process any plugins.

--profile      Profile execution using the hotshot profiler.
--lsprof       Profile execution using the lsprof profiler.
--lsprof-file  Profile execution using the lsprof profiler, and write the
               results to a specified file.  If the filename ends with ".txt",
               text format will be used.  If the filename either starts with
               "callgrind.out" or end with ".callgrind", the output will be
               formatted for use with KCacheGrind. Otherwise, the output
               will be a pickle.
--coverage     Generate line coverage report in the specified directory.

See doc/developers/profiling.txt for more information on profiling.
A number of debug flags are also available to assist troubleshooting and
development.

-Dauth            Trace authentication sections used.
-Derror           Instead of normal error handling, always print a traceback
                  on error.
-Devil            Capture call sites that do expensive or badly-scaling
                  operations.
-Dfetch           Trace history copying between repositories.
-Dhashcache       Log every time a working file is read to determine its hash.
-Dhooks           Trace hook execution.
-Dhpss            Trace smart protocol requests and responses.
-Dhttp            Trace http connections, requests and responses
-Dindex           Trace major index operations.
-Dknit            Trace knit operations.
-Dlock            Trace when lockdir locks are taken or released.
-Dmerge           Emit information for debugging merges.
-Dpack            Emit information about pack operations.
"""

_standard_options = \
"""Standard Options

Standard options are legal for all commands.
      
--help, -h     Show help message.
--verbose, -v  Display more information.
--quiet, -q    Only display errors and warnings.

Unlike global options, standard options can be used in aliases.
"""


_checkouts = \
"""Checkouts

Checkouts are source trees that are connected to a branch, so that when
you commit in the source tree, the commit goes into that branch.  They
allow you to use a simpler, more centralized workflow, ignoring some of
Bazaar's decentralized features until you want them. Using checkouts
with shared repositories is very similar to working with SVN or CVS, but
doesn't have the same restrictions.  And using checkouts still allows
others working on the project to use whatever workflow they like.

A checkout is created with the bzr checkout command (see "help checkout").
You pass it a reference to another branch, and it will create a local copy
for you that still contains a reference to the branch you created the
checkout from (the master branch). Then if you make any commits they will be
made on the other branch first. This creates an instant mirror of your work, or
facilitates lockstep development, where each developer is working together,
continuously integrating the changes of others.

However the checkout is still a first class branch in Bazaar terms, so that
you have the full history locally.  As you have a first class branch you can
also commit locally if you want, for instance due to the temporary loss af a
network connection. Use the --local option to commit to do this. All the local
commits will then be made on the master branch the next time you do a non-local
commit.

If you are using a checkout from a shared branch you will periodically want to
pull in all the changes made by others. This is done using the "update"
command. The changes need to be applied before any non-local commit, but
Bazaar will tell you if there are any changes and suggest that you use this
command when needed.

It is also possible to create a "lightweight" checkout by passing the
--lightweight flag to checkout. A lightweight checkout is even closer to an
SVN checkout in that it is not a first class branch, it mainly consists of the
working tree. This means that any history operations must query the master
branch, which could be slow if a network connection is involved. Also, as you
don't have a local branch, then you cannot commit locally.

Lightweight checkouts work best when you have fast reliable access to the
master branch. This means that if the master branch is on the same disk or LAN
a lightweight checkout will be faster than a heavyweight one for any commands
that modify the revision history (as only one copy of the branch needs to
be updated). Heavyweight checkouts will generally be faster for any command
that uses the history but does not change it, but if the master branch is on
the same disk then there won't be a noticeable difference.

Another possible use for a checkout is to use it with a treeless repository
containing your branches, where you maintain only one working tree by
switching the master branch that the checkout points to when you want to 
work on a different branch.

Obviously to commit on a checkout you need to be able to write to the master
branch. This means that the master branch must be accessible over a writeable
protocol , such as sftp://, and that you have write permissions at the other
end. Checkouts also work on the local file system, so that all that matters is
file permissions.

You can change the master of a checkout by using the "bind" command (see "help
bind"). This will change the location that the commits are sent to. The bind
command can also be used to turn a branch into a heavy checkout. If you
would like to convert your heavy checkout into a normal branch so that every
commit is local, you can use the "unbind" command.

Related commands::

  checkout    Create a checkout. Pass --lightweight to get a lightweight
              checkout
  update      Pull any changes in the master branch in to your checkout
  commit      Make a commit that is sent to the master branch. If you have
              a heavy checkout then the --local option will commit to the 
              checkout without sending the commit to the master
  bind        Change the master branch that the commits in the checkout will
              be sent to
  unbind      Turn a heavy checkout into a standalone branch so that any
              commits are only made locally
"""

_repositories = \
"""Repositories

Repositories in Bazaar are where committed information is stored. There is
a repository associated with every branch.

Repositories are a form of database. Bzr will usually maintain this for
good performance automatically, but in some situations (e.g. when doing
very many commits in a short time period) you may want to ask bzr to 
optimise the database indices. This can be done by the 'bzr pack' command.

By default just running 'bzr init' will create a repository within the new
branch but it is possible to create a shared repository which allows multiple
branches to share their information in the same location. When a new branch is
created it will first look to see if there is a containing shared repository it
can use.

When two branches of the same project share a repository, there is
generally a large space saving. For some operations (e.g. branching
within the repository) this translates in to a large time saving.

To create a shared repository use the init-repository command (or the alias
init-repo). This command takes the location of the repository to create. This
means that 'bzr init-repository repo' will create a directory named 'repo',
which contains a shared repository. Any new branches that are created in this
directory will then use it for storage.

It is a good idea to create a repository whenever you might create more
than one branch of a project. This is true for both working areas where you
are doing the development, and any server areas that you use for hosting
projects. In the latter case, it is common to want branches without working
trees. Since the files in the branch will not be edited directly there is no
need to use up disk space for a working tree. To create a repository in which
the branches will not have working trees pass the '--no-trees' option to
'init-repository'.

Related commands::

  init-repository   Create a shared repository. Use --no-trees to create one
                    in which new branches won't get a working tree.
"""


_working_trees = \
"""Working Trees

A working tree is the contents of a branch placed on disk so that you can
see the files and edit them. The working tree is where you make changes to a
branch, and when you commit the current state of the working tree is the
snapshot that is recorded in the commit.

When you push a branch to a remote system, a working tree will not be
created. If one is already present the files will not be updated. The
branch information will be updated and the working tree will be marked
as out-of-date. Updating a working tree remotely is difficult, as there
may be uncommitted changes or the update may cause content conflicts that are
difficult to deal with remotely.

If you have a branch with no working tree you can use the 'checkout' command
to create a working tree. If you run 'bzr checkout .' from the branch it will
create the working tree. If the branch is updated remotely, you can update the
working tree by running 'bzr update' in that directory.

If you have a branch with a working tree that you do not want the 'remove-tree'
command will remove the tree if it is safe. This can be done to avoid the
warning about the remote working tree not being updated when pushing to the
branch. It can also be useful when working with a '--no-trees' repository
(see 'bzr help repositories').

If you want to have a working tree on a remote machine that you push to you
can either run 'bzr update' in the remote branch after each push, or use some
other method to update the tree during the push. There is an 'rspush' plugin
that will update the working tree using rsync as well as doing a push. There
is also a 'push-and-update' plugin that automates running 'bzr update' via SSH
after each push.

Useful commands::

  checkout     Create a working tree when a branch does not have one.
  remove-tree  Removes the working tree from a branch when it is safe to do so.
  update       When a working tree is out of sync with it's associated branch
               this will update the tree to match the branch.
"""


_branches = \
"""Branches

A branch consists of the state of a project, including all of its
history. All branches have a repository associated (which is where the
branch history is stored), but multiple branches may share the same
repository (a shared repository). Branches can be copied and merged.

Related commands::

  init    Change a directory into a versioned branch.
  branch  Create a new copy of a branch.
  merge   Perform a three-way merge.
"""


_standalone_trees = \
"""Standalone Trees

A standalone tree is a working tree with an associated repository. It
is an independently usable branch, with no dependencies on any other.
Creating a standalone tree (via bzr init) is the quickest way to put
an existing project under version control.

Related Commands::

  init    Make a directory into a versioned branch.
"""


_status_flags = \
"""Status Flags

Status flags are used to summarise changes to the working tree in a concise
manner.  They are in the form::

   xxx   <filename>

where the columns' meanings are as follows.

Column 1 - versioning/renames::

  + File versioned
  - File unversioned
  R File renamed
  ? File unknown
  C File has conflicts
  P Entry for a pending merge (not a file)

Column 2 - contents::

  N File created
  D File deleted
  K File kind changed
  M File modified

Column 3 - execute::

  * The execute bit was changed
"""


_env_variables = \
"""Environment Variables

================ =================================================================
BZRPATH          Path where bzr is to look for shell plugin external commands.
BZR_EMAIL        E-Mail address of the user. Overrides EMAIL.
EMAIL            E-Mail address of the user.
BZR_EDITOR       Editor for editing commit messages. Overrides EDITOR.
EDITOR           Editor for editing commit messages.
BZR_PLUGIN_PATH  Paths where bzr should look for plugins.
BZR_HOME         Directory holding .bazaar config dir. Overrides HOME.
BZR_HOME (Win32) Directory holding bazaar config dir. Overrides APPDATA and HOME.
BZR_REMOTE_PATH  Full name of remote 'bzr' command (for bzr+ssh:// URLs).
BZR_SSH          SSH client: paramiko (default), openssh, ssh, plink.
BZR_LOG          Location of .bzr.log (use '/dev/null' to suppress log).
BZR_LOG (Win32)  Location of .bzr.log (use 'NUL' to suppress log).
================ =================================================================
"""


_files = \
r"""Files

:On Linux:   ~/.bazaar/bazaar.conf
:On Windows: C:\\Documents and Settings\\username\\Application Data\\bazaar\\2.0\\bazaar.conf

Contains the user's default configuration. The section ``[DEFAULT]`` is
used to define general configuration that will be applied everywhere.
The section ``[ALIASES]`` can be used to create command aliases for
commonly used options.

A typical config file might look something like::

  [DEFAULT]
  email=John Doe <jdoe@isp.com>

  [ALIASES]
  commit = commit --strict
  log10 = log --short -r -10..-1
"""

_criss_cross = \
"""Criss-Cross

A criss-cross in the branch history can cause the default merge technique
to emit more conflicts than would normally be expected.

In complex merge cases, ``bzr merge --lca`` or ``bzr merge --weave`` may give
better results.  You may wish to ``bzr revert`` the working tree and merge
again.  Alternatively, use ``bzr remerge`` on particular conflicted files.

Criss-crosses occur in a branch's history if two branches merge the same thing
and then merge one another, or if two branches merge one another at the same
time.  They can be avoided by having each branch only merge from or into a
designated central branch (a "star topology").

Criss-crosses cause problems because of the way merge works.  Bazaar's default
merge is a three-way merger; in order to merge OTHER into THIS, it must
find a basis for comparison, BASE.  Using BASE, it can determine whether
differences between THIS and OTHER are due to one side adding lines, or
from another side removing lines.

Criss-crosses mean there is no good choice for a base.  Selecting the recent
merge points could cause one side's changes to be silently discarded.
Selecting older merge points (which Bazaar does) mean that extra conflicts
are emitted.

The ``weave`` merge type is not affected by this problem because it uses
line-origin detection instead of a basis revision to determine the cause of
differences.
"""

_branches_out_of_sync = """Branches out of sync

When reconfiguring a checkout, tree or branch into a lightweight checkout,
a local branch must be destroyed.  (For checkouts, this is the local branch
that serves primarily as a cache.)  If the branch-to-be-destroyed does not
have the same last revision as the new reference branch for the lightweight
checkout, data could be lost, so Bazaar refuses.

How you deal with this depends on *why* the branches are out of sync.

If you have a checkout and have done local commits, you can get back in sync
by running "bzr update" (and possibly "bzr commit").

If you have a branch and the remote branch is out-of-date, you can push
the local changes using "bzr push".  If the local branch is out of date, you
can do "bzr pull".  If both branches have had changes, you can merge, commit
and then push your changes.  If you decide that some of the changes aren't
useful, you can "push --overwrite" or "pull --overwrite" instead.
"""


# Register help topics
topic_registry.register("revisionspec", _help_on_revisionspec,
                        "Explain how to use --revision")
topic_registry.register('basic', _basic_help, "Basic commands", SECT_HIDDEN)
topic_registry.register('topics', _help_on_topics, "Topics list", SECT_HIDDEN)
def get_format_topic(topic):
    from bzrlib import bzrdir
    return "Storage Formats\n\n" + bzrdir.format_registry.help_topic(topic)
topic_registry.register('formats', get_format_topic, 'Directory formats')
topic_registry.register('standard-options', _standard_options,
                        'Options that can be used with any command')
topic_registry.register('global-options', _global_options,
                    'Options that control how Bazaar runs')
topic_registry.register('urlspec', _help_on_transport,
                        "Supported transport protocols")
topic_registry.register('status-flags', _status_flags,
                        "Help on status flags")
def get_bugs_topic(topic):
    from bzrlib import bugtracker
    return ("Bug Tracker Settings\n\n" + 
        bugtracker.tracker_registry.help_topic(topic))
topic_registry.register('bugs', get_bugs_topic, 'Bug tracker settings')
topic_registry.register('env-variables', _env_variables,
                        'Environment variable names and values')
topic_registry.register('files', _files,
                        'Information on configuration and log files')

# Load some of the help topics from files
topic_registry.register('authentication', _load_from_file,
                        'Information on configuring authentication')
topic_registry.register('configuration', _load_from_file,
                        'Details on the configuration settings available')
topic_registry.register('conflicts', _load_from_file,
                        'Types of conflicts and what to do about them')
topic_registry.register('hooks', _load_from_file,
                        'Points at which custom processing can be added')


# Register concept topics.
# Note that we might choose to remove these from the online help in the
# future or implement them via loading content from files. In the meantime,
# please keep them concise.
topic_registry.register('branches', _branches,
                        'Information on what a branch is', SECT_CONCEPT)
topic_registry.register('checkouts', _checkouts,
                        'Information on what a checkout is', SECT_CONCEPT)
topic_registry.register('patterns', _load_from_file,
                        'Information on the pattern syntax',
                        SECT_CONCEPT)
topic_registry.register('repositories', _repositories,
                        'Basic information on shared repositories.',
                        SECT_CONCEPT)
topic_registry.register('rules', _load_from_file,
                        'Information on defining rule-based preferences',
                        SECT_CONCEPT)
topic_registry.register('standalone-trees', _standalone_trees,
                        'Information on what a standalone tree is',
                        SECT_CONCEPT)
topic_registry.register('working-trees', _working_trees,
                        'Information on working trees', SECT_CONCEPT)
topic_registry.register('criss-cross', _criss_cross,
                        'Information on criss-cross merging', SECT_CONCEPT)
topic_registry.register('sync-for-reconfigure', _branches_out_of_sync,
                        'Steps to resolve "out-of-sync" when reconfiguring',
                        SECT_CONCEPT)


class HelpTopicIndex(object):
    """A index for bzr help that returns topics."""

    def __init__(self):
        self.prefix = ''

    def get_topics(self, topic):
        """Search for topic in the HelpTopicRegistry.

        :param topic: A topic to search for. None is treated as 'basic'.
        :return: A list which is either empty or contains a single
            RegisteredTopic entry.
        """
        if topic is None:
            topic = 'basic'
        if topic in topic_registry:
            return [RegisteredTopic(topic)]
        else:
            return []


class RegisteredTopic(object):
    """A help topic which has been registered in the HelpTopicRegistry.

    These topics consist of nothing more than the name of the topic - all
    data is retrieved on demand from the registry.
    """

    def __init__(self, topic):
        """Constructor.

        :param topic: The name of the topic that this represents.
        """
        self.topic = topic

    def get_help_text(self, additional_see_also=None, plain=True):
        """Return a string with the help for this topic.

        :param additional_see_also: Additional help topics to be
            cross-referenced.
        :param plain: if False, raw help (reStructuredText) is
            returned instead of plain text.
        """
        result = topic_registry.get_detail(self.topic)
        # there is code duplicated here and in bzrlib/plugin.py's 
        # matching Topic code. This should probably be factored in
        # to a helper function and a common base class.
        if additional_see_also is not None:
            see_also = sorted(set(additional_see_also))
        else:
            see_also = None
        if see_also:
            result += '\n:See also: '
            result += ', '.join(see_also)
            result += '\n'
        if plain:
            result = help_as_plain_text(result)
        return result

    def get_help_topic(self):
        """Return the help topic this can be found under."""
        return self.topic


def help_as_plain_text(text):
    """Minimal converter of reStructuredText to plain text."""
    lines = text.splitlines()
    result = []
    for line in lines:
        if line.startswith(':'):
            line = line[1:]
        elif line.endswith('::'):
            line = line[:-1]
        result.append(line)
    return "\n".join(result) + "\n"
