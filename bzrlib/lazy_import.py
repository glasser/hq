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

"""Functionality to create lazy evaluation objects.

This includes waiting to import a module until it is actually used.

Most commonly, the 'lazy_import' function is used to import other modules
in an on-demand fashion. Typically use looks like:
    from bzrlib.lazy_import import lazy_import
    lazy_import(globals(), '''
    from bzrlib import (
        errors,
        osutils,
        branch,
        )
    import bzrlib.branch
    ''')

    Then 'errors, osutils, branch' and 'bzrlib' will exist as lazy-loaded
    objects which will be replaced with a real object on first use.

    In general, it is best to only load modules in this way. This is because
    it isn't safe to pass these variables to other functions before they
    have been replaced. This is especially true for constants, sometimes
    true for classes or functions (when used as a factory, or you want
    to inherit from them).
"""


class ScopeReplacer(object):
    """A lazy object that will replace itself in the appropriate scope.

    This object sits, ready to create the real object the first time it is
    needed.
    """

    __slots__ = ('_scope', '_factory', '_name', '_real_obj')

    # Setting this to True will allow you to do x = y, and still access members
    # from both variables. This should not normally be enabled, but is useful
    # when building documentation.
    _should_proxy = False

    def __init__(self, scope, factory, name):
        """Create a temporary object in the specified scope.
        Once used, a real object will be placed in the scope.

        :param scope: The scope the object should appear in
        :param factory: A callable that will create the real object.
            It will be passed (self, scope, name)
        :param name: The variable name in the given scope.
        """
        object.__setattr__(self, '_scope', scope)
        object.__setattr__(self, '_factory', factory)
        object.__setattr__(self, '_name', name)
        object.__setattr__(self, '_real_obj', None)
        scope[name] = self

    def _replace(self):
        """Actually replace self with other in the given scope"""
        name = object.__getattribute__(self, '_name')
        try:
            factory = object.__getattribute__(self, '_factory')
            scope = object.__getattribute__(self, '_scope')
        except AttributeError, e:
            # Because ScopeReplacer objects only replace a single
            # item, passing them to another variable before they are
            # replaced would cause them to keep getting replaced
            # (only they are replacing the wrong variable). So we
            # make it forbidden, and try to give a good error.
            raise errors.IllegalUseOfScopeReplacer(
                name, msg="Object already cleaned up, did you assign it"
                          " to another variable?",
                extra=e)
        obj = factory(self, scope, name)
        if ScopeReplacer._should_proxy:
            object.__setattr__(self, '_real_obj', obj)
        scope[name] = obj
        return obj

    def _cleanup(self):
        """Stop holding on to all the extra stuff"""
        del self._factory
        del self._scope
        # We keep _name, so that we can report errors
        # del self._name

    def __getattribute__(self, attr):
        obj = object.__getattribute__(self, '_real_obj')
        if obj is None:
            _replace = object.__getattribute__(self, '_replace')
            obj = _replace()
            _cleanup = object.__getattribute__(self, '_cleanup')
            _cleanup()
        return getattr(obj, attr)

    def __setattr__(self, attr, value):
        obj = object.__getattribute__(self, '_real_obj')
        if obj is None:
            _replace = object.__getattribute__(self, '_replace')
            obj = _replace()
            _cleanup = object.__getattribute__(self, '_cleanup')
            _cleanup()
        return setattr(obj, attr, value)

    def __call__(self, *args, **kwargs):
        _replace = object.__getattribute__(self, '_replace')
        obj = _replace()
        _cleanup = object.__getattribute__(self, '_cleanup')
        _cleanup()
        return obj(*args, **kwargs)


class ImportReplacer(ScopeReplacer):
    """This is designed to replace only a portion of an import list.

    It will replace itself with a module, and then make children
    entries also ImportReplacer objects.

    At present, this only supports 'import foo.bar.baz' syntax.
    """

    # '_import_replacer_children' is intentionally a long semi-unique name
    # that won't likely exist elsewhere. This allows us to detect an
    # ImportReplacer object by using
    #       object.__getattribute__(obj, '_import_replacer_children')
    # We can't just use 'isinstance(obj, ImportReplacer)', because that
    # accesses .__class__, which goes through __getattribute__, and triggers
    # the replacement.
    __slots__ = ('_import_replacer_children', '_member', '_module_path')

    def __init__(self, scope, name, module_path, member=None, children={}):
        """Upon request import 'module_path' as the name 'module_name'.
        When imported, prepare children to also be imported.

        :param scope: The scope that objects should be imported into.
            Typically this is globals()
        :param name: The variable name. Often this is the same as the 
            module_path. 'bzrlib'
        :param module_path: A list for the fully specified module path
            ['bzrlib', 'foo', 'bar']
        :param member: The member inside the module to import, often this is
            None, indicating the module is being imported.
        :param children: Children entries to be imported later.
            This should be a map of children specifications.
            {'foo':(['bzrlib', 'foo'], None, 
                {'bar':(['bzrlib', 'foo', 'bar'], None {})})
            }
        Examples:
            import foo => name='foo' module_path='foo',
                          member=None, children={}
            import foo.bar => name='foo' module_path='foo', member=None,
                              children={'bar':(['foo', 'bar'], None, {}}
            from foo import bar => name='bar' module_path='foo', member='bar'
                                   children={}
            from foo import bar, baz would get translated into 2 import
            requests. On for 'name=bar' and one for 'name=baz'
        """
        if (member is not None) and children:
            raise ValueError('Cannot supply both a member and children')

        object.__setattr__(self, '_import_replacer_children', children)
        object.__setattr__(self, '_member', member)
        object.__setattr__(self, '_module_path', module_path)

        # Indirecting through __class__ so that children can
        # override _import (especially our instrumented version)
        cls = object.__getattribute__(self, '__class__')
        ScopeReplacer.__init__(self, scope=scope, name=name,
                               factory=cls._import)

    def _import(self, scope, name):
        children = object.__getattribute__(self, '_import_replacer_children')
        member = object.__getattribute__(self, '_member')
        module_path = object.__getattribute__(self, '_module_path')
        module_python_path = '.'.join(module_path)
        if member is not None:
            module = __import__(module_python_path, scope, scope, [member])
            return getattr(module, member)
        else:
            module = __import__(module_python_path, scope, scope, [])
            for path in module_path[1:]:
                module = getattr(module, path)

        # Prepare the children to be imported
        for child_name, (child_path, child_member, grandchildren) in \
                children.iteritems():
            # Using self.__class__, so that children get children classes
            # instantiated. (This helps with instrumented tests)
            cls = object.__getattribute__(self, '__class__')
            cls(module.__dict__, name=child_name,
                module_path=child_path, member=child_member,
                children=grandchildren)
        return module


class ImportProcessor(object):
    """Convert text that users input into lazy import requests"""

    # TODO: jam 20060912 This class is probably not strict enough about
    #       what type of text it allows. For example, you can do:
    #       import (foo, bar), which is not allowed by python.
    #       For now, it should be supporting a superset of python import
    #       syntax which is all we really care about.

    __slots__ = ['imports', '_lazy_import_class']

    def __init__(self, lazy_import_class=None):
        self.imports = {}
        if lazy_import_class is None:
            self._lazy_import_class = ImportReplacer
        else:
            self._lazy_import_class = lazy_import_class

    def lazy_import(self, scope, text):
        """Convert the given text into a bunch of lazy import objects.

        This takes a text string, which should be similar to normal python
        import markup.
        """
        self._build_map(text)
        self._convert_imports(scope)

    def _convert_imports(self, scope):
        # Now convert the map into a set of imports
        for name, info in self.imports.iteritems():
            self._lazy_import_class(scope, name=name, module_path=info[0],
                                    member=info[1], children=info[2])

    def _build_map(self, text):
        """Take a string describing imports, and build up the internal map"""
        for line in self._canonicalize_import_text(text):
            if line.startswith('import '):
                self._convert_import_str(line)
            elif line.startswith('from '):
                self._convert_from_str(line)
            else:
                raise errors.InvalidImportLine(line,
                    "doesn't start with 'import ' or 'from '")

    def _convert_import_str(self, import_str):
        """This converts a import string into an import map.

        This only understands 'import foo, foo.bar, foo.bar.baz as bing'

        :param import_str: The import string to process
        """
        if not import_str.startswith('import '):
            raise ValueError('bad import string %r' % (import_str,))
        import_str = import_str[len('import '):]

        for path in import_str.split(','):
            path = path.strip()
            if not path:
                continue
            as_hunks = path.split(' as ')
            if len(as_hunks) == 2:
                # We have 'as' so this is a different style of import
                # 'import foo.bar.baz as bing' creates a local variable
                # named 'bing' which points to 'foo.bar.baz'
                name = as_hunks[1].strip()
                module_path = as_hunks[0].strip().split('.')
                if name in self.imports:
                    raise errors.ImportNameCollision(name)
                # No children available in 'import foo as bar'
                self.imports[name] = (module_path, None, {})
            else:
                # Now we need to handle
                module_path = path.split('.')
                name = module_path[0]
                if name not in self.imports:
                    # This is a new import that we haven't seen before
                    module_def = ([name], None, {})
                    self.imports[name] = module_def
                else:
                    module_def = self.imports[name]

                cur_path = [name]
                cur = module_def[2]
                for child in module_path[1:]:
                    cur_path.append(child)
                    if child in cur:
                        cur = cur[child][2]
                    else:
                        next = (cur_path[:], None, {})
                        cur[child] = next
                        cur = next[2]

    def _convert_from_str(self, from_str):
        """This converts a 'from foo import bar' string into an import map.

        :param from_str: The import string to process
        """
        if not from_str.startswith('from '):
            raise ValueError('bad from/import %r' % from_str)
        from_str = from_str[len('from '):]

        from_module, import_list = from_str.split(' import ')

        from_module_path = from_module.split('.')

        for path in import_list.split(','):
            path = path.strip()
            if not path:
                continue
            as_hunks = path.split(' as ')
            if len(as_hunks) == 2:
                # We have 'as' so this is a different style of import
                # 'import foo.bar.baz as bing' creates a local variable
                # named 'bing' which points to 'foo.bar.baz'
                name = as_hunks[1].strip()
                module = as_hunks[0].strip()
            else:
                name = module = path
            if name in self.imports:
                raise errors.ImportNameCollision(name)
            self.imports[name] = (from_module_path, module, {})

    def _canonicalize_import_text(self, text):
        """Take a list of imports, and split it into regularized form.

        This is meant to take regular import text, and convert it to
        the forms that the rest of the converters prefer.
        """
        out = []
        cur = None
        continuing = False

        for line in text.split('\n'):
            line = line.strip()
            loc = line.find('#')
            if loc != -1:
                line = line[:loc].strip()

            if not line:
                continue
            if cur is not None:
                if line.endswith(')'):
                    out.append(cur + ' ' + line[:-1])
                    cur = None
                else:
                    cur += ' ' + line
            else:
                if '(' in line and ')' not in line:
                    cur = line.replace('(', '')
                else:
                    out.append(line.replace('(', '').replace(')', ''))
        if cur is not None:
            raise errors.InvalidImportLine(cur, 'Unmatched parenthesis')
        return out


def lazy_import(scope, text, lazy_import_class=None):
    """Create lazy imports for all of the imports in text.

    This is typically used as something like:
    from bzrlib.lazy_import import lazy_import
    lazy_import(globals(), '''
    from bzrlib import (
        foo,
        bar,
        baz,
        )
    import bzrlib.branch
    import bzrlib.transport
    ''')

    Then 'foo, bar, baz' and 'bzrlib' will exist as lazy-loaded
    objects which will be replaced with a real object on first use.

    In general, it is best to only load modules in this way. This is
    because other objects (functions/classes/variables) are frequently
    used without accessing a member, which means we cannot tell they
    have been used.
    """
    # This is just a helper around ImportProcessor.lazy_import
    proc = ImportProcessor(lazy_import_class=lazy_import_class)
    return proc.lazy_import(scope, text)


# The only module that this module depends on is 'bzrlib.errors'. But it
# can actually be imported lazily, since we only need it if there is a
# problem.

lazy_import(globals(), """
from bzrlib import errors
""")
