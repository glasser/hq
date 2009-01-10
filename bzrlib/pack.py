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

"""Container format for Bazaar data.

"Containers" and "records" are described in
doc/developers/container-format.txt.
"""

from cStringIO import StringIO
import re

from bzrlib import errors


FORMAT_ONE = "Bazaar pack format 1 (introduced in 0.18)"


_whitespace_re = re.compile('[\t\n\x0b\x0c\r ]')


def _check_name(name):
    """Do some basic checking of 'name'.
    
    At the moment, this just checks that there are no whitespace characters in a
    name.

    :raises InvalidRecordError: if name is not valid.
    :seealso: _check_name_encoding
    """
    if _whitespace_re.search(name) is not None:
        raise errors.InvalidRecordError("%r is not a valid name." % (name,))


def _check_name_encoding(name):
    """Check that 'name' is valid UTF-8.
    
    This is separate from _check_name because UTF-8 decoding is relatively
    expensive, and we usually want to avoid it.

    :raises InvalidRecordError: if name is not valid UTF-8.
    """
    try:
        name.decode('utf-8')
    except UnicodeDecodeError, e:
        raise errors.InvalidRecordError(str(e))


class ContainerSerialiser(object):
    """A helper class for serialising containers.
    
    It simply returns bytes from method calls to 'begin', 'end' and
    'bytes_record'.  You may find ContainerWriter to be a more convenient
    interface.
    """

    def begin(self):
        """Return the bytes to begin a container."""
        return FORMAT_ONE + "\n"

    def end(self):
        """Return the bytes to finish a container."""
        return "E"

    def bytes_record(self, bytes, names):
        """Return the bytes for a Bytes record with the given name and
        contents.
        """
        # Kind marker
        byte_sections = ["B"]
        # Length
        byte_sections.append(str(len(bytes)) + "\n")
        # Names
        for name_tuple in names:
            # Make sure we're writing valid names.  Note that we will leave a
            # half-written record if a name is bad!
            for name in name_tuple:
                _check_name(name)
            byte_sections.append('\x00'.join(name_tuple) + "\n")
        # End of headers
        byte_sections.append("\n")
        # Finally, the contents.
        byte_sections.append(bytes)
        # XXX: This causes a memory copy of bytes in size, but is usually
        # faster than two write calls (12 vs 13 seconds to output a gig of
        # 1k records.) - results may differ on significantly larger records
        # like .iso's but as they should be rare in any case and thus not
        # likely to be the common case. The biggest issue is causing extreme
        # memory pressure in that case. One possibly improvement here is to
        # check the size of the content before deciding to join here vs call
        # write twice.
        return ''.join(byte_sections)


class ContainerWriter(object):
    """A class for writing containers to a file.

    :attribute records_written: The number of user records added to the
        container. This does not count the prelude or suffix of the container
        introduced by the begin() and end() methods.
    """

    def __init__(self, write_func):
        """Constructor.

        :param write_func: a callable that will be called when this
            ContainerWriter needs to write some bytes.
        """
        self._write_func = write_func
        self.current_offset = 0
        self.records_written = 0
        self._serialiser = ContainerSerialiser()

    def begin(self):
        """Begin writing a container."""
        self.write_func(self._serialiser.begin())

    def write_func(self, bytes):
        self._write_func(bytes)
        self.current_offset += len(bytes)

    def end(self):
        """Finish writing a container."""
        self.write_func(self._serialiser.end())

    def add_bytes_record(self, bytes, names):
        """Add a Bytes record with the given names.
        
        :param bytes: The bytes to insert.
        :param names: The names to give the inserted bytes. Each name is
            a tuple of bytestrings. The bytestrings may not contain
            whitespace.
        :return: An offset, length tuple. The offset is the offset
            of the record within the container, and the length is the
            length of data that will need to be read to reconstitute the
            record. These offset and length can only be used with the pack
            interface - they might be offset by headers or other such details
            and thus are only suitable for use by a ContainerReader.
        """
        current_offset = self.current_offset
        serialised_record = self._serialiser.bytes_record(bytes, names)
        self.write_func(serialised_record)
        self.records_written += 1
        # return a memo of where we wrote data to allow random access.
        return current_offset, self.current_offset - current_offset


class ReadVFile(object):
    """Adapt a readv result iterator to a file like protocol."""

    def __init__(self, readv_result):
        self.readv_result = readv_result
        # the most recent readv result block
        self._string = None

    def _next(self):
        if (self._string is None or
            self._string.tell() == self._string_length):
            length, data = self.readv_result.next()
            self._string_length = len(data)
            self._string = StringIO(data)

    def read(self, length):
        self._next()
        result = self._string.read(length)
        if len(result) < length:
            raise errors.BzrError('request for too much data from a readv hunk.')
        return result

    def readline(self):
        """Note that readline will not cross readv segments."""
        self._next()
        result = self._string.readline()
        if self._string.tell() == self._string_length and result[-1] != '\n':
            raise errors.BzrError('short readline in the readvfile hunk.')
        return result


def make_readv_reader(transport, filename, requested_records):
    """Create a ContainerReader that will read selected records only.

    :param transport: The transport the pack file is located on.
    :param filename: The filename of the pack file.
    :param requested_records: The record offset, length tuples as returned
        by add_bytes_record for the desired records.
    """
    readv_blocks = [(0, len(FORMAT_ONE)+1)]
    readv_blocks.extend(requested_records)
    result = ContainerReader(ReadVFile(
        transport.readv(filename, readv_blocks)))
    return result


class BaseReader(object):

    def __init__(self, source_file):
        """Constructor.

        :param source_file: a file-like object with `read` and `readline`
            methods.
        """
        self._source = source_file

    def reader_func(self, length=None):
        return self._source.read(length)

    def _read_line(self):
        line = self._source.readline()
        if not line.endswith('\n'):
            raise errors.UnexpectedEndOfContainerError()
        return line.rstrip('\n')


class ContainerReader(BaseReader):
    """A class for reading Bazaar's container format."""

    def iter_records(self):
        """Iterate over the container, yielding each record as it is read.

        Each yielded record will be a 2-tuple of (names, callable), where names
        is a ``list`` and bytes is a function that takes one argument,
        ``max_length``.

        You **must not** call the callable after advancing the interator to the
        next record.  That is, this code is invalid::

            record_iter = container.iter_records()
            names1, callable1 = record_iter.next()
            names2, callable2 = record_iter.next()
            bytes1 = callable1(None)
        
        As it will give incorrect results and invalidate the state of the
        ContainerReader.

        :raises ContainerError: if any sort of containter corruption is
            detected, e.g. UnknownContainerFormatError is the format of the
            container is unrecognised.
        :seealso: ContainerReader.read
        """
        self._read_format()
        return self._iter_records()
    
    def iter_record_objects(self):
        """Iterate over the container, yielding each record as it is read.

        Each yielded record will be an object with ``read`` and ``validate``
        methods.  Like with iter_records, it is not safe to use a record object
        after advancing the iterator to yield next record.

        :raises ContainerError: if any sort of containter corruption is
            detected, e.g. UnknownContainerFormatError is the format of the
            container is unrecognised.
        :seealso: iter_records
        """
        self._read_format()
        return self._iter_record_objects()
    
    def _iter_records(self):
        for record in self._iter_record_objects():
            yield record.read()

    def _iter_record_objects(self):
        while True:
            record_kind = self.reader_func(1)
            if record_kind == 'B':
                # Bytes record.
                reader = BytesRecordReader(self._source)
                yield reader
            elif record_kind == 'E':
                # End marker.  There are no more records.
                return
            elif record_kind == '':
                # End of stream encountered, but no End Marker record seen, so
                # this container is incomplete.
                raise errors.UnexpectedEndOfContainerError()
            else:
                # Unknown record type.
                raise errors.UnknownRecordTypeError(record_kind)

    def _read_format(self):
        format = self._read_line()
        if format != FORMAT_ONE:
            raise errors.UnknownContainerFormatError(format)

    def validate(self):
        """Validate this container and its records.

        Validating consumes the data stream just like iter_records and
        iter_record_objects, so you cannot call it after
        iter_records/iter_record_objects.

        :raises ContainerError: if something is invalid.
        """
        all_names = set()
        for record_names, read_bytes in self.iter_records():
            read_bytes(None)
            for name_tuple in record_names:
                for name in name_tuple:
                    _check_name_encoding(name)
                # Check that the name is unique.  Note that Python will refuse
                # to decode non-shortest forms of UTF-8 encoding, so there is no
                # risk that the same unicode string has been encoded two
                # different ways.
                if name_tuple in all_names:
                    raise errors.DuplicateRecordNameError(name_tuple)
                all_names.add(name_tuple)
        excess_bytes = self.reader_func(1)
        if excess_bytes != '':
            raise errors.ContainerHasExcessDataError(excess_bytes)


class BytesRecordReader(BaseReader):

    def read(self):
        """Read this record.

        You can either validate or read a record, you can't do both.

        :returns: A tuple of (names, callable).  The callable can be called
            repeatedly to obtain the bytes for the record, with a max_length
            argument.  If max_length is None, returns all the bytes.  Because
            records can be arbitrarily large, using None is not recommended
            unless you have reason to believe the content will fit in memory.
        """
        # Read the content length.
        length_line = self._read_line()
        try:
            length = int(length_line)
        except ValueError:
            raise errors.InvalidRecordError(
                "%r is not a valid length." % (length_line,))
        
        # Read the list of names.
        names = []
        while True:
            name_line = self._read_line()
            if name_line == '':
                break
            name_tuple = tuple(name_line.split('\x00'))
            for name in name_tuple:
                _check_name(name)
            names.append(name_tuple)

        self._remaining_length = length
        return names, self._content_reader

    def _content_reader(self, max_length):
        if max_length is None:
            length_to_read = self._remaining_length
        else:
            length_to_read = min(max_length, self._remaining_length)
        self._remaining_length -= length_to_read
        bytes = self.reader_func(length_to_read)
        if len(bytes) != length_to_read:
            raise errors.UnexpectedEndOfContainerError()
        return bytes

    def validate(self):
        """Validate this record.

        You can either validate or read, you can't do both.

        :raises ContainerError: if this record is invalid.
        """
        names, read_bytes = self.read()
        for name_tuple in names:
            for name in name_tuple:
                _check_name_encoding(name)
        read_bytes(None)


class ContainerPushParser(object):
    """A "push" parser for container format 1.

    It accepts bytes via the ``accept_bytes`` method, and parses them into
    records which can be retrieved via the ``read_pending_records`` method.
    """

    def __init__(self):
        self._buffer = ''
        self._state_handler = self._state_expecting_format_line
        self._parsed_records = []
        self._reset_current_record()
        self.finished = False

    def _reset_current_record(self):
        self._current_record_length = None
        self._current_record_names = []

    def accept_bytes(self, bytes):
        self._buffer += bytes
        # Keep iterating the state machine until it stops consuming bytes from
        # the buffer.
        last_buffer_length = None
        cur_buffer_length = len(self._buffer)
        while cur_buffer_length != last_buffer_length:
            last_buffer_length = cur_buffer_length
            self._state_handler()
            cur_buffer_length = len(self._buffer)

    def read_pending_records(self):
        records = self._parsed_records
        self._parsed_records = []
        return records
    
    def _consume_line(self):
        """Take a line out of the buffer, and return the line.

        If a newline byte is not found in the buffer, the buffer is
        unchanged and this returns None instead.
        """
        newline_pos = self._buffer.find('\n')
        if newline_pos != -1:
            line = self._buffer[:newline_pos]
            self._buffer = self._buffer[newline_pos+1:]
            return line
        else:
            return None

    def _state_expecting_format_line(self):
        line = self._consume_line()
        if line is not None:
            if line != FORMAT_ONE:
                raise errors.UnknownContainerFormatError(line)
            self._state_handler = self._state_expecting_record_type

    def _state_expecting_record_type(self):
        if len(self._buffer) >= 1:
            record_type = self._buffer[0]
            self._buffer = self._buffer[1:]
            if record_type == 'B':
                self._state_handler = self._state_expecting_length
            elif record_type == 'E':
                self.finished = True
                self._state_handler = self._state_expecting_nothing
            else:
                raise errors.UnknownRecordTypeError(record_type)

    def _state_expecting_length(self):
        line = self._consume_line()
        if line is not None:
            try:
                self._current_record_length = int(line)
            except ValueError:
                raise errors.InvalidRecordError(
                    "%r is not a valid length." % (line,))
            self._state_handler = self._state_expecting_name

    def _state_expecting_name(self):
        encoded_name_parts = self._consume_line()
        if encoded_name_parts == '':
            self._state_handler = self._state_expecting_body
        elif encoded_name_parts:
            name_parts = tuple(encoded_name_parts.split('\x00'))
            for name_part in name_parts:
                _check_name(name_part)
            self._current_record_names.append(name_parts)
            
    def _state_expecting_body(self):
        if len(self._buffer) >= self._current_record_length:
            body_bytes = self._buffer[:self._current_record_length]
            self._buffer = self._buffer[self._current_record_length:]
            record = (self._current_record_names, body_bytes)
            self._parsed_records.append(record)
            self._reset_current_record()
            self._state_handler = self._state_expecting_record_type

    def _state_expecting_nothing(self):
        pass

    def read_size_hint(self):
        hint = 16384
        if self._state_handler == self._state_expecting_body:
            remaining = self._current_record_length - len(self._buffer)
            if remaining < 0:
                remaining = 0
            return max(hint, remaining)
        return hint


def iter_records_from_file(source_file):
    parser = ContainerPushParser()
    while True:
        bytes = source_file.read(parser.read_size_hint())
        parser.accept_bytes(bytes)
        for record in parser.read_pending_records():
            yield record
        if parser.finished:
            break

