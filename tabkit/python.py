# coding: utf-8

import ast
from collections import defaultdict
from itertools import count

def make_list_func(expr_str, field_names_dict, filename=None):
    """
    Создает функцию, принимающую на вход один парамерт типа list
    в котором значение поля с именем name находится в листе по индексу
    field_names_dict[name].

    Если field_names_dict не задан, то он создается автоматически.

    Функция возвращает тупл (func, field_names_dict),
    где field_names_dict - это маппинг из имени поля в индекс водного списка.

    >>> func = make_list_func('a+b+3**2', {'a':0, 'b': 1})
    >>> func([1, 2])
    12
    """
    filename = filename or '<generated>'
    return _make_list_func(
        tree = ast.parse(expr_str, filename, 'eval'),
        field_names_dict = field_names_dict,
        filename = filename,
    )

def make_grp_list_func(expr_str, field_names_dict, global_names_dict=None, filename=None):
    """
    Создает группировочную функцию, принимающую на вход итератор по спискам,
    списки такие же как в make_list_func.

    Аргумент field_names_dict ведет себя так же как в make_list_func.
    
    >>> func = make_grp_list_func('1+sum(a)+sum(b**2)', {'a':0, 'b':1})
    >>> func([(10, 1), (20, 2)])
    36
    >>> func([(10, 1), (20, 2)])
    36
    >>> func = make_grp_list_func('b+sum(a)/sum(c)', {'a': 0, 'c': 1}, {'b': 0})
    >>> func([(10, 1), (20, 2), (30, 3)], [1])
    11
    >>> func([(10, 1), (20, 2), (30, 3)], [1])
    11
    >>> func = make_grp_list_func('sum(a)', {'a': 0})
    >>> func([(1,), (2,), (3,)])
    6
    >>> func([(1,), (2,), (3,)])
    6
    """
    global_names_dict = global_names_dict or dict()
    filename = filename or '<generated>'

    grp_rewriter = RewriteGrpFuncs()

    tree = ast.parse(expr_str, filename, 'eval')
    tree = grp_rewriter.visit(tree)
    result_func = _make_list_func(
        tree,
        global_names_dict,
        filename=filename,
        add_args=['grp_vals'],
    )

    grp_funcs = []
    for repl in grp_rewriter.grp_replaces:
        arg_funcs = []
        for arg in repl.args:
            arg_func = _make_list_func(
                ast.Expression(body=arg),
                field_names_dict,
                filename,
            )
            arg_funcs.append(arg_func)
        grp_funcs.append((repl.grp_func, arg_funcs))

    def aggregator(items, args=None):
        args = args or []
        funcs = list()
        for grp_func_class, arg_funcs in grp_funcs:
            grp_func = grp_func_class()
            funcs.append(grp_func)
            for item in items:
                grp_func.update(*[func(item) for func in arg_funcs])
        return result_func(
            args,
            [grp_func.getval() for grp_func in funcs],
        )

    return aggregator

def AutoDict():
    '''
    >>> a = AutoDict()
    >>> a.get('not exists', 0)
    0
    '''
    c = count()
    return defaultdict(lambda: next(c))

def make_subscript(varname, idx, ctx=None, lineno=0, col_offset=0):
    ctx = ctx or ast.Load()
    return ast.Subscript(
        value = ast.Name(
            id = varname,
            ctx = ast.Load(),
            lineno = lineno,
            col_offset = col_offset,
        ),
        slice = ast.Index(
            value = ast.Num(
                n = idx,
                lineno = lineno,
                col_offset = col_offset,
            ),
            lineno = lineno,
            col_offset = col_offset,
        ),
        ctx = ctx,
        lineno = lineno,
        col_offset = col_offset,
    )
    
class RewriteName(ast.NodeTransformer):
    def __init__(self, list_name, field_names_dict):
        self.list_name = list_name
        self.field_names_dict = field_names_dict

    def visit_Name(self, node):
        idx = self.field_names_dict.get(node.id, None)
        if node.id not in self.field_names_dict:
            return node
        else:
            return make_subscript(
                self.list_name,
                idx,
                ctx=node.ctx,
                lineno=node.lineno,
                col_offset=node.col_offset,
            )

def _make_list_func(tree, field_names_dict, filename=None, add_args=None):
    filename = filename or '<generated>'
    list_name = 'data'

    rewriter = RewriteName(list_name, field_names_dict)

    lambda_args = [ast.Name(id=list_name, ctx=ast.Param(), lineno=0, col_offset=0)]
    for arg in (add_args or []):
        lambda_args.append(
            ast.Name(id=arg, ctx=ast.Param(), lineno=0, col_offset=0)
        )

    tree = rewriter.visit(tree)
    tree = ast.Expression(
        body = ast.Lambda(
            lineno = 0,
            col_offset = 0,
            body = tree.body,
            args = ast.arguments(
                args = lambda_args,
                vararg = None,
                kwarg = None,
                defaults = [],
            )
        ),
    )
    code = compile(tree, filename, 'eval')
    func = eval(code)
    return func

class Summator(object):
    __slots__ = ['val']
    def __init__(self):
        self.val = 0
    def update(self, val):
        self.val += val
    def getval(self):
        return self.val
        
class Counter(object):
    __slots__ = ['val']
    def __init__(self):
        self.val = 0
    def update(self):
        self.val += 1
    def getval(self):
        return self.val        

GRP_FUNCS = {
    'sum' : Summator,
    'cnt' : Counter
}


from collections import namedtuple

GrpReplace = namedtuple('GrpReplace', 'grp_func args kwargs')

class RewriteGrpFuncs(ast.NodeTransformer):
    def __init__(self):
        self.grp_replaces = []
        self.last_replace_num = count()

    def visit_Call(self, node):
        if node.func.id not in GRP_FUNCS:
            return node
        else:
            grp_func = GRP_FUNCS[node.func.id]
            self.grp_replaces.append(GrpReplace(
                grp_func = grp_func,
                args = node.args,
                kwargs = node.kwargs,
            ))
            return make_subscript(
                'grp_vals',
                next(self.last_replace_num),
                lineno = node.lineno,
                col_offset = node.col_offset,
            )

class TabkitPythonError(Exception):
    pass

def _test(): # pylint: disable-msg=E0102
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()

