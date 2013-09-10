# coding: utf-8

import ast
from python import RewriteName, make_subscript

def make_grp_list_func(expr_str, field_names_dict, global_names_dict=None, filename=None):
    """
    >>> func = make_grp_list_func('sum(a)/cnt()', {'a': 0})
    >>> func([(1,), (2,), (3,)])
    2
    >>> func = make_grp_list_func('1+sum(a)+sum(b**2)', {'a':0, 'b':1})
    >>> func([(10, 1), (20, 2)])
    36
    >>> func = make_grp_list_func('b+sum(a)/sum(c)', {'a': 0, 'c': 1}, {'b': 0})
    >>> func([(10, 1), (20, 2), (30, 3)], [1])
    11
    >>> func = make_grp_list_func('sum(a)', {'a': 0})
    >>> func([(1,), (2,), (3,)])
    6
    """
    filename = filename or '<generated>'
    list_name = 'data'
    lambda_args = [ast.Name(id=list_name, ctx=ast.Param(), lineno=0, col_offset=0)]

    tree = ast.parse(expr_str, filename, 'eval')
    tree = RewriteCntFuncs().visit(tree)
    tree = RewriteGrpFuncs(field_names_dict).visit(tree)
    if global_names_dict:
        lambda_args.append(ast.Name(id='globaldata', ctx=ast.Param(), lineno=0, col_offset=0))
        tree = RewriteName('globaldata', global_names_dict).visit(tree)
    tree = ast.Expression(
        body = ast.Lambda(
            body=tree.body,
            args=ast.arguments(
                args=lambda_args,
                vararg=None,
                kwarg=None,
                defaults=[],
            ),
            lineno=0,
            col_offset=0,
        ),
    )
    #print ast.dump(tree)
    code = compile(tree, filename, 'eval')
    func = eval(code)
    return func
    
GRP_FUNCS = ['sum', 'max', 'min']

class RewriteGrpFuncs(ast.NodeTransformer):
    def __init__(self, field_names_dict):
        self.field_names_dict = field_names_dict

    def visit_Call(self, node):
        if node.func.id not in GRP_FUNCS:
            return node
        else:
            self.generic_visit(node)
            return ast.Call(
                func=node.func,
                args=[
                    ast.ListComp(
                        elt=node.args[0],
                        generators=[
                            ast.comprehension(
                                target=ast.Name(id="datarow", ctx=ast.Store(), lineno=0, col_offset=0),
                                iter=ast.Name(id="data", ctx=ast.Load(), lineno=0, col_offset=0),
                                ifs=[],
                                lineno=0,
                                col_offset=0
                            )
                        ],
                        lineno=0,
                        col_offset=0,
                    )
                ],
                keywords=[],
                ctx=ast.Load(),
                lineno=0,
                col_offset=0,
            )

    def visit_Name(self, node):
        if node.id in self.field_names_dict:
            return make_subscript(
                'datarow',
                self.field_names_dict[node.id],
                node.ctx,
                node.lineno,
                node.col_offset
            )
        else:
            return node

class RewriteCntFuncs(ast.NodeTransformer):
    def visit_Call(self, node):
        if node.func.id == "cnt":
            return ast.Call(
                func=ast.Name(id="len", ctx=ast.Load(), lineno=0, col_offset=0),
                args=[ast.Name(id="data", ctx=ast.Load(), lineno=0, col_offset=0)],
                keywords=[],
                ctx=ast.Load(),
                lineno=node.lineno,
                col_offset=node.col_offset
            )
        else:
            return node

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()

