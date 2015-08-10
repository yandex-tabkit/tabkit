# coding: utf-8

import os, sys
import _ast

from tabkit.miniast import parse, dump
from tabkit.datasrc import DataDesc, DataField, copy_field_order
from tabkit.awk_expr import *
from tabkit.awk_types import infer_type

OP_MAP = {
    _ast.Add      : lambda args: RowExprOp('+', args),
    _ast.Sub      : lambda args: RowExprOp('-', args),
    _ast.Mult     : lambda args: RowExprOp('*', args),
    _ast.Div      : lambda args: RowExprOp('/', args),
    _ast.Pow      : lambda args: RowExprOp('^', args),
    _ast.Mod      : lambda args: RowExprOp('%', args),
    _ast.FloorDiv : lambda args: RowExprFunc('int', [RowExprOp('/', args)]),
    _ast.BitAnd   : lambda args: RowExprFunc('and', args),
    _ast.BitOr    : lambda args: RowExprFunc('or', args),
    _ast.RShift   : lambda args: RowExprFunc('rshift', args),
    _ast.LShift   : lambda args: RowExprFunc('lshift', args),
    _ast.Invert   : lambda args: RowExprFunc('compl', args),

    _ast.And      : lambda args: RowExprOp('&&', args),
    _ast.Or       : lambda args: RowExprOp('||', args),
    _ast.Not      : lambda args: RowExprFunc('!', args),
    _ast.USub     : lambda args: RowExprFunc('-', args),

    _ast.Eq      : lambda args: RowExprOp('==', args),
    _ast.NotEq   : lambda args: RowExprOp('!=', args),
    _ast.Gt      : lambda args: RowExprOp('>', args),
    _ast.Lt      : lambda args: RowExprOp('<', args),
    _ast.GtE     : lambda args: RowExprOp('>=', args),
    _ast.LtE     : lambda args: RowExprOp('<=', args),
}

EXT_FUNC_REQ = set()
EXT_FUNC_SRC = {
    'crc32' : '''function crc32(str)
{
    #LC_ALL=C must be set
    if (__src32_init!=1){
        for (__crc32_i=0;__crc32_i<256;__crc32_i++){
            __crc32_ord[sprintf("%c", __crc32_i)] = __crc32_i;
            __crc32 = lshift(__crc32_i,24);
            for (__crc32_j=0;__crc32_j<8;__crc32_j++){
                if (and(__crc32,0x80000000)) __crc32 = and(xor(2*__crc32,0x04C11DB7),0xffffffff)
                else                     __crc32 = and(2*__crc32,0xffffffff)
            }
            __crc32_table[__crc32_i] = __crc32;
        }
        __src32_init = 1;
    }

    __crc32_buf_len = split(str,__crc32_buf,"");
    __crc32 = 0;
    for (__crc32_i = 1; __crc32_i<=__crc32_buf_len; __crc32_i++)
      __crc32 = and(xor(and(lshift(__crc32,8),0xffffffff),\
        __crc32_table[and(and(xor(rshift(__crc32,24),__crc32_ord[__crc32_buf[__crc32_i]]),0xff),0xffffffff)]),0xffffffff);

    while(__crc32_buf_len){
        __crc32=and(xor(and(lshift(__crc32,8),0xffffffff),\
        __crc32_table[and(and(xor(rshift(__crc32,24),and(__crc32_buf_len,0xff)),0xff),0xffffffff)]),0xffffffff);
        __crc32_buf_len=rshift(__crc32_buf_len,8);
    }

    return and(compl(__crc32),0xffffffff)
}''',


    'hash_id_set' : '''function hash_id_set(fname){
# fname - tsv без заголовка
# ключ $0, значение 0
# при первом вызове строит по fname хэш, далее возвращает его id

    if (fname in __hash_id_set)
        return __hash_id_set[fname];

    if(system( "[ -e " fname " ] ")!=0){
        print "Error:", fname, "not found" > "/dev/stderr";
        exit 1;
    }

    __hash_id_set_next_id = (length(__hash_id_set) + 1) "";
    while ((getline __hash_id_set_line < fname) > 0)
        __hash_id_set_tables[(__hash_id_set_next_id "\t" __hash_id_set_line)] = 0;
    close(fname);

    __hash_id_set[fname] = __hash_id_set_next_id;
    return __hash_id_set_next_id;
}''',


    'hash_id_map' : '''function hash_id_map(fname){
# fname - tsv без заголовка
# ключ - $1, значение - $2
# при первом вызове строит по fname хэш, далее возвращает его id

    if (fname in __hash_id_map)
        return __hash_id_map[fname];

    if(system( "[ -e " fname " ] ")!=0){
        print "Error:", fname, "not found" > "/dev/stderr";
        exit 1;
    }

    __hash_id_map_next_id = (length(__hash_id_map) + 1) "";
    while ((getline __hash_id_map_line < fname) > 0){
        split(__hash_id_map_line, __hash_id_map_sline, "\t")
        __hash_id_map_tables[(__hash_id_map_next_id "\t" __hash_id_map_sline[1])] = __hash_id_map_sline[2]
    }
    close(fname);

    __hash_id_map[fname] = __hash_id_map_next_id;
    return __hash_id_map_next_id;
}''',


    'is_in_file' : '''
function is_in_file(fname, key){
    return ( (hash_id_set(fname) "\t" key) in __hash_id_set_tables );
}''',


    'map_from_file' : '''function map_from_file(fname, key, def){
    __map_from_file_key = hash_id_map(fname) "\t" key;
    if (__map_from_file_key in __hash_id_map_tables)
        return __hash_id_map_tables[__map_from_file_key];
    return def;
}
''',


    'uniq' : '''
function uniq(delim, expr){
    delete __uniq_items;
    delete __uniq_heap;
    split(expr, __uniq_items, delim);
    for (__uniq_item in __uniq_items) __uniq_heap[__uniq_items[__uniq_item]] = 0;
    __uniq_nitems = asorti(__uniq_heap);
    __uniq_result = "";
    for (__uniq_i=1; __uniq_i<=__uniq_nitems; __uniq_i++)
            __uniq_result = (__uniq_result=="")?(__uniq_heap[__uniq_i]):(__uniq_result delim __uniq_heap[__uniq_i]);
    return __uniq_result;
}
'''
}

def func_mapper(ctx):
    """
    Используя staticmethod перекладываем  ответственность
    за сообщения об ошибочных вызовах функций на питон

    >>> func_mapper(None).join()
    Traceback (most recent call last):
    ...
    TypeError: join() takes at least 1 argument (0 given)
    >>> func_mapper(None).join(a=1)
    Traceback (most recent call last):
    ...
    TypeError: join() got an unexpected keyword argument 'a'
    """
    def _get_var(prefix, expr):
        if isinstance(expr, RowExprField):
                var = expr
        else:
            varname = ctx.get_name(prefix, expr.tostr())
            if not ctx.has_var(varname):
                ctx.set_var(varname, RowExprAssign(varname, expr))
            var = RowExprVar(ctx, varname)
        return var

    def _associative_bin_op_tree(func):
        def associative_op_tree_decorator(*exprs):
            if not exprs:
                raise Exception('%s on empty args' % (func.__name__,))
            if len(exprs)==1:
                return _get_var('_'+func.__name__, exprs[0])
            else:
                l_expr = associative_op_tree_decorator(*exprs[:len(exprs)/2])
                r_expr = associative_op_tree_decorator(*exprs[len(exprs)/2:])
                return func(l_expr, r_expr)
        return associative_op_tree_decorator

    class FuncMapper(object):
        @staticmethod
        def domain(url):
            return RowExprFunc(
                func = 'gensub',
                args = [
                    RowExprConst("^https?://([^/?:#]+).*$"),
                    RowExprConst("\\\\1"),
                    RowExprConst(""),
                    url,
                ],
            )

        @staticmethod
        def netlocator(url):
            return RowExprFunc(
                func = 'gensub',
                args = [
                    RowExprConst("^https?://([^/?#]+).*$"),
                    RowExprConst("\\\\1"),
                    RowExprConst(""),
                    url,
                ],
            )

        @staticmethod
        def join(delim, *strs):
            values = []
            for s in strs:
                if values:
                    values.append(delim)
                values.append(s)
            return RowExprOp('', values)


        @staticmethod
        @_associative_bin_op_tree
        def min(l, r):
            return RowExprIf(RowExprOp('<', [l, r]), l, r)


        @staticmethod
        @_associative_bin_op_tree
        def max(l, r):
            return RowExprIf(RowExprOp('>', [l, r]), l, r)


        @staticmethod
        def _unjoin(delim, expr):
            splitcnt_varname = ctx.get_name('_spcnt', (expr.tostr(), delim.tostr()))
            splitted_varname = ctx.get_name('_split', (expr.tostr(), delim.tostr()))
            if not ctx.has_var(splitcnt_varname):
                ctx.set_var(
                    splitcnt_varname,
                    RowExprAssign(
                        splitcnt_varname,
                        RowExprFunc('split', [
                            expr,
                            RowExprBuiltinVar(splitted_varname),
                            delim,
                        ]),
                    ),
                )
            return (
                RowExprSideEffectVar(splitted_varname, RowExprVar(ctx, splitcnt_varname)),
                RowExprVar(ctx, splitcnt_varname),
            )

        @staticmethod
        def unjoin_count(delim, expr):
            vals, cnt = FuncMapper._unjoin(delim, expr)
            return cnt

        @staticmethod
        def unjoin(delim, expr, idx):
            vals, cnt = FuncMapper._unjoin(delim, expr)
            return RowExprSubscript(vals, RowExprOp('+', [idx, RowExprConst(1)]))


        @staticmethod
        def abs(expr):
            var = _get_var('_abs', expr)
            return RowExprIf(
                RowExprOp('<', [var, RowExprConst(0)]),
                RowExprFunc('-', [var]),
                var,
            )

        @staticmethod
        def shell(cmd):
            varname = ctx.get_name('_sh', cmd.tostr())
            if not ctx.has_var(varname):
                ctx.set_var(
                    varname,
                    RowExprOp(' ', [
                        cmd,
                        RowExprBuiltinVar('|'),
                        RowExprBuiltinVar('getline'),
                        RowExprBuiltinVar(varname),
                    ])
                )
            return RowExprSideEffectVar(varname, RowExprVar(ctx, varname))

        @staticmethod
        def crc32(expr):
            EXT_FUNC_REQ.add('crc32')
            return RowExprFunc(
                func = 'crc32',
                args = [
                    _get_var('_abs', expr),
                ],
            )

        @staticmethod
        def uniq(delim, expr):
            EXT_FUNC_REQ.add('uniq')
            return RowExprFunc(
                func = 'uniq',
                args = [
                    delim,
                    _get_var('_uniq', expr),
                ],
            )


        @staticmethod
        def map_from_file(fname_expr, key_expr, default_expr):
            # turn check off. usefull for mapreduce
            #if isinstance(fname_expr, RowExprConst) and fname_expr.type == "str" and not os.path.exists(fname_expr.const):
            #    raise Exception('map_from_file: %s not found' % fname_expr.const)

            EXT_FUNC_REQ.add('hash_id_map')
            EXT_FUNC_REQ.add('map_from_file')

            return RowExprFunc(
                func = 'map_from_file',
                args = [
                    _get_var('_map_from_file', fname_expr),
                    _get_var('_map_from_file', key_expr),
                    _get_var('_map_from_file', default_expr),
                ],
            )


        @staticmethod
        def is_in_file(fname_expr, key_expr):
            # turn check off. usefull for mapreduce
            #if isinstance(fname_expr, RowExprConst) and fname_expr.type == "str" and not os.path.exists(fname_expr.const):
            #    raise Exception('map_from_file: %s not found' % fname_expr.const)

            EXT_FUNC_REQ.add('hash_id_set')
            EXT_FUNC_REQ.add('is_in_file')

            return RowExprFunc(
                func = 'is_in_file',
                args = [
                    _get_var('_is_in_file', fname_expr),
                    _get_var('_is_in_file', key_expr),
                ],
            )



        @staticmethod
        def strptime(format, timestr):
            if not isinstance(format, RowExprConst) or format.type != "str":
                raise Exception("'format' argument to strptime must be string constant")
            i = 1
            format_chars = iter(format.const)
            format_tokens = []
            format_parts = {}
            for char in format_chars:
                if char != '%':
                    format_tokens.append(char)
                else:
                    fmt = next(format_chars)
                    if fmt == 'Y':
                        format_tokens.append('(....)')
                        format_parts['Y'] = '\\\\' + str(i)
                        i += 1
                    elif fmt in 'mdHMS':
                        format_tokens.append('(..)')
                        format_parts[fmt] = '\\\\' + str(i)
                        i += 1
                    else:
                        raise Exception('Unrecognized format specifier %r' % ('%' + fmt,))
            format_re = "".join(format_tokens)
            format_replace = " ".join([
                format_parts.get('Y', '1970'),
                format_parts.get('m', '01'),
                format_parts.get('d', '01'),
                format_parts.get('H', '00'),
                format_parts.get('M', '00'),
                format_parts.get('S', '00'),
            ])
            return RowExprFunc(
                'mktime', [
                    RowExprFunc(
                        'gensub', [
                            RowExprConst("^" + format_re + ".*$"),
                            RowExprConst(format_replace),
                            RowExprConst(""),
                            timestr,
                        ]
                    )
                ]
            )

        @staticmethod
        def strip(expr):
            return RowExprFunc('gensub', [
                RowExprConst('^[[:space:]]+|[[:space:]]+$'),
                RowExprConst(''),
                RowExprConst('G'),
                _get_var('_strip', expr)
            ])

    return FuncMapper

def add_blocks(block1, block2):
    if isinstance(block1, AwkBlock):
        block1 = block1.lines
    elif isinstance(block1, AwkHeadBlock):
        block1 = [block1]
    if isinstance(block2, AwkBlock):
        block2 = block2.lines
    elif isinstance(block2, AwkHeadBlock):
        block2 = [block2]
    return AwkBlock(block1 + block2)

class AwkBlock(object):
    def __init__(self, lines=None):
        self.lines = lines or []
    def __nonzero__(self):
        return bool(self.lines)
    def append(self, line):
        self.lines.append(line)
    def extend(self, lines):
        self.lines.extend(lines)
    def __add__(self, block):
        return add_blocks(self, block)
    def __radd__(self, block):
        return add_blocks(block, self)
    def tostr(self, ident=0, newline='', level=0):
        strs = []
        for line in self.lines:
            if isinstance(line, AwkBlock):
                strs.append(
                    ' '*ident*level + '{' + newline
                    + line.tostr(ident, newline, level+1) + newline
                    + ' '*ident*level + '}'
                )
            elif isinstance(line, AwkHeadBlock):
                strs.append(
                    line.tostr(ident, newline, level)
                )
            else:
                if line:
                    line_str = ' '*ident*level + line
                    if not line_str.endswith(';'):
                        line_str += ';'
                    strs.append(line_str)
        return newline.join(strs)

class AwkHeadBlock(object):
    def __init__(self, header_str, block):
        self.header_str = header_str
        self.block = block
    def __add__(self, block):
        return add_blocks(self, block)
    def __radd__(self, block):
        return add_blocks(block, self)
    def tostr(self, ident=0, newline='', level=0):
        return (
            ' '*ident*level + self.header_str + newline
            + AwkBlock([self.block]).tostr(ident, newline, level)
        )

class AwkScript(object):
    """
    >>> awk = AwkScript(
    ...     begin = AwkBlock(['a=0']),
    ...     end = AwkBlock(['xx=0']),
    ...     main = AwkBlock([
    ...         'a=1',
    ...         AwkBlock(['b=2', 'c=3', 'd=4; e=5']),
    ...         'print',
    ...     ]),
    ... )
    >>> print awk.tostr(ident=0, newline='')
    BEGIN{a=0;}{a=1;{b=2;c=3;d=4; e=5;}print;}END{xx=0;}
    >>> print awk.tostr(ident=4, newline='\\n')
    BEGIN{
        a=0;
    }
    {
        a=1;
        {
            b=2;
            c=3;
            d=4; e=5;
        }
        print;
    }
    END{
        xx=0;
    }
    <BLANKLINE>
    """
    def __init__(self, main, begin=None, end=None, awk=None):
        self.awk = awk or 'awk'
        self.main = main
        self.begin = begin or AwkBlock([])
        self.end = end or AwkBlock([])
    def tostr(self, ident=0, newline=''):
        awk_str = '\n'.join(EXT_FUNC_SRC[func_name] for func_name in EXT_FUNC_REQ)
        if self.begin.lines:
            awk_str += 'BEGIN' + AwkBlock([self.begin]).tostr(ident, newline, 0) + newline
        awk_str += AwkBlock([self.main]).tostr(ident, newline, 0) + newline
        if self.end.lines:
            awk_str += 'END' + AwkBlock([self.end]).tostr(ident, newline, 0) + newline
        return awk_str
    def cmd_line(self, awk_exec=None, args=""):
        return "LC_ALL=C %s %s -F $'\\t' '%s'" % (awk_exec or self.awk, args, self.tostr(),)

def parse_expr(ctx, tree, subparser=None):
    subparser = subparser or parse_expr

    if isinstance(tree, _ast.Expr):
        return subparser(ctx, tree.value)
    elif isinstance(tree, _ast.Name):
        if ctx.has_field(tree.id):
            return RowExprField(ctx, tree.id)
        if ctx.has_var(tree.id):
            return RowExprVar(ctx, tree.id)
        elif tree.id in ['NR', 'NF', 'FILENAME', 'RSTART', 'RLENGTH']:
            return RowExprBuiltinVar(tree.id)
        else:
            raise Exception('Variable %r not found' % (tree.id,))
    elif isinstance(tree, _ast.Tuple):
        return RowExprOp('', [subparser(ctx, el) for el in tree.elts])
    elif isinstance(tree, _ast.Subscript):
        if not (
            isinstance(tree.slice, _ast.Index)
            and isinstance(tree.slice.value, (_ast.Str, _ast.Num))
        ):
            raise Exception('Bad subscript')
        return RowExprSubscript(
            subparser(ctx, tree.value),
            subparser(ctx, tree.slice.value),
        )
    elif isinstance(tree, _ast.Call):
        if tree.starargs or tree.kwargs:
            raise Exception("* and ** are not supported in function calls")
        parsed_args = list(subparser(ctx, arg) for arg in tree.args)
        parsed_kwargs = dict((kw.arg, subparser(ctx, kw.value)) for kw in tree.keywords)
        mapper = func_mapper(ctx)
        if hasattr(mapper, tree.func.id):
            return getattr(mapper, tree.func.id)(*parsed_args, **parsed_kwargs)
        else:
            if parsed_kwargs:
                raise Exception("Function %r does not accept keyword arguments" % (tree.func.id,))
            return RowExprFunc(tree.func.id, parsed_args)
    elif isinstance(tree, _ast.Num):
        return RowExprConst(tree.n)
    elif isinstance(tree, _ast.Str):
        return RowExprConst(tree.s)
    elif isinstance(tree, _ast.BinOp):
        return OP_MAP[type(tree.op)]([subparser(ctx, tree.left), subparser(ctx, tree.right)])
    elif isinstance(tree, _ast.BoolOp):
        return OP_MAP[type(tree.op)]([subparser(ctx, val) for val in tree.values])
    elif isinstance(tree, _ast.UnaryOp):
        return OP_MAP[type(tree.op)]([subparser(ctx, tree.operand)])
    elif isinstance(tree, _ast.Compare):
        assert len(tree.ops) == 1
        if isinstance(tree.ops[0], _ast.In):
            assert len(tree.comparators) == 1
            args = tree.comparators[0].elts
            return RowExprOp(
                '||',
                [RowExprOp('==', [subparser(ctx, tree.left), subparser(ctx, arg)]) for arg in args],
            )
        elif isinstance(tree.ops[0], _ast.NotIn):
            assert len(tree.comparators) == 1
            args = tree.comparators[0].elts
            return RowExprOp(
                '&&',
                [RowExprOp('!=', [subparser(ctx, tree.left), subparser(ctx, arg)]) for arg in args],
            )
        else:
            return OP_MAP[type(tree.ops[0])](
                [subparser(ctx, val) for val in [tree.left] + tree.comparators]
            )
    elif isinstance(tree, _ast.IfExp):
        return RowExprIf(
            subparser(ctx, tree.test),
            subparser(ctx, tree.body),
            subparser(ctx, tree.orelse),
        )
    elif isinstance(tree, _ast.Assign):
        raise Exception('Assignments are not allowed here %r' % (dump(tree),))
    else:
        raise Exception('Unrecognized node: {0}'.format(dump(tree)))

def parse_assign_expr(ctx, tree, subparser):
    if isinstance(tree, _ast.Assign):
        assert len(tree.targets) == 1 and isinstance(tree.targets[0], _ast.Name)
        return RowExprAssign(tree.targets[0].id, subparser(ctx, tree.value))
    elif isinstance(tree, _ast.Expr):
        if isinstance(tree.value, _ast.Name):
            return RowExprAssign(tree.value.id, subparser(ctx, tree))
        else:
            raise Exception("Please assign expression to a variable")
    else:
        raise Exception("Please assign expression to a variable")

def parse_rowexpr(ctx, tree):
    return parse_assign_expr(ctx, tree, parse_expr)

def get_assignments_for(ctx, exprs, already_assigned=None):
    already_assigned = already_assigned or set()
    varnames = set(var.name for expr in exprs for var in expr.find(RowExprVar, {}))
    assigns = []
    for name, assign_expr in ctx.itervars():
        if not name.startswith('__') and name in varnames and name not in already_assigned:
            assigns.append(assign_expr)
    new_already_assigned = set(already_assigned)
    new_already_assigned.update(varnames)
    return assigns, new_already_assigned

def awk_filter_map(data_desc, filter_strs, map_strs):
    """
    >>> from tabkit.header import parse_header
    >>> awk, desc = awk_filter_map(
    ...     parse_header('# d p e s c m'),
    ...     ['e==157 and (s>100 or s in [15,30,45])'],
    ...     ['ctr=c/s', 'cpm=ctr*m']
    ... )
    >>> print desc
    DataDesc([DataField('ctr', 'any'), DataField('cpm', 'any')])
    >>> print awk.cmd_line()
    LC_ALL=C awk  -F $'\\t' 'BEGIN{OFS="\\t";}{if((($3 == 157) && (($4 > 100) || (($4 == 15) || ($4 == 30) || ($4 == 45))))){ctr = ($5 / $4);print(ctr,(ctr * $6));}}'
    >>> awk, desc = awk_filter_map(parse_header('# a b'), [], ['__all__'])
    >>> print desc
    DataDesc([DataField('a', 'any'), DataField('b', 'any')])
    """
    ctx = ExprContext(data_desc)

    # parse map
    for map_expr_str in map_strs:
        for node in parse(map_expr_str).body:
            if isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Name) and node.value.id == '__all__':
                for field in data_desc.fields:
                    ctx.set_var(field.name, RowExprAssign(field.name, RowExprField(ctx, field.name)))
            elif isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Name) and node.value.id == '__rest__':
                for field in data_desc.fields:
                    if not ctx.has_var(field.name):
                        ctx.set_var(field.name, RowExprAssign(field.name, RowExprField(ctx, field.name)))
            else:
                expr = parse_rowexpr(ctx, node)
                ctx.set_var(expr.target, expr)

    # parse filter
    nodes = [node for filter_str in filter_strs for node in parse(filter_str).body]
    filter_expr = None
    if len(nodes) == 0:
        pass
    elif len(nodes) == 1:
        filter_expr = parse_expr(ctx, nodes[0])
    else:
        filter_expr = RowExprOp('&&', [parse_expr(ctx, node) for node in nodes])

    awk_cmd, output_desc = awk_filter_map_from_context(ctx, filter_expr, data_desc.order)
    if output_desc:
        output_desc.meta = data_desc.meta
    return awk_cmd, output_desc or data_desc

def awk_filter_map_from_context(ctx, filter_expr=None, order=None, already_assigned=None):
    order = order or []
    already_assigned = already_assigned or set()

    if filter_expr is None:
        assign_before_if = []
    else:
        assign_before_if, already_assigned = get_assignments_for(
            ctx, [filter_expr], already_assigned
        )
    assign_after_if, already_assigned = get_assignments_for(
        ctx,
        [assign_expr for name, assign_expr in ctx.itervars()],
        already_assigned,
    )

    output_exprs = []
    output_field_names = []
    kept_fields = {}
    for name, assign_expr in ctx.itervars():
        if not name.startswith('_'):
            output_field_names.append(name)
            if name in already_assigned:
                output_exprs.append(RowExprVar(ctx, name))
            else:
                assert isinstance(assign_expr, RowExprAssign)
                output_exprs.append(assign_expr.value)
            refered_field = ctx.var_refers_to_field(name)
            if refered_field:
                if refered_field not in kept_fields or kept_fields[refered_field] != refered_field:
                    kept_fields[refered_field] = name

    if output_exprs:
        awk_cmd = AwkBlock(["print(" + ','.join(expr.tostr() for expr in output_exprs) + ")"])
    else:
        awk_cmd = AwkBlock(["print"])
    if assign_after_if:
        awk_cmd = AwkBlock(['; '.join(expr.tostr() for expr in assign_after_if)]) + awk_cmd
    if filter_expr:
        awk_cmd = AwkBlock([AwkHeadBlock('if(%s)' % (filter_expr.tostr(),), awk_cmd)])
    if assign_before_if:
        awk_cmd = AwkBlock(['; '.join(expr.tostr() for expr in assign_before_if)]) + awk_cmd
    awk_cmd = AwkScript(awk_cmd, begin=AwkBlock(['OFS="\\t"']))

    # construct data_desc
    output_fields = []
    new_order = []
    for name, expr in zip(output_field_names, output_exprs):
        output_fields.append(DataField(name, infer_type(expr)))
    for field in order:
        if field.name not in kept_fields:
            break
        new_order.append(copy_field_order(
            field,
            name = kept_fields[field.name],
        ))

    if output_fields:
        return awk_cmd, DataDesc(output_fields, new_order)
    else:
        return awk_cmd, None

def _test(): # pylint: disable-msg=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
