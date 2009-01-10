# Bazaar -- distributed version control
#
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

import sys


def show_status(state, kind, name, to_file=None):
    if kind == 'directory':
        # use this even on windows?
        kind_ch = '/'
    elif kind == 'symlink':
        kind_ch = '->'
    elif kind == 'file':
        kind_ch = ''
    else:
        raise ValueError(kind)

    if len(state) != 1:
        raise ValueError(state)
        
    if to_file is None:
        to_file = sys.stdout

    to_file.write(state + '       ' + name + kind_ch + '\n')
    
