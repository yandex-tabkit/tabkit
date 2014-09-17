import os
from itertools import izip
from collections import namedtuple

TYPES = set([
    'float',
    'int',
    'str',
    'bool',
    'any',
])

class DataField(namedtuple('DataField', 'name type')):
    def __repr__(self):
        return "%s(%r, %r)" % (
            self.__class__.__name__, self.name, self.type # pylint: disable-msg=E1101
        )

class SortType(object):
    STRING = 'str'
    NUMERIC = 'num'
    GENERAL_NUMERIC = 'general'
    HUMAN_NUMERIC = 'human'
    MONTH = 'month'

    @classmethod
    def is_valid(self, sort_type):
        return sort_type in (
            self.STRING,
            self.NUMERIC,
            self.GENERAL_NUMERIC,
            self.HUMAN_NUMERIC,
            self.MONTH,
        )

class DataFieldOrder(object):

    def __init__(self, name, sort_type=None, desc=None):
        self.name = name
        self.desc = desc
        self.sort_type = sort_type
        if self.desc == None:
            self.desc = False
        if self.sort_type == None:
            self.sort_type = SortType.STRING
        if not SortType.is_valid(self.sort_type):
            raise Exception('Unknown sort type %r' % (self.sort_type,))

    def __eq__(self, other):
        return (
            self.name == other.name
            and self.sort_type == other.sort_type
            and self.desc == other.desc
        )

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return "%s(%r, sort_type=%r, desc=%r)" % (
            self.__class__.__name__, self.name, self.sort_type, self.desc
        )

def copy_field_order(field_order, name=None):
    return DataFieldOrder(
        name = name or field_order.name,
        sort_type = field_order.sort_type,
        desc = field_order.desc,
    )

def unix_sort_flags(field_order):
    sort_flags = ''

    if field_order.sort_type == SortType.NUMERIC:
        sort_flags += 'n'
    elif field_order.sort_type == SortType.GENERAL_NUMERIC:
        sort_flags += 'g'
    elif field_order.sort_type == SortType.HUMAN_NUMERIC:
        sort_flags += 'h'
    elif field_order.sort_type == SortType.MONTH:
        sort_flags += 'M'

    if field_order.desc:
        sort_flags += 'r'

    return sort_flags

def header_order_field(order_field):
    order_str = order_field.name
    if order_field.desc:
        order_str += ':desc'
    if order_field.sort_type == SortType.NUMERIC:
        order_str += ':num'
    if order_field.sort_type == SortType.GENERAL_NUMERIC:
        order_str += ':general'
    if order_field.sort_type == SortType.HUMAN_NUMERIC:
        order_str += ':human'
    if order_field.sort_type == SortType.MONTH:
        order_str += ':month'
    return order_str

def field_order_from_header(name, modifiers):
    desc = None
    sort_type = None
    for modifier in modifiers:
        if SortType.is_valid(modifier):
            if sort_type != None:
                raise Exception('Conflicting sort types %r and %r' % (sort_type, modifier))
            sort_type = modifier
        elif modifier in ('asc', 'desc'):
            if desc != None:
                order_field_str = name + ':' + ':'.join(modifiers)
                raise Exception('Ambiguous order direction in %r' % (order_field_str,))
            if modifier == 'asc':
                desc = False
            else:
                desc = True
        else:
            raise Exception('Unknown order modifier %r' % (modifier,))
    return DataFieldOrder(name, sort_type, desc)

class DataOrder(object):
    def __init__(self, data_order):
        self.data_order = data_order

    def fields_are_ordered(self, field_names):
        for field_name, order in zip(field_names, self.data_order):
            if field_name != order.name:
                return False
        return True

    def is_ordered_by(self, data_order):
        if isinstance(data_order, DataOrder):
            data_order = data_order.data_order
        data_order = list(data_order)
        if len(self.data_order) < len(data_order):
            return False
        for required, actual in zip(data_order, self.data_order):
            if required != actual:
                return False
        return True

    def __nonzero__(self):
        return bool(self.data_order)

    def __iter__(self):
        return iter(self.data_order)

    def __repr__(self):
        return "%s(%r)" % (
            self.__class__.__name__, self.data_order
        )

class DataDesc(object):
    def __init__(self, fields, order=None, size=None, meta=None):
        if meta:
            assert(isinstance(meta, dict))
        self.meta = meta or {}
        self.size = size
        self.fields = fields
        if isinstance(order, DataOrder):
            self.order = order
        else:
            self.order = DataOrder(order or [])
        self.field_names = dict((field.name, idx) for idx, field in enumerate(self.fields))
        if len(self.fields) != len(self.field_names):
            names = list(field.name for field in self.fields)
            dups = list(name for name in self.field_names.keys() if names.count(name) > 1)
            raise Exception("Conflicting field names %r in %r" % (dups, self.fields,))
        for order_field in self.order:
            if order_field.name not in self.field_names:
                raise Exception('Unknown ordering field name %r' % (order_field.name,))

    def copy(self, fields=None, order=None, size=None, meta=None):
        return DataDesc(
            fields = fields or self.fields,
            order = order or self.order,
            size = size or self.size,
            meta = meta or self.meta,
        )

    def __getitem__(self, idx):
        assert isinstance(idx, slice)
        fields = self.fields[idx]
        field_names = list(field.name for field in fields)
        order = list(self.order)
        for order_field in order:
            if order_field.name not in field_names:
                break
            order.append(order_field)
        return DataDesc(fields, order, self.size)

    def __add__(self, desc):
        return paste_data_desc(self, desc)

    def __radd__(self, desc):
        return paste_data_desc(desc, self)

    def field_index(self, name):
        return self.field_names[name]

    def get_field(self, name):
        return self.fields[self.field_names[name]]

    def has_field(self, name):
        return name in self.field_names

    def __repr__(self):
        if self.order and self.size == None:
            return "%s(%r, %r)" % (
                self.__class__.__name__, self.fields, self.order
            )
        if not self.order and self.size == None:
            return "%s(%r)" % (
                self.__class__.__name__, self.fields
            )
        return "%s(%r, %r, %r)" % (
            self.__class__.__name__, self.fields, self.order, self.size
        )

def make_data_field(field):
    if isinstance(field, DataField):
        return field
    if isinstance(field, tuple) and isinstance(field[0], str) and field[1] in TYPES:
        return DataField(*field)
    raise Exception("Can't convert %r to DataField" % (field,))

def make_data_desc(desc):
    if isinstance(desc, tuple) and isinstance(desc[0], str) and desc[1] in TYPES:
        return DataDesc([DataField(*desc)])
    if isinstance(desc, list):
        return DataDesc(list(make_data_field(item) for item in desc))
    if isinstance(desc, DataDesc):
        return desc
    try:
        return DataDesc([make_data_field(desc)])
    except Exception, err:
        pass
    raise Exception("Can't convert %r to DataDesc" % (desc,))

def paste_data_desc(d1, d2):
    r"""
    >>> from tabkit.header import parse_header, make_header

    >>> parse_header('# a c:int')[:1] + ('b', 'str')
    DataDesc([DataField('a', 'any'), DataField('b', 'str')])

    >>> parse_header('# a b:int') + ('b', 'str')
    Traceback (most recent call last):
        ...
    Exception: Conflicting fields ['b'] in DataDesc([DataField('a', 'any'), DataField('b', 'int')]) and DataDesc([DataField('b', 'str')])

    >>> parse_header('# a #ORDER: a #SIZE: 2') + [('b', 'str')]
    DataDesc([DataField('a', 'any'), DataField('b', 'str')], DataOrder([DataFieldOrder('a', sort_type='str', desc=False)]))

    >>> ('b','str') + parse_header('# a #ORDER: a #SIZE: 2')
    DataDesc([DataField('b', 'str'), DataField('a', 'any')], DataOrder([DataFieldOrder('a', sort_type='str', desc=False)]))

    >>> make_header(parse_header("# a #META: foo:bar") + parse_header("# b #META: spam:spam"))
    '# a\tb #META: {foo: bar, spam: spam}\n'
    """
    d1 = make_data_desc(d1)
    d2 = make_data_desc(d2)
    isect = list(set(field.name for field in d1.fields).intersection(
        field.name for field in d2.fields
    ))
    if isect:
        raise Exception("Conflicting fields %r in %r and %r" % (isect, d1, d2))
    if d1.size == None or d2.size == None:
        size = None
    else:
        size = d1.size + d2.size
    return DataDesc(
        fields = d1.fields + d2.fields,
        order = d1.order or d2.order,
        size = size,
        meta = merge_meta(d1.meta, d2.meta)
    )

def merge_data_desc(desc1, desc2):
    return DataDesc(
        fields = merge_data_fields(desc1.fields, desc2.fields),
        order = merge_data_order(desc1.order, desc2.order),
        meta = merge_meta(desc1.meta, desc2.meta),
    )

def merge_data_fields(fields1, fields2):
    if len(fields1) != len(fields2):
        raise Exception('Incompatible data fields: %r and %r' % (
            fields1, fields2,
        ))

    fields = []
    for field1, field2 in zip(fields1, fields2):
        if field1.name != field2.name:
            raise Exception('Incompatible data fields: %r and %r' % (
                fields1, fields2,
            ))
        if field1.type == field2.type:
            fields.append(DataField(field1.name, field1.type))
        elif field1.type == 'any':
            fields.append(DataField(field1.name, field2.type))
        elif field2.type == 'any':
            fields.append(DataField(field1.name, field1.type))
        else:
            raise Exception('Incompatible data fields: %r and %r' % (
                fields1, fields2,
            ))

    return fields

def merge_data_order(order1, order2):
    order = []
    for ord1, ord2 in zip(order1, order2):
        if ord1 == ord2:
            order.append(copy_field_order(ord1))
        else:
            break
    return DataOrder(order)

def merge_meta(a, b):
    result = a.copy()
    result.update(b)
    return result

def rename_fields(desc, renamings):
    new_fields = []
    for field in desc.fields:
        if field.name in renamings:
            new_fields.append(DataField(renamings[field.name], field.type))
        else:
            new_fields.append(DataField(field.name, field.type))

    new_order = []
    for field in desc.order:
        if field.name in renamings:
            new_order.append(copy_field_order(
                field, name=renamings[field.name],
            ))
        else:
            new_order.append(copy_field_order(
                field, name=field.name,
            ))

    return DataDesc(new_fields, new_order)

def convertible(from_type, to_type):
    if from_type == 'any' or to_type == 'any':
        return True
    if to_type == from_type:
        return True
    if to_type == 'str':
        return True
    if to_type == 'float' and from_type in ('int', 'bool'):
        return True
    if to_type == 'int' and from_type == 'bool':
        return True
    return False

def _test(): # pylint: disable=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
