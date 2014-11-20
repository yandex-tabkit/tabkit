# -*- coding: utf-8 -*-
import re
import sys
from collections import defaultdict
from itertools import ifilter, groupby
from operator import itemgetter
from optparse import OptionParser, Option, OptionValueError

from tabkit._odict import OrderedDict
from tabkit.datasrc import SortType, DataFieldOrder
from tabkit.header import make_header, field_split
from tabkit.utils import FilesList, OptUtils


def hr_float_to_float(value):
    m = re.match("""
    (
    [0-9]+   # целая часть
    (?:[.][0-9]+)?  # необязательная дробная часть
    )
    ([KMG]?)  # кило-, мега-, гига-
    """, value, re.VERBOSE)
    if not m:
        raise ValueError(value)

    value = float(m.groups()[0])

    # 0 для числа без порядка, 1 для кило, 2 для мега, ...
    value_exponent_idx = 'KMG'.find(m.groups()[1]) + 1
    value *= (2 ** (10 * value_exponent_idx))
    return value


def check_hr_float(option, opt, value):
    try:
        return hr_float_to_float(value)
    except ValueError:
        raise OptionValueError("option {0!r}: invalid number {1!r}".format(opt, value))


class HRFloatOption(Option):
    """
    Человекочитаемый float. Например, 1.23, 1.23k, 100M, 1G
    """
    TYPES = ("float", )
    TYPE_CHECKER = {
        "float": check_hr_float
    }

    def __init__(self, *args, **kwargs):
        kwargs['type'] = 'float'
        Option.__init__(self, *args, **kwargs)  # Option is old-style class


class FieldsOption(Option):
    """
    tabkit-поля через запятую
    """
    TYPES = ("string", )
    TYPE_CHECKER = {
        "string": lambda option, opt, value: field_split(value)
    }


def check_sort_key(option, opt, value):
    result = []

    for value in field_split(value):
        value = value.strip().split(":")
        field, sort_opts = value[0], value[1:]
        sort_type = desc = None

        for sort_opt in sort_opts:
            if sort_opt == "desc":
                desc = True
            elif SortType.is_valid(sort_opt):
                sort_type = sort_opt
            else:
                raise OptionValueError("Unknown sort option: {0!r}".format(sort_opt))

        result.append(DataFieldOrder(field, sort_type=sort_type, desc=desc))

    return result


class SortKeyOption(Option):
    TYPES = ("string", )
    TYPE_CHECKER = {
        "string": check_sort_key
    }


def main(argv=None, output_stream=sys.stdout):
    if argv is None:
        argv = sys.argv[1:]

    optparser = OptionParser(usage="Usage: %prog [options] <file1> <file2> ...")
    optparser.add_option(FieldsOption(
        '-k', '--keys', dest='keys', default=(),
        help=u"Ключи, по которым следует сгруппировать данные."))
    optparser.add_option(FieldsOption(
        '-K', '--grouped-keys', dest='grouped_keys', default=(),
        help=u"Ключи, по которым данные уже сгруппированы."))
    optparser.add_option(HRFloatOption(
        '-S', '--max-size', dest='max_size', default=2 ** 30,  # 1 Гб
        help=(u"Максимальный размер занимаемой памяти. Если установлен как 0,"
              u" то отключить ограничение памяти.")))
    optparser.add_option(
        '-L', '--lru', action="store_true", dest="lru",
        help=(u"Режим LRU-кеша. При переполнении буфера не выходит с ошибкой,"
              u" а выводит не обновлявшуюся дольше всех группу. В этом режиме"
              u" не гарантируется полная сгруппированность результата."))
    optparser.add_option(SortKeyOption(
        '-s', '--sort-group', dest="sort_group", default=[],
        help=(u"Сортировать все строки в пределах одной группы по указанному полю/полям."
              u" Можно указать несколько ключей через точку с запятой."
              u" Формат: FIELDNAME[:desc][:num][:general][:human][:month]")))

    OptUtils.add_header(optparser)
    OptUtils.add_no_out_header(optparser)
    OptUtils.add_pytrace(optparser)

    opts, args = optparser.parse_args(argv)

    files = FilesList(args, header=opts.header)
    output_desc = files.concat_desc()

    if not opts.no_out_header:
        output_stream.write(make_header(output_desc))
        output_stream.flush()

    data = files.readlines()
    data = ifilter(None, (
        map(intern, s.rstrip('\r\n').split('\t'))
        for s in data))

    regrouped = regroup(
        input_data=data,
        data_desc=output_desc,
        grouped_keys=opts.grouped_keys,
        keys=opts.keys,
        max_size=None if opts.max_size <= 0 else opts.max_size,
        lru=opts.lru,
        sort_group=opts.sort_group)
    output_stream.writelines('\t'.join(l) + '\n' for l in regrouped)


def regroup(input_data, data_desc, grouped_keys, keys, max_size, lru, sort_group):
    grouped_keys_idx = []
    keys_idx = []

    for src, dst in ([grouped_keys, grouped_keys_idx], [keys, keys_idx]):
        for key in src:
            try:
                dst.append(data_desc.field_index(key))
            except KeyError:
                raise Exception("Field {0!r} does not exist".format(key))

    grouped_keys_getter = lambda data: tuple(data[i] for i in grouped_keys_idx)
    keys_getter = lambda data: tuple(data[i] for i in keys_idx)
    sort_comparator = make_sort_comparator(sort_group, data_desc)

    for _, input_data_group in groupby(input_data, grouped_keys_getter):
        for l in handle_group(
                input_data_group, keys_getter, max_size=max_size, lru=lru,
                sort_comparator=sort_comparator):
            yield l


def make_sort_comparator(sort_group, data_desc):
    # sort_group: [DataFieldOrder(...), ...]
    if not sort_group:
        return None

    sort_type_comparators = [
        {
            None: GenericSortComparator,
            SortType.STRING: GenericSortComparator,
            SortType.NUMERIC: NumericSortComparator,
            SortType.GENERAL_NUMERIC: NumericSortComparator,
            SortType.HUMAN_NUMERIC: HumanNumericSortComparator,
            SortType.MONTH: NotImplemented,
        },
        {
            None: ReverseGenericSortComparator,
            SortType.STRING: ReverseGenericSortComparator,
            SortType.NUMERIC: ReverseNumericSortComparator,
            SortType.GENERAL_NUMERIC: ReverseNumericSortComparator,
            SortType.HUMAN_NUMERIC: ReverseHumanNumericSortComparator,
            SortType.MONTH: NotImplemented,
        },
    ]

    comparators = [
        (sort_type_comparators[f.desc][f.sort_type], data_desc.field_index(f.name))
        for f in sort_group
    ]

    return lambda line: tuple(c(line[i]) for c, i in comparators)


class GenericSortComparator(object):
    """
    Используется для двоичного поиска.
    """
    __slots__ = ['val']

    def __init__(self, val):
        self.val = self.make(val)

    make = staticmethod(lambda x: x)

    def __cmp__(self, other):
        return cmp(self.val, other.val)


class ReverseSortComparatorMixin(object):
    def __cmp__(self, other):
        return -cmp(self.val, other.val)


class ReverseGenericSortComparator(
        ReverseSortComparatorMixin, GenericSortComparator):
    pass


class NumericSortComparator(GenericSortComparator):
    @staticmethod
    def make(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value


class ReverseNumericSortComparator(
        ReverseSortComparatorMixin, NumericSortComparator):
    pass


class HumanNumericSortComparator(GenericSortComparator):
    @staticmethod
    def make(value):
        try:
            return hr_float_to_float(value)
        except (TypeError, ValueError):
            return value


class ReverseHumanNumericSortComparator(
        ReverseSortComparatorMixin, HumanNumericSortComparator):
    pass


def tuple_size(t):
    return sys.getsizeof(t) + sum(sys.getsizeof(x) for x in t)


def handle_group(input_data_group, keys_getter, max_size=None, lru=False, sort_comparator=None):
    with_max_size = bool(max_size)
    with_sort_group = sort_comparator is not None
    lru = bool(lru)

    handler_cls = possible_handlers[(with_max_size, with_sort_group, lru)]
    kwargs = {}
    if with_max_size:
        kwargs["max_size"] = max_size
    if with_sort_group:
        kwargs["sort_comparator"] = sort_comparator

    return handler_cls(input_data_group, keys_getter, **kwargs)


class GroupHandler(object):
    def __init__(self, input_data_group, keys_getter):
        self.input_data_group = input_data_group
        self.keys_getter = keys_getter

    @staticmethod
    def make_data_holder():
        return {}

    def __iter__(self):
        data_holder = self.make_data_holder()  # {key: [line, ...], ...}
        keys_getter = self.keys_getter

        for line in self.input_data_group:
            keys = keys_getter(line)

            yield_lines, skip = self.handle_keys(keys, line, data_holder)
            for tmp_line in yield_lines:
                yield tmp_line

            if skip:
                continue

            key_data_holder = data_holder.get(keys, None)
            if key_data_holder is None:
                key_data_holder = []
                data_holder[keys] = key_data_holder

            self.put_line(key_data_holder, line)

        rest_keys = self.get_rest_keys(data_holder)
        for keys in rest_keys:
            for line in data_holder.pop(keys):
                yield line

    def handle_keys(self, keys, line, data_holder):
        return ((), False)

    put_line = staticmethod(list.append)

    def get_rest_keys(self, dct):
        return dct.keys()


class SortMixin(object):
    def __init__(self, input_data_grouper, keys_getter, **kwargs):
        sort_comparator = kwargs.pop('sort_comparator')
        super(SortMixin, self).__init__(input_data_grouper, keys_getter, **kwargs)
        self.sort_comparator = sort_comparator

    def put_line(self, arr, elem):
        # bisect.insort не подходит, т.к. не поддерживает функцию ключа
        lo, hi = 0, len(arr)
        elem_key = self.sort_comparator(elem)
        while lo < hi:
            mid = (lo + hi) // 2
            mid_key = self.sort_comparator(arr[mid])
            if elem_key < mid_key:
                hi = mid
            else:
                lo = mid + 1
        arr.insert(lo, elem)

    def get_rest_keys(self, dct):
        keys = dct.keys()
        keys.sort()
        return keys


class SortGroupHandler(SortMixin, GroupHandler):
    pass


class SizedMixin(object):
    def __init__(self, input_data_grouper, keys_getter, **kwargs):
        max_size = kwargs.pop('max_size')
        super(SizedMixin, self).__init__(input_data_grouper, keys_getter, **kwargs)
        self.max_size = max_size


class FixedGroupHandler(SizedMixin, GroupHandler):
    def __init__(self, *args, **kwargs):
        super(FixedGroupHandler, self).__init__(*args, **kwargs)
        self.total_size = 0
        self.data_sizes = defaultdict(int)
        self.breakout_keys = None

    def handle_keys(self, keys, line, data_holder):
        line_size = tuple_size(line)
        self.total_size += line_size

        result, skip = [], False

        if self.total_size >= self.max_size:
            if self.breakout_keys is not None:
                raise Exception("Memory overlimit.")

            self.breakout_keys, breakout_size = max(
                self.data_sizes.iteritems(), key=itemgetter(1))
            del self.data_sizes

            self.total_size -= breakout_size
            result = data_holder.pop(self.breakout_keys)
        elif self.breakout_keys is None:
            self.data_sizes[keys] += line_size

        if self.breakout_keys == keys:
            skip = True
            result.append(line)
            self.total_size -= line_size

        return (result, skip)


class SortFixedGroupHandler(SortMixin, FixedGroupHandler):
    pass


class LRUDict(OrderedDict):
    def get(self, key, default=None):
        data = super(LRUDict, self).get(key, default)
        if data is not default:
            del self[key]
            self[key] = data
        return data

    def __getitem__(self, key):
        data = super(LRUDict, self).__getitem__(key)
        del self[key]
        self[key] = data
        return data

    # python 2.6 does not knows that this is iterable without such adaptors.
    def __iter__(self):
        return super(LRUDict, self).__iter__()

    def __reversed__(self):
        return super(LRUDict, self).__reversed__()


class LRUMixin(object):
    @staticmethod
    def make_data_holder():
        return LRUDict()

    def get_rest_keys(self, dct):
        return list(reversed(dct))


class LRUGroupHandler(LRUMixin, GroupHandler):
    pass


class SizedLRUGroupHandler(LRUMixin, SizedMixin, GroupHandler):
    def __init__(self, *args, **kwargs):
        super(SizedLRUGroupHandler, self).__init__(*args, **kwargs)
        self.total_size = 0

    def handle_keys(self, keys, line, data_holder):
        line_size = tuple_size(line)
        self.total_size += line_size

        result, skip = [], False

        if self.total_size >= self.max_size:
            oldest_keys = next(reversed(data_holder))
            old_lines = data_holder.pop(oldest_keys)
            self.total_size -= sum(tuple_size(l) for l in old_lines)
            result += old_lines

        return (result, skip)


class SortLRUGroupHandler(SortMixin, LRUGroupHandler):
    pass


class SizedSortLRUGroupHandler(SortMixin, SizedLRUGroupHandler):
    pass


# {(with_max_size, with_sort, lru): cls}
possible_handlers = {
    (False, False, False): GroupHandler,
    (False, False, True): LRUGroupHandler,
    (False, True, False): SortGroupHandler,
    (False, True, True): SortLRUGroupHandler,
    (True, False, False): FixedGroupHandler,
    (True, False, True): SizedLRUGroupHandler,
    (True, True, False): SortFixedGroupHandler,
    (True, True, True): SizedSortLRUGroupHandler,
}
