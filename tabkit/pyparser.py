from itertools import islice, tee, izip
from tabkit.header import parse_header, parse_header_order
from tabkit.datasrc import DataDesc
from tabkit._fileparser import FileParser, RecParser

TYPE_MAP = {
    'str'  : str,
    'int'  : int,
    'long' : int,
    'float': float,
    'bool' : lambda x: bool(int(x)),
    'any'  : str,
}

class ParsedFile(object):
    def __init__(self, data_desc, recs):
        self.data_desc = data_desc
        self.recs = recs
    def __iter__(self):
        return self.recs
    def next(self):
        return self.recs.next()
    def fields_with_prefix(self, prefix):
        for name, type in self.data_desc.fields:
            if name.startswith(prefix):
                yield name

def parse_file(lines, require_order=None):
    """
    >>> lines = ['# q:str ans:str s:int c:int rel:float\\n', 'url\\tph\\t1000\\t15\\t1.2\\n']
    >>> list(parse_file(lines))
    [Rec(q='url', ans='ph', s=1000, c=15, rel=1.2)]
    """
    lines_iter = iter(lines)
    header = list(islice(lines_iter, 1))
    if len(header) == 1:
        data_desc = parse_header(header[0])
        if require_order:
            if not data_desc.order.is_ordered_by(parse_header_order(require_order)):
                raise Exception('require_order check of {0} failure on {1}.'.format(require_order, data_desc.order))
        field_spec = []
        for field in data_desc.fields:
            field_spec.append((field.name, TYPE_MAP[field.type]))
        parser = FileParser(
            field_separator = '\t',
            rec_parser = RecParser(field_spec),
        )
        return ParsedFile(data_desc, parser(lines_iter))
    else:
        raise Exception("No header")
        
def parse_file_keeplines(lines, require_order=None):
    r"""
    >>> def gen_lines(x):
    ...     yield "# field:int\n"
    ...     for i in range(x):
    ...         yield "%s\n" % (test_field,)
    >>> parsed = parse_file_keeplines(gen_lines(2))
    >>> next(parsed)
    '# field:int\n'
    >>> test_field = 1; next(parsed)
    ('1\n', Rec(field=1))
    >>> test_field = 2; next(parsed)
    ('2\n', Rec(field=2))
    """
    lines_iter, lines_iter_parse = tee(iter(lines), 2)
    try:
        yield next(lines_iter)
    except StopIteration:
        raise Exception("No header")
    for line, rec in izip(lines_iter, parse_file(lines_iter_parse)):
        yield line, rec

def _test(): # pylint: disable=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()

