import time
from warnings import warn
from collections import namedtuple
from itertools import islice
from array import array

def ChunkIter( iterable, chunk_size ):
    """
    >>> list( ChunkIter( [1,2,3,4,5,6,7,8], 3 ) )
    [[1, 2, 3], [4, 5, 6], [7, 8]]
    """
    iterator = iter( iterable )
    while 1:
        chunk = list( islice( iterator, chunk_size ) )
        if not len( chunk ): break
        yield chunk

def SimpleFileParser(fields_spec, field_separator=None, ignore_errors=None,
                     has_header=None, header_rename=None):
    header_rename = dict(header_rename or {})
    if has_header == None:
        has_header = False

    def simple_file_parser(fileobj):
        if has_header:
            parser = HeadedRecordsParser(
                fields_spec, header_rename, ignore_errors
            )
        else:
            parser = RecordsParser(RecParser(fields_spec), ignore_errors)
        splitter = SimpleLinesSplitter(field_separator)
        for rec in parser(splitter(fileobj)):
            yield rec

    return simple_file_parser

def FileParser(rec_parser, field_separator=None, ignore_errors=None):
    """
    >>> src = ['a b:c 1', 'd e:f 2', 'h i:g 3']
    >>> parser = FileParser(
    ...     field_separator = ' ',
    ...     rec_parser = RecParser((
    ...         ('first',  str),
    ...         ('second', strlist(str, ':')),
    ...         ('third',  int), 
    ...     )),
    ... )
    >>> for rec in parser(src):
    ...     print rec
    Rec(first='a', second=['b', 'c'], third=1)
    Rec(first='d', second=['e', 'f'], third=2)
    Rec(first='h', second=['i', 'g'], third=3)

    >>> src = ['a b:c d:e']
    >>> parser = FileParser(
    ...     field_separator = ' ',
    ...     rec_parser = RecParser(
    ...         fields_spec = (('first',  str),),
    ...         tail_spec = (('second', strlist(str, ':')),),
    ...     ),
    ... )
    >>> for rec in parser(src):
    ...     print rec
    Rec(first='a', tail=[Rec(second=['b', 'c']), Rec(second=['d', 'e'])])
    """
    lines_splitter = SimpleLinesSplitter(field_separator or '\t')
    records_parser = RecordsParser(rec_parser, ignore_errors)
    def parse_file(fileobj):
        for rec in records_parser(lines_splitter(fileobj)):
            yield rec
    return parse_file

def SimpleLinesSplitter(field_separator=None):
    def simple_lines_splitter(lines):
        for line in lines:
            yield line.strip('\n').split(field_separator)
    return simple_lines_splitter

def RecordsParser(rec_parser, warn_on_errors=None):
    if warn_on_errors == None:
        warn_on_errors = False

    def parse_records(tuples_iter):
        for i, tup in enumerate(tuples_iter):
            try:
                yield rec_parser(tup)
            except BaseRecParseError, err:
                file_err = FileParseError(i, err)
                if warn_on_errors:
                    warn(file_err.msg)
                else:
                    raise file_err

    return parse_records

def HeadedRecordsParser(fields_spec=None, header_rename=None,
                        warn_on_errors=None):
    header_rename = dict(header_rename or {})

    def parse_headed_records(tuples_iter):
        tuples_iter = iter(tuples_iter)
        header = list(islice(tuples_iter, 1))[0]
        header = [header_rename.get(name) or name for name in header]
        spec_dict = dict(fields_spec or [])
        new_fields_spec = [(name, spec_dict.get(name, str)) for name in header]
        parser = RecordsParser(RecParser(new_fields_spec), warn_on_errors)
        for rec in parser(tuples_iter):
            yield rec

    return parse_headed_records

def RecParser(fields_spec, required=None, tail_spec=None):
    required = required or len(fields_spec)

    rec_fields = [name for name, rec_type in fields_spec]

    if tail_spec:
        tail_rec_size = len(tail_spec)
        tail_parser = RecParser(tail_spec)
        rec_fields.append('tail')

    Rec = namedtuple('Rec', rec_fields)

    def parse(fields):
        if len(fields) < required:
            raise RecParseError(len(fields), required, len(fields_spec))

        args = []

        # fill required and existing args
        for field_value, spec in zip(fields, fields_spec):
            try:
                args.append(spec[1](field_value))
            except (ValueError, TypeError), err:
                raise RecParseConvError(spec[0], field_value, err)

        # fill default values for non-required args
        args.extend( [None] * (len(fields_spec) - len(fields)) )

        # fill tail
        if tail_spec and len(fields) > len(fields_spec):
            tail_iter = ChunkIter(fields[len(fields_spec):], tail_rec_size)
            args.append( [tail_parser(tail_rec) for tail_rec in tail_iter] )

        return Rec(*args)

    return parse

def SimpleRecParser(first_conv, tail_conv=None):
    def parse(fields):
        tail = [ tail_conv(value) for value in fields[1:] ]
        return first_conv(fields[0]), tail
    return parse

class CondRecParser(object):

    def __init__(self):
        self.parsers = {}

    def add(self, first_field, parser):
        self.parsers[first_field] = parser

    def __call__(self, fields):
        return self.parsers[fields[0]]( fields )

## Fields

def strtime(format):
    def strtime(item):
        return int( time.mktime(time.strptime(item, format)) )
    return strtime

def strlist(item_type, separator, strip_sep=False):
    if isinstance(item_type, basestring):
        raise Exception("'strlist' usage: strlist(item_type, separator)")
    def converter(item):
        if strip_sep:
            item = item.strip(separator)
        if item:
            return [ item_type(o) for o in item.split(separator) ]
        else:
            return []
    return converter

def strarray(array_type, item_type, separator, strip_sep=False):
    if not isinstance(array_type, basestring):
        raise Exception("'strarray' usage: strarray(array_type, item_type, separator)")
    if isinstance(item_type, basestring):
        raise Exception("'strarray' usage: strarray(array_type, item_type, separator)")
    def converter(item):
        if strip_sep:
            item = item.strip(separator)
        if item:
            return array(array_type, [ item_type(o) for o in item.split(separator) ])
        else:
            return array(array_type)
    return converter

def subrec(rec_parser, separator='\t'):
    def subrec(item):
        return rec_parser(item.split(separator))
    return subrec

## Errors

class BaseRecParseError(Exception):
    pass

class RecParseError(BaseRecParseError):
    def __init__(self, found, expected_min, expected_max):
        self.found = found
        self.expected_min = expected_min
        self.expected_max = expected_max
        self.msg = 'Record has %s field(s), expected %s-%s' % (
            self.found, self.expected_min, self.expected_max
        )
        BaseRecParseError.__init__(self, self.msg)

class RecParseConvError(BaseRecParseError):
    def __init__(self, field_name, field_value, error=None):
        self.field_name = field_name
        self.field_value = field_value
        self.msg = 'Failed to convert field %r (value %r): %r' % (
            self.field_name, self.field_value, error
        )
        BaseRecParseError.__init__(self, self.msg)

class FileParseError(Exception):
    def __init__(self, line_no, rec_error):
        self.msg = ("Line %d: " % (line_no + 1,)) + rec_error.msg
        Exception.__init__(self, self.msg)

