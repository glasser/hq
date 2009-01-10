# Copyright (C) 2008 Canonical Ltd
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

from bzrlib import xml8


class Serializer_v6(xml8.Serializer_v8):
    """This serialiser supports rich roots.

    While its inventory format number is 6, its revision format is 5.
    Its inventory_sha1 may be inaccurate-- the inventory may have been
    converted from format 5 or 7 without updating the sha1.
    """

    format_num = '6'
    # Format 6 & 7 reported their revision format as 5.
    revision_format_num = '5'


serializer_v6 = Serializer_v6()
