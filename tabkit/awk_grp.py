import _ast

from tabkit.miniast import parse
from tabkit.utils import partial
from tabkit.datasrc import DataDesc

from tabkit.awk import parse_expr, parse_assign_expr
from tabkit.awk import awk_filter_map_from_context, match_node
from tabkit.awk import ExprContext, RowExprOp, RowExprVar, RowExprConst, RowExprField
from tabkit.awk import AwkBlock, AwkScript, AwkHeadBlock
from tabkit.awk_expr import _GrpExprFunc, RowExprAssign, Namer

class GrpExprFuncMaker(object):
    def __init__(self, prefix, namer):
        self.namer = namer
        self.prefix = prefix
    def __call__(self, func, init, update, args, end=None):
        return _GrpExprFunc(
            name = self.namer.get_name(
                self.prefix,
                (init, update) + tuple(arg.tostr() for arg in args)
            ),
            func = func,
            init = init,
            update = update,
            args = args,
            end = end,
        )

def grp_ifmax(maker, args):
    if len(args) != 2:
        raise Exception("'ifmax' function takes 2 arguments")
    return maker(
        func = "ifmax",
        init = '%(var)s_cmp = -10^1000000; %(var)s_cmp = -10^1000000;',
        update = (
            '__tmp__=%(rowexpr0)s; '
            'if(__tmp__>%(var)s_cmp)'
            '{%(var)s_cmp=__tmp__; %(var)s=%(rowexpr1)s};'
        ),
        args = args,
    )

def grp_ifmin(maker, args):
    if len(args) != 2:
        raise Exception("'ifmin' function takes 2 arguments")
    return maker(
        func = "ifmin",
        init = '%(var)s_cmp = 10^1000000; %(var)s_cmp = 10^1000000;',
        update = (
            '__tmp__=%(rowexpr0)s; '
            'if(__tmp__<%(var)s_cmp)'
            '{%(var)s_cmp=__tmp__; %(var)s=%(rowexpr1)s};'
        ),
        args = args,
    )

def grp_max(maker, args):
    if len(args) != 1:
        raise Exception("'max' function takes 1 argument")
    return maker(
        func = "max",
        init = '%(var)s_init = 0',
        update = '__tmp__=%(rowexpr0)s;'
        'if (%(var)s_init==0) {%(var)s_init=1; %(var)s=__tmp__;}'
        'if(__tmp__>%(var)s){%(var)s=__tmp__};',
        args = args,
    )

def grp_min(maker, args):
    if len(args) != 1:
        raise Exception("'min' function takes 1 argument")

    return maker(
        func = "min",
        init = '%(var)s_init = 0',
        update = '__tmp__=%(rowexpr0)s;'
        'if (%(var)s_init==0) {%(var)s_init=1; %(var)s=__tmp__;}'
        'if(__tmp__<%(var)s){%(var)s=__tmp__};',
        args = args,
    )

def grp_sum(maker, args):
    if len(args) != 1:
        raise Exception("'sum' function takes 1 argument")
    return maker(func="sum", init='%(var)s = 0;', update='%(var)s += %(rowexpr0)s;', args=args)

def grp_product(maker, args):
    if len(args) != 1:
        raise Exception("'product' function takes 1 argument")
    return maker(func="product", init='%(var)s = 1;', update='%(var)s *= %(rowexpr0)s;', args=args)

def grp_concat(maker, args):
    if len(args) == 1:
        field_name, = args
        delim = RowExprConst(",")
    elif len(args) == 2:
        field_name, delim = args
    else:
        raise Exception("'concat' function takes 2 arguments (field and delimiter)")

    if not isinstance(delim, RowExprConst) or delim.type != "str":
        raise Exception("'delim' arg to 'concat' function should be a const of type 'str'")

    return maker(
        func = "concat",
        init = '%(var)s = "";',
        update = '%(var)s = (%(var)s=="")?(%(rowexpr0)s):(%(var)s"' + delim.const + '"%(rowexpr0)s);',
        args = (field_name,),
    )

def grp_concat_uniq(maker, args):
    if len(args) == 1:
        field_name, = args
        delim = RowExprConst(",")
    elif len(args) == 2:
        field_name, delim = args
    else:
        raise Exception("'concat_uniq' function takes 2 arguments (field and delimiter)")

    if not isinstance(delim, RowExprConst) or delim.type != "str":
        raise Exception("'delim' arg to 'concat_uniq' function should be a const of type 'str'")

    return maker(
        func = "concat_uniq",
        init = '%(var)s = "";',
        update = '%(var)s_heap[%(rowexpr0)s]=""',
        end = '%(var)s_nitems = asorti(%(var)s_heap);'
        'for (%(var)s_i=1; %(var)s_i<=%(var)s_nitems; %(var)s_i++)'
            '%(var)s = (%(var)s=="")?(%(var)s_heap[%(var)s_i]):(%(var)s "' + delim.const + '" %(var)s_heap[%(var)s_i]);'
        'delete %(var)s_heap;',
        args = (field_name,),
    )

def grp_concat_sorted(maker, args):
    if len(args) == 1:
        field_name, = args
        delim = RowExprConst(",")
    elif len(args) == 2:
        field_name, delim = args
    else:
        raise Exception("'concat_sorted' function takes 2 arguments (field and delimiter)")

    if not isinstance(delim, RowExprConst) or delim.type != "str":
        raise Exception("'delim' arg to 'concat_sorted' function should be a const of type 'str'")

    from textwrap import dedent
    return maker(
        func="concat_sorted",
        init='%(var)s = "";',
        update=dedent('''
            %(var)s_heap[%(rowexpr0)s]="";
            if (%(rowexpr0)s in %(var)s_heap_count) {
                %(var)s_heap_count[%(rowexpr0)s]++;
            } else {
                %(var)s_heap_count[%(rowexpr0)s] = 1;
            }
        '''.strip()),
        end=dedent('''
            %(var)s_nitems = asorti(%(var)s_heap);
            for(%(var)s_i=1; %(var)s_i<=%(var)s_nitems; %(var)s_i++) {
                for (%(var)s_j=0; 
                     %(var)s_j<%(var)s_heap_count[%(var)s_heap[%(var)s_i]]; 
                     %(var)s_j++) {
                    if (%(var)s == ""){
                        %(var)s = %(var)s_heap[%(var)s_i];
                    } else {
                        %(var)s = %(var)s "''' + delim.const + '''" %(var)s_heap[%(var)s_i];
                    }
                }
            }
            delete %(var)s_heap;
            delete %(var)s_heap_count
        '''.strip()),
        args=(field_name,),
    )

def grp_chain_concat_uniq(maker, args):
    if len(args) == 1:
        field_name, = args
        delim = RowExprConst(",")
    elif len(args) == 2:
        field_name, delim = args
    else:
        raise Exception("'grp_chain_concat_uniq' function takes 2 arguments (field and delimiter)")

    if not isinstance(delim, RowExprConst) or delim.type != "str":
        raise Exception("'delim' arg to 'grp_chain_concat_uniq' function should be a const of type 'str'")

    return maker(
        func = "concat_uniq",
        init = '%(var)s = "";',
        update = 'split(%(rowexpr0)s, %(var)s_unjoin,"' + delim.const + '");'
        'for (%(var)s_item in %(var)s_unjoin) %(var)s_heap[%(var)s_unjoin[%(var)s_item]]=""',
        end = '%(var)s_nitems = asorti(%(var)s_heap);'
        'for (%(var)s_i=1; %(var)s_i<=%(var)s_nitems; %(var)s_i++)'
            '%(var)s = (%(var)s=="")?(%(var)s_heap[%(var)s_i]):(%(var)s "' + delim.const + '" %(var)s_heap[%(var)s_i]);'
        'delete %(var)s_heap;',
        args = (field_name,),
    )


def grp_concat_sample(maker, args):
    if len(args) == 2:
        field_name, limit = args
        delim = RowExprConst(",")
    elif len(args) == 3:
        field_name, limit, delim = args
    else:
        raise Exception("'grp_concat_sample' function takes 3 arguments (field, limit, delimiter=',')")

    if not isinstance(delim, RowExprConst) or delim.type != "str":
        raise Exception("'delim' arg to 'grp_concat_sample' function should be a const of type 'str'")

    if not isinstance(limit, RowExprConst) or limit.type != "int":
        raise Exception("'limit' arg to 'grp_concat_sample' function should be a const of type 'int'")

    return maker(
        func = "concat_sample",
        init = '%(var)s = ""; %(var)s_cnt=0;',
        update = '''
        if (!(%(rowexpr0)s in %(var)s_heap) && %(var)s_cnt<{0})
        {{
            %(var)s_heap[%(rowexpr0)s]="";
            %(var)s_cnt += 1;
        }}'''.format(limit.const),
        end = '%(var)s_nitems = asorti(%(var)s_heap);'
        'for (%(var)s_i=1; %(var)s_i<=%(var)s_nitems; %(var)s_i++)'
            '%(var)s = (%(var)s=="")?(%(var)s_heap[%(var)s_i]):(%(var)s "' + delim.const + '" %(var)s_heap[%(var)s_i]);'
        'delete %(var)s_heap;',
        args = (field_name,),
    )



def grp_cnt(maker, args):
    if len(args) != 0:
        raise Exception("'cnt' function takes no arguments")
    return maker(func="cnt", init='%(var)s = 0;', update='%(var)s += 1;', args=args)

def grp_avg(maker, args):
    if len(args) != 1:
        raise Exception("'avg' function takes 1 argument")
    return RowExprOp('/', [grp_sum(maker, args), grp_cnt(maker, [])])

def grp_median(maker, args):
    if len(args) != 1:
        raise Exception("'median' function takes 1 argument")
    return maker(
        func = "median",
        init = "delete %(var)s_arr; %(var)s_cnt = 0;",
        update = "%(var)s_arr[%(var)s_cnt] = %(rowexpr0)s; %(var)s_cnt++;",
        args = args,
        end = "__tmp__ = asort(%(var)s_arr) / 2; %(var)s = int(__tmp__) == __tmp__ ? (%(var)s_arr[int(__tmp__)] + %(var)s_arr[int(__tmp__) + 1]) / 2 : %(var)s_arr[int(__tmp__) + 1]"
    )

def grp_variance(maker, args):
    if len(args) != 1:
        raise Exception("'variance' function takes 1 argument")
    return RowExprOp('-', 
        [
            RowExprOp('/', [grp_sum(maker, [RowExprOp('^', [args[0], RowExprConst(2)])]), grp_cnt(maker, [])]),
            RowExprOp('^', [
                RowExprOp('/', [grp_sum(maker, args), grp_cnt(maker, [])]),
                RowExprConst(2)
            ])
        ]
    )

def grp_first(maker, args):
    if len(args) != 1:
        raise Exception("'first' function takes 1 argument")
    return maker(
        func = "first",
        init = '%(var)s = ""; %(var)s_unset = 1;',
        update = 'if(%(var)s_unset) {%(var)s = %(rowexpr0)s; %(var)s_unset = 0;}',
        args = args,
    )

def grp_last(maker, args):
    if len(args) != 1:
        raise Exception("'last' function takes 1 argument")
    return maker(func="last", init='%(var)s = "";', update='%(var)s = %(rowexpr0)s;', args=args)

FUNC_MAP = {
    'ifmin' : grp_ifmin,
    'ifmax' : grp_ifmax,
    'min' : grp_min,
    'max' : grp_max,
    'sum' : grp_sum,
    'product': grp_product,
    'concat' : grp_concat,
    'concat_uniq' : grp_concat_uniq,
    'concat_sorted' : grp_concat_sorted,
    'chain_concat_uniq' : grp_chain_concat_uniq,
    'concat_sample' : grp_concat_sample,
    'cnt' : grp_cnt,
    'avg' : grp_avg,
    'median' : grp_median,
    'var' : grp_variance,
    'first' : grp_first,
    'last' : grp_last,
}

def parse_grpexpr(grp_ctx, tree, row_ctx, maker):
    if isinstance(tree, _ast.Call) and tree.func.id in FUNC_MAP:
        if tree.keywords:
            raise Exception('Keyword arguments are not supported in %r' % (tree.func.id,))
        return FUNC_MAP[tree.func.id](
            maker, list(parse_expr(row_ctx, arg) for arg in tree.args)
        )
    else:
        return parse_expr(grp_ctx, tree, partial(parse_grpexpr, maker=maker, row_ctx=row_ctx))

def parse_assign_grpexpr(grp_ctx, tree, row_ctx, maker):
    return parse_assign_expr(grp_ctx, tree, partial(parse_grpexpr, maker=maker, row_ctx=row_ctx))

def find_grp_funcs(ctx):
    func_dict = {}
    for name, assign_expr in ctx.itervars():
        for node in assign_expr.find(_GrpExprFunc, {}):
            func_dict[node.name] = node
    return func_dict.items()

def awk_grp(data_desc, key_str, grp_expr_tuples, output_only_assigned=True, expose_groups=False):
    namer = Namer()
    acc_maker = GrpExprFuncMaker('__acc_', namer)
    grp_maker = GrpExprFuncMaker('__grp_', namer)
    key_ctx = ExprContext(data_desc, namer)
    row_ctx = ExprContext(data_desc, namer)
    acc_ctx = ExprContext(DataDesc([],[]), namer)
    grp_ctx = ExprContext(DataDesc([],[]), namer)
    out_ctx = ExprContext(DataDesc([],[]), namer)

    # parse key expr
    keys = []
    key_ins_pos = 0
    for node in parse(key_str or '1').body:
        assigned_name = None
        if isinstance(node, _ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], _ast.Name):
                raise Exception('Bad assignment in %r' % (key_str,))
            expr = parse_expr(key_ctx, node.value)
            assigned_name = node.targets[0].id
        else:
            expr = parse_expr(key_ctx, node)
            if output_only_assigned:
                assign = False
            else:
                if isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Name):
                    assigned_name = node.value.id
                else:
                    raise Exception('Please assign expression to a variable in %r' % (key_str,))
        key_name = namer.get_name('__key', expr.tostr())
        key_row_name = namer.get_name('__row_key', expr.tostr())
        if assigned_name:
            out_ctx.set_var(
                key_name,
                RowExprAssign(key_name, expr)
            )
            out_ctx.set_var(
                assigned_name,
                RowExprAssign(assigned_name, RowExprVar(out_ctx, key_name)),
                insert_at = key_ins_pos
            )
            key_ins_pos += 1
            grp_ctx.set_var(
                assigned_name,
                RowExprAssign(assigned_name, RowExprVar(out_ctx, key_name)),
            )
        if isinstance(expr, RowExprField): # force str assuming if node is filed
            expr = RowExprOp('', [expr, RowExprConst("")])
        keys.append((expr, key_name, key_row_name))

    for grp_type, expr_str in grp_expr_tuples:
        for ast_expr in parse(expr_str).body:
            if grp_type == 'acc':
                expr = parse_assign_grpexpr(acc_ctx, ast_expr, row_ctx, acc_maker)
                acc_ctx.set_var(expr.target, expr)
                out_ctx.set_var(expr.target, expr)
            elif grp_type == 'grp':
                expr = parse_assign_grpexpr(grp_ctx, ast_expr, row_ctx, grp_maker)
                grp_ctx.set_var(expr.target, expr)
                out_ctx.set_var(expr.target, expr)
            else:
                raise Exception('Unknown grouping type %r' % (grp_type,))


    # construct awk script
    print_awk, output_desc = awk_filter_map_from_context(
        out_ctx,
        order = data_desc.order,
    )
    if output_desc is None:
        raise Exception('No output fields specified')
    assert not print_awk.end

    init_grps = AwkBlock()
    init_accs = AwkBlock()
    calc_row_keys = AwkBlock()
    keys_changed = []
    update_keys = AwkBlock()
    update_grps = AwkBlock()
    update_accs = AwkBlock()
    end_grps = AwkBlock()

    for expr, name, row_name in keys:
        calc_row_keys.append(row_name + ' = ' + expr.tostr())
        update_keys.append(name + ' = ' + row_name)
        keys_changed.append(name + '!=' + row_name)

    for name, val in find_grp_funcs(grp_ctx):
        init_grps.append(val.init_str())
        update_grps.append(val.update_str())
        end_grps.append(val.end_str())

    for name, val in find_grp_funcs(acc_ctx):
        init_accs.append(val.init_str())
        update_accs.append(val.update_str())
        end_grps.append(val.end_str())

    keys_changed_str = ' || '.join(keys_changed)

    awk = AwkScript(
        begin = (
            print_awk.begin
            + init_grps
            + init_accs
            + AwkBlock(['__print_last = ' + str(int(key_str == None))])
        ),
        end = AwkBlock() if expose_groups else AwkBlock([AwkHeadBlock(
            'if(NR!=0 || __print_last==1)',
            end_grps + print_awk.main
        )]),
        main = (
            calc_row_keys
            + AwkHeadBlock('if(NR==1)', update_keys)
            + AwkHeadBlock('else', AwkBlock([
                AwkHeadBlock('if(' + keys_changed_str + ')',
                    end_grps
                    + (print_awk.main if not expose_groups else AwkBlock())
                    + update_keys
                    + init_grps
                )])
            )
            + update_grps
            + update_accs
            + (print_awk.main if expose_groups else AwkBlock())
        )
    )

    return awk, output_desc

__test__ = dict(
    awk_grp1 = r"""
        >>> from tabkit.header import parse_header
        >>> awk_cmd, output_desc = awk_grp(
        ...     data_desc = parse_header('# d p e s c m'),
        ...     key_str = 'd;p',
        ...     grp_expr_tuples = [
        ...         ('grp', 'ctr=sum(c)/sum(s); cpm=ctr*avg(m)'),
        ...         ('acc', 'cnt=cnt()'),
        ...         ('grp', 'xctr=avg(c/s)'),
        ...     ],
        ... )
        >>> print awk_cmd.tostr(ident=4, newline='\n')
        BEGIN{
            OFS="\t";
            __grp_4 = 0;
            __grp_1 = 0;
            __grp_0 = 0;
            __grp_3 = 0;
            __grp_2 = 0;
            __acc_0 = 0;
            __print_last = 0;
        }
        {
            __row_key0 = ($1  "");
            __row_key1 = ($2  "");
            if(NR==1)
            {
                __key0 = __row_key0;
                __key1 = __row_key1;
            }
            else
            {
                if(__key0!=__row_key0 || __key1!=__row_key1)
                {
                    ctr = (__grp_0 / __grp_1);
                    print(ctr,(ctr * (__grp_2 / __grp_3)),__acc_0,(__grp_4 / __grp_3));
                    __key0 = __row_key0;
                    __key1 = __row_key1;
                    __grp_4 = 0;
                    __grp_1 = 0;
                    __grp_0 = 0;
                    __grp_3 = 0;
                    __grp_2 = 0;
                }
            }
            __grp_4 += ($5 / $4);
            __grp_1 += $4;
            __grp_0 += $5;
            __grp_3 += 1;
            __grp_2 += $6;
            __acc_0 += 1;
        }
        END{
            if(NR!=0 || __print_last==1)
            {
                ctr = (__grp_0 / __grp_1);
                print(ctr,(ctr * (__grp_2 / __grp_3)),__acc_0,(__grp_4 / __grp_3));
            }
        }
        <BLANKLINE>
        """,
    awk_grp2 = r"""
        >>> from tabkit.header import parse_header
        >>> awk_cmd, output_desc = awk_grp(
        ...     data_desc = parse_header('# d p e s c m'),
        ...     key_str = 'grp=int(d)',
        ...     grp_expr_tuples = [
        ...         ('acc', '_ctr=sum(c)/(sum(s)+0.0000001)*100'),
        ...         ('acc', 'm=sprintf("%0.2f",sum(m)/1000000)'),
        ...         ('acc', 'cpm=sprintf("%0.20f",_ctr*m)'),
        ...         ('grp', 'cnt=cnt()'),
        ...         ('grp', 'r=sum(p)+grp'),
        ...     ],
        ... )
        >>> print awk_cmd.tostr(ident=4, newline='\n')
        BEGIN{
            OFS="\t";
            __grp_1 = 0;
            __grp_0 = 0;
            __acc_2 = 0;
            __acc_1 = 0;
            __acc_0 = 0;
            __print_last = 0;
        }
        {
            __row_key0 = int($1);
            if(NR==1)
            {
                __key0 = __row_key0;
            }
            else
            {
                if(__key0!=__row_key0)
                {
                    grp = __key0; _ctr = ((__acc_0 / (__acc_1 + 1e-07)) * 100); m = sprintf("%0.2f", (__acc_2 / 1000000));
                    print(grp,m,sprintf("%0.20f", (_ctr * m)),__grp_0,(__grp_1 + grp));
                    __key0 = __row_key0;
                    __grp_1 = 0;
                    __grp_0 = 0;
                }
            }
            __grp_1 += $2;
            __grp_0 += 1;
            __acc_2 += $6;
            __acc_1 += $4;
            __acc_0 += $5;
        }
        END{
            if(NR!=0 || __print_last==1)
            {
                grp = __key0; _ctr = ((__acc_0 / (__acc_1 + 1e-07)) * 100); m = sprintf("%0.2f", (__acc_2 / 1000000));
                print(grp,m,sprintf("%0.20f", (_ctr * m)),__grp_0,(__grp_1 + grp));
            }
        }
        <BLANKLINE>
        """,
    awk_grp3 = r"""
        >>> from tabkit.header import parse_header
        >>> awk_cmd, output_desc = awk_grp(
        ...     data_desc = parse_header('# d p e s c m'),
        ...     key_str = 'd;p',
        ...     grp_expr_tuples = [
        ...         ('grp', 'median_ctr=median(c/s)'),
        ...         ('grp', 'variance_ctr=var(c/s)'),
        ...     ],
        ... )
        >>> print awk_cmd.tostr(ident=4, newline='\n')
        BEGIN{
            OFS="\t";
            __grp_1 = 0;
            delete __grp_0_arr; __grp_0_cnt = 0;
            __grp_3 = 0;
            __grp_2 = 0;
            __print_last = 0;
        }
        {
            __row_key0 = ($1  "");
            __row_key1 = ($2  "");
            if(NR==1)
            {
                __key0 = __row_key0;
                __key1 = __row_key1;
            }
            else
            {
                if(__key0!=__row_key0 || __key1!=__row_key1)
                {
                    __tmp__ = asort(__grp_0_arr) / 2; __grp_0 = int(__tmp__) == __tmp__ ? (__grp_0_arr[int(__tmp__)] + __grp_0_arr[int(__tmp__) + 1]) / 2 : __grp_0_arr[int(__tmp__) + 1];
                    print(__grp_0,((__grp_1 / __grp_2) - ((__grp_3 / __grp_2) ^ 2)));
                    __key0 = __row_key0;
                    __key1 = __row_key1;
                    __grp_1 = 0;
                    delete __grp_0_arr; __grp_0_cnt = 0;
                    __grp_3 = 0;
                    __grp_2 = 0;
                }
            }
            __grp_1 += (($5 / $4) ^ 2);
            __grp_0_arr[__grp_0_cnt] = ($5 / $4); __grp_0_cnt++;
            __grp_3 += ($5 / $4);
            __grp_2 += 1;
        }
        END{
            if(NR!=0 || __print_last==1)
            {
                __tmp__ = asort(__grp_0_arr) / 2; __grp_0 = int(__tmp__) == __tmp__ ? (__grp_0_arr[int(__tmp__)] + __grp_0_arr[int(__tmp__) + 1]) / 2 : __grp_0_arr[int(__tmp__) + 1];
                print(__grp_0,((__grp_1 / __grp_2) - ((__grp_3 / __grp_2) ^ 2)));
            }
        }
        <BLANKLINE>
        """
)


def _test(): # pylint: disable=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
