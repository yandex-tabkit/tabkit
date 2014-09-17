import os, re

from tabkit.datasrc import DataField, DataFieldOrder, DataDesc, SortType, merge_meta
from tabkit.datasrc import header_order_field, field_order_from_header

def field_split(fields_str):
    return [key for key in re.split(r'[;,\s]+', fields_str.strip()) if key]

def parse_header_order(zone_fields):
    for order_field_str in zone_fields:
        order_field = order_field_str.strip().split(':')
        yield field_order_from_header(order_field[0], order_field[1:])
        
def parse_meta(meta):
    '''
    >>> parse_meta("spam:spam")
    {'spam': 'spam'}
    >>> parse_meta("'spam':'spam'")
    {'spam': 'spam'}
    >>> parse_meta("'spam': 'spam'")
    {'spam': 'spam'}
    >>> parse_meta("{'spam': 'spam'}")
    {'spam': 'spam'}
    >>> parse_meta(" {spam:spam}")
    {'spam': 'spam'}
    '''
    import yaml
    if '"' not in meta: # http://pyyaml.org/wiki/YAMLColonInFlowContext
        meta = ",".join(pair.replace(":", ": ", 1) for pair in meta.split(","))
    if meta.lstrip()[0] != "{":
        meta = "{" + meta + "}"
    return yaml.load(meta)    
    
def split_header(header):
    """
    >>> header = "# shows:int clicks:int ctr:float rel url #ORDER: url:asc, ctr:desc:num #SIZE: 12312 #META: # #ANYTHING"
    >>> list(split_header(header))
    [' shows:int clicks:int ctr:float rel url ', 'ORDER: url:asc, ctr:desc:num ', 'SIZE: 12312 ', 'META: # #ANYTHING']
    """
    if not header.startswith('#'):
        raise Exception('Bad header %r' % (header,))
        
    start = 1
    while True:
        pos = header.find('#', start)
        if pos < 0:
            yield header[start:]
            break
        substr = header[start:pos]
        if substr.startswith('META'):
            yield header[start:]
            break
        yield substr
        start = pos + 1            

def parse_header(header):
    """
    >>> header = "# shows:int clicks:int ctr:float rel url #ORDER: url:asc, ctr:desc:num"
    >>> parse_header(header) #doctest: +NORMALIZE_WHITESPACE
    DataDesc([DataField('shows', 'int'),
            DataField('clicks', 'int'),
            DataField('ctr', 'float'),
            DataField('rel', 'any'),
            DataField('url', 'any')],
        DataOrder([DataFieldOrder('url', sort_type='str', desc=False),
            DataFieldOrder('ctr', sort_type='num', desc=True)]))
    """
    data_fields = []
    data_order = []
    data_size = None
    meta = {}

    zones = split_header(header)
    fields_str = next(zones)
    fields = field_split(fields_str)
    for field in fields:
        field_parts = field.split(':')
        field_name = field_parts[0]
        field_type = 'any'
        if len(field_parts) == 2:
            field_type = field_parts[1]
        elif len(field_parts) > 2:
            raise Exception('Invalid field %r' % (field,))
        data_fields.append(DataField(field_name, field_type))

    for zone in zones:
        zone_name, zone_data = zone.strip().split(None, 1)
        if zone_name == 'ORDER:':
            data_order = list(parse_header_order(field_split(zone_data)))
        elif zone_name == 'SIZE:':
            data_size = int(zone_data)
        elif zone_name == 'META:':
            meta = parse_meta(zone_data)
        else:
            raise Exception('Bad header, invalid zone %r' % (zone_name,))

    return DataDesc(data_fields, data_order, data_size, meta)
        
def pass_meta(meta, opts):
    result = {}
    
    if opts.pass_meta:
        result = meta
    elif opts.pass_meta_keys:
        keys = set(key.strip() for key in opts.pass_meta_keys.split(','))
        result = dict((key, value) for key, value in meta.iteritems() if key in keys)
        
    if opts.meta:
        return merge_meta(result, parse_meta(opts.meta))
    else:
        return result

def make_header(data_desc):
    r"""
    >>> desc = DataDesc(
    ...     [DataField('shows', 'int'), DataField('url', 'any')],
    ...     [
    ...         DataFieldOrder('url', desc=True),
    ...         DataFieldOrder('shows', sort_type=SortType.NUMERIC),
    ...     ],
    ...     meta=dict(
    ...         foo=['array', 'a very long line which is likely to be broken, also with commas, commas, commas'],
    ...         bar=['array']
    ...     )
    ... )
    >>> make_header(desc)
    "# shows:int\turl #ORDER: url:desc\tshows:num #META: {bar: [array], foo: [array, 'a very long line which is likely to be broken, also with commas, commas, commas']}\n"
    """
    fields = []
    for field in data_desc.fields:
        if field.type == 'any':
            fields.append(field.name)
        else:
            fields.append(field.name + ':' + field.type)
    order = []
    for order_field in data_desc.order:
        order.append(header_order_field(order_field))
    header = '# ' + '\t'.join(fields)
    if order:
        header += ' #ORDER: ' + '\t'.join(order)
    if data_desc.size != None:
        header += ' #SIZE: ' + str(data_desc.size)
    if data_desc.meta:
        import yaml
        s = ' #META: ' + yaml.dump(data_desc.meta, width=float('Inf'), default_flow_style=True).rstrip()
        assert("\n" not in s and "\r" not in s)
        header += s
    header += "\n"
    return header

def read_fd_header(fd):
    header = ''
    while header[-1:] != '\n':
        ch = os.read(fd, 1)
        if ch == '':
            break
        header += ch
    return header

def read_file_header(fname):
    fobj = open(fname)
    try:
        header = fobj.readline()
    finally:
        fobj.close()
    return header

def _test(): # pylint: disable=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
