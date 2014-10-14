# -*- coding: utf-8 -*-
from itertools import groupby
from unittest import TestCase, main as unittest_main

from tabkit import regroup
from tabkit.datasrc import DataFieldOrder
from tabkit.header import parse_header


class FunctionalTest(TestCase):
    def run_regroup_main(self, argv, header, table):
        import tempfile
        from cStringIO import StringIO

        output_stream = StringIO()

        with tempfile.NamedTemporaryFile() as input_stream:
            input_stream.write(header.rstrip('\n') + '\n')
            input_stream.writelines('\t'.join(line) + '\n' for line in table)
            input_stream.seek(0)
            argv.append(input_stream.name)
            regroup.main(argv, output_stream)

        output_stream.seek(0)
        result_header = next(output_stream)
        result_list = [line.rstrip('\n').split('\t') for line in output_stream]
        return (result_header, result_list)

    def check_is_grouped(self, keys, data, group_count=None):
        seen_keys = set()
        for keys, _ in self.group_by_keys(data, keys):
            self.assertNotIn(keys, seen_keys)
            seen_keys.add(keys)
        if group_count is not None:
            self.assertEquals(group_count, len(seen_keys))

    @staticmethod
    def group_by_keys(data, keys):
        return groupby(data, lambda line: tuple(line[i] for i in keys))

    def test_one_key(self):
        _, result = self.run_regroup_main(
            ["-k", "A"],
            "# A:str B:str",
            [
                ["foo", "123"],
                ["bar", "456"],
                ["foo", "789"],
                ["baz", "abc"],
                ["foo", "def"],
            ]
        )

        self.check_is_grouped([0], result, group_count=3)

        for keys, group in self.group_by_keys(result, [0]):
            group = sorted(group)
            if keys[0] == "foo":
                self.assertEquals([
                    ["foo", "123"],
                    ["foo", "789"],
                    ["foo", "def"],
                ], group)
            elif keys[0] == "bar":
                self.assertEquals([
                    ["bar", "456"],
                ], group)
            else:
                self.assertEquals(keys[0], "baz")
                self.assertEquals([
                    ["baz", "abc"],
                ], group)

    def test_many_keys(self):
        _, result = self.run_regroup_main(
            ["-k", "A;C;E"],
            "# A B C D E",
            [
                ["foo", "123", "hello", "xxx", "world"],
                ["bar", "456", "apple", "xxx", "pine"],
                ["foo", "789", "orange", "yyy", "lemon"],
                ["baz", "abc", "tomato", "yyy", "cucumber"],
                ["foo", "def", "hello", "zzz", "world"],
            ]
        )

        self.check_is_grouped([0, 2, 4], result, group_count=4)

        for keys, group in self.group_by_keys(result, [0, 2, 4]):
            group = sorted(group)
            if keys == ("foo", "hello", "world"):
                self.assertEquals(group, [
                    ["foo", "123", "hello", "xxx", "world"],
                    ["foo", "def", "hello", "zzz", "world"],
                ])
            elif keys == ("bar", "apple", "pine"):
                self.assertEquals(group, [
                    ["bar", "456", "apple", "xxx", "pine"],
                ])
            elif keys == ("foo", "orange", "lemon"):
                self.assertEquals(group, [
                    ["foo", "789", "orange", "yyy", "lemon"],
                ])
            else:
                self.assertEquals(keys, ("baz", "tomato", "cucumber"))
                self.assertEquals(group, [
                    ["baz", "abc", "tomato", "yyy", "cucumber"],
                ])

    def test_max_size(self):
        import sys

        def source(bytes_):
            # Вся строка должна занимать 1 килобайт
            to_fit_size = (
                1024 - sys.getsizeof("xxx") - sys.getsizeof("123456")
                - sys.getsizeof((None, None))
            )
            value = lambda i: "_" * to_fit_size + "{0:06d}".format(i)
            for i in xrange(0, bytes_ // 1024, 4):
                yield ["bar", value(i)]
                yield ["bar", value(i + 1)]
                yield ["foo", value(i + 2)]
                yield ["bar", value(i + 3)]

        # Первый проход - должен пропустить 75 килобайт записей
        _, result = self.run_regroup_main(
            ["-k", "A", "--max-size", "50K"],
            "# A B",
            source(75 * 1024),
        )

        self.check_is_grouped([0], result, group_count=2)

        # Не должно быть повторяющихся линий
        existing_lines = set()
        duplicates = set()
        for line in result:
            line = tuple(line)
            if line in existing_lines:
                duplicates.add(repr(line).replace('_', ''))
            existing_lines.add(line)

        self.assertEquals(set(), duplicates)

        # Первая группа должна быть "bar", т.к. записей с этим ключом было больше.
        self.assertEquals(result[0][0], "bar")
        self.assertEquals(result[-1][0], "foo")

        # Второй проход - должен упасть при попытке пропустить 300 килобайт
        # (до пробоя - 50 килобайт, далее - нужно ещё как минимум 50 * 4, т.к.
        # "пробойного" ключа в 3 раза больше).
        with self.assertRaisesRegexp(Exception, "Memory overlimit."):
            self.run_regroup_main(
                ["-k", "A", "--max-size", "50K"],
                "# A B",
                source(300 * 1024),
            )

    def test_lru(self):
        import sys

        def source(bytes_):
            # Вся строка должна занимать 1 килобайт
            to_fit_size = (
                1024 - sys.getsizeof("xxx") - sys.getsizeof("123456")
                - sys.getsizeof((None, None))
            )
            value = lambda i: "_" * to_fit_size + "{0:06d}".format(i)
            for i in xrange(0, bytes_ // 1024, 4):
                yield ["bar", value(i)]
                yield ["bar", value(i + 1)]
                yield ["foo", value(i + 2)]
                yield ["bar", value(i + 3)]

        # Первый проход - должен пропустить 25 Кб записей, полностью сгруппированных
        _, result = self.run_regroup_main(
            ["-k", "A", "--lru", "--max-size", "50K"],
            "# A B",
            source(25 * 1024),
        )
        self.check_is_grouped([0], result, group_count=2)

        # Первая группа должна быть "bar", т.к. "foo" была последней записью.
        self.assertEquals(result[0][0], "bar")
        self.assertEquals(result[-1][0], "foo")

        # Второй проход - не должен упасть, но вывод уже не будет полностью сгруппирован.
        _, result = self.run_regroup_main(
            ["-k", "A", "--lru", "--max-size", "50K"],
            "# A B",
            source(300 * 1024),
        )
        self.assertEquals(len(result), 300)

        # Не должно быть повторяющихся линий
        existing_lines = set()
        duplicates = set()
        for line in result:
            line = tuple(line)
            if line in existing_lines:
                duplicates.add(repr(line).replace('_', ''))
            existing_lines.add(line)

        self.assertEquals(set(), duplicates)

        self.assertEquals(sum(l[0] == "bar" for l in result), 300 / 4 * 3)
        self.assertEquals(sum(l[0] == "foo" for l in result), 300 / 4)

    def test_sort_one(self):
        _, result = self.run_regroup_main(
            ["-k", "A,C", "--sort-group", "B:num:desc"],
            "# A:str B:int C:str D:str E:str",
            [
                ["foo", "123", "hello", "xxx", "world"],
                ["bar", "456", "apple", "xxx", "pine"],
                ["foo", "789", "hello", "yyy", "lemon"],
                ["baz", "1", "tomato", "yyy", "cucumber"],
                ["foo", "2", "hello", "zzz", "apple"],
            ],
        )

        self.check_is_grouped([0, 2], result, group_count=3)

        for keys, group in self.group_by_keys(result, [0, 2]):
            group = list(group)
            if keys == ("foo", "hello"):
                self.assertEquals([
                    ["foo", "789", "hello", "yyy", "lemon"],
                    ["foo", "123", "hello", "xxx", "world"],
                    ["foo", "2", "hello", "zzz", "apple"],
                ], group)
            elif keys == ("bar", "apple"):
                self.assertEquals([
                    ["bar", "456", "apple", "xxx", "pine"],
                ], group)
            else:
                self.assertEquals(("baz", "tomato"), keys)
                self.assertEquals([
                    ["baz", "1", "tomato", "yyy", "cucumber"],
                ], group)

    def test_sort_many(self):
        _, result = self.run_regroup_main(
            ["-k", "A,C", "--sort-group", "E,B:num"],
            "# A:str B:int C:str D:str E:str",
            [
                ["foo", "123", "hello", "xxx", "lemon"],
                ["bar", "456", "apple", "xxx", "pine"],
                ["foo", "789", "hello", "yyy", "apple"],
                ["baz", "1", "tomato", "yyy", "cucumber"],
                ["foo", "2", "hello", "zzz", "lemon"],
            ],
        )

        self.check_is_grouped([0, 2], result, group_count=3)

        for keys, group in self.group_by_keys(result, [0, 2]):
            group = list(group)
            if keys == ("foo", "hello"):
                self.assertEquals([
                    ["foo", "789", "hello", "yyy", "apple"],
                    ["foo", "2", "hello", "zzz", "lemon"],
                    ["foo", "123", "hello", "xxx", "lemon"],
                ], group)
            elif keys == ("bar", "apple"):
                self.assertEquals([
                    ["bar", "456", "apple", "xxx", "pine"],
                ], group)
            else:
                self.assertEquals(("baz", "tomato"), keys)
                self.assertEquals([
                    ["baz", "1", "tomato", "yyy", "cucumber"],
                ], group)

    def test_already_grouped(self):
        _, result = self.run_regroup_main(
            ["-k", "B", "-K", "A"],
            "# A B",
            [
                ["f*", "foo"],
                ["f*", "foobar"],
                ["f*", "foo"],
                ["f*", "foobaz"],
                ["b*", "bar"],
                ["b*", "baz"],
                ["b*", "bar"],
            ]
        )

        # Первоначальная группировка не нарушена
        self.assertEquals(["f*"] * 4 + ["b*"] * 3, [row[0] for row in result])

        # В пределах каждой исходной группы всё сгруппировано по новому ключу:
        self.check_is_grouped([1], result[:4], group_count=3)
        self.check_is_grouped([1], result[4:], group_count=2)


if __name__ == '__main__':
    unittest_main()
