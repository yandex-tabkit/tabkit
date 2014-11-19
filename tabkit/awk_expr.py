# coding: utf-8
import copy

class RowExprAssign(object):
    def __init__(self, target, value):
        self.target = target
        self.value = value
    def tostr(self):
        return self.target + ' = ' + self.value.tostr()
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for node in self.value.find(node_type, node_props):
            yield node

class RowExprConst(object):
    def __init__(self, const):
        self.const = const
        if isinstance(const, str):
            self.type = "str"
        elif isinstance(const, int):
            self.type = "int"
        elif isinstance(const, float):
            self.type = "float"
        elif isinstance(const, bool):
            self.type = "bool"
        else:
            raise Exception("Unsupported type of const %r" % (const,))
    def tostr(self):
        if isinstance(self.const, str):
            return '"' + self.const.replace('"', r'\"') + '"'
        elif isinstance(self.const, bool):
            return str(int(self.const))
        else:
            return str(self.const)
    def find(self, node_type, node_props):
        return match_node(self, node_type, node_props)

class RowExprField(object):
    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
        if self.name.startswith('__'):
            raise Exception("Variable name can't start with '__'")
    def tostr(self):
        return '$' + str(self.ctx.data_desc.field_index(self.name) + 1)
    def find(self, node_type, node_props):
        return match_node(self, node_type, node_props)

class RowExprBuiltinVar(object):
    def __init__(self, name):
        self.name = name
    def tostr(self):
        return self.name
    def find(self, node_type, node_props):
        return []

class RowExprVar(object):
    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
    def tostr(self):
        return self.name
    def get_var_expr(self):
        return self.ctx.get_var_expr(self.name)
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        var_expr = self.ctx.get_var_assign_expr(self.name)
        if isinstance(var_expr, RowExprAssign):
            var_expr = var_expr.value
        for node in var_expr.find(node_type, node_props):
            yield node
    def pop_nested(self, out_lines):
        nested_func = self.get_var_expr()
        line = self.name + '=' + nested_func.tostr()
        if line not in out_lines:
            out_lines.insert(0, line)
        hasattr(nested_func, 'pop_nested') and nested_func.pop_nested(out_lines)

class RowExprSideEffectVar(object):
    def __init__(self, name, var):
        self.name = name
        self.var = var
    def tostr(self):
        return self.name
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for node in self.var.find(node_type, node_props):
            yield node
    def pop_nested(self, out_lines):
        hasattr(self.var, 'pop_nested') and self.var.pop_nested(out_lines)
        
class RowExprFunc(object):
    def __init__(self, func, args):
        self.func = func
        self.args = args
    def tostr(self):
        return self.func + '(' + ', '.join(arg.tostr() for arg in self.args) + ')'
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for arg in self.args:
            for node in arg.find(node_type, node_props):
                yield node
    def pop_nested(self, out_lines):
        for n_arg in self.args:
            hasattr(n_arg, 'pop_nested') and n_arg.pop_nested(out_lines)

class RowExprSubscript(object):
    def __init__(self, var, idx):
        self.var = var
        self.idx = idx
    def tostr(self):
        return self.var.tostr() + '[' + self.idx.tostr() + ']'
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for node in self.var.find(node_type, node_props):
            yield node
        for node in self.idx.find(node_type, node_props):
            yield node
    def pop_nested(self, out_lines):
        hasattr(self.var, 'pop_nested') and self.var.pop_nested(out_lines)
        hasattr(self.idx, 'pop_nested') and self.idx.pop_nested(out_lines)

class RowExprOp(object):
    def __init__(self, op, args):
        self.op = op
        self.args = args
    def tostr(self):
        return '(' + (' ' + self.op + ' ').join(arg.tostr() for arg in self.args) + ')'
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for arg in self.args:
            for node in arg.find(node_type, node_props):
                yield node
    def pop_nested(self, out_lines):
        for n_arg in self.args:
            hasattr(n_arg, 'pop_nested') and n_arg.pop_nested(out_lines)

class RowExprIf(object):
    def __init__(self, test, body, orelse):
        self.test = test
        self.body = body
        self.orelse = orelse
    def tostr(self):
        return "(%s?%s:%s)" % (
            self.test.tostr(),
            self.body.tostr(),
            self.orelse.tostr(),
        )
    def find(self, node_type, node_props):
        for node in match_node(self, node_type, node_props):
            yield node
        for arg in [self.test, self.body, self.orelse]:
            for node in arg.find(node_type, node_props):
                yield node
    def pop_nested(self, out_lines):
        hasattr(self.test, 'pop_nested') and self.test.pop_nested(out_lines)
        hasattr(self.orelse, 'pop_nested') and self.orelse.pop_nested(out_lines)

class Namer(object):
    """
    >>> n = Namer()
    >>> n.get_name('a', 'a')
    a1
    >>> n.get_name('b', 'a')
    b1
    >>> n.get_name('a', 'b')
    a2
    >>> n.get_name('a', 'a')
    a1
    """
    def __init__(self):
        self.names = {}
        self.cnts = {}
    def get_name(self, prefix, obj):
        if (prefix, obj) in self.names:
            return self.names[(prefix, obj)]
        else:
            name = prefix + str(self.cnts.setdefault(prefix, 0))
            self.names[(prefix, obj)] = name
            self.cnts[prefix] += 1
            return name

class ExprContext(object):
    def __init__(self, data_desc, namer=None):
        self.data_desc = data_desc
        self.vars = {}
        self.varnames = []
        self.namer = namer or Namer()
    def has_field(self, name):
        return self.data_desc.has_field(name)
    def has_var(self, name):
        return name in self.vars
    def get_var_assign_expr(self, name):
        return self.vars[name]
    def get_var_expr(self, name):
        expr = self.vars[name]
        if isinstance(expr, RowExprAssign):
            return expr.value
        elif isinstance(expr, RowExprOp):
            return expr
        else:
            raise Exception('No expression for variable %r' % (name,))
    def itervars(self):
        for name in self.varnames:
            yield name, self.vars[name]
    def var_refers_to_field(self, varname):
        assign = self.vars[varname]
        if isinstance(assign, RowExprAssign):
            # добавление '' в конце строки не влияет на результат
            if isinstance(assign.value, RowExprOp) and assign.value.op=='':
                args = assign.value.args
                if len(args)==2 and isinstance(args[0], RowExprField) and isinstance(args[1], RowExprConst):
                    return args[0].name if args[1].const == '' else None
            if isinstance(assign.value, RowExprField):
                return assign.value.name
            if isinstance(assign.value, RowExprVar):
                if hasattr(assign.value, 'ctx'):
                    return self.var_refers_to_field(assign.value.name)
                else: # ctx отсутствует у _GrpExprFunc
                    return None
        else:
            return None
    def set_var(self, name, assign_expr, insert_at=None):
        if name not in self.vars:
            self.vars[name] = assign_expr
            if insert_at == None:
                self.varnames.append(name)
            else:
                self.varnames.insert(insert_at, name)
        else:
            raise Exception("Variable named %r already exists" % (name,))
    def get_name(self, prefix, obj):
        return self.namer.get_name(prefix, obj)

class _GrpExprFunc(RowExprVar):
    def __init__(self, name, func, init, update, args, end=None):
        self.name = name
        self.func = func
        self.init = init
        self.update = update
        self.args = args
        if end:
            self.end = end
    def tostr(self):
        return self.name
    def find(self, node_type, node_props):
        return match_node(self, node_type, node_props)
    def _expand_tpl(self, tpl, recursive=False):
        args = dict(var=self.name)
        for num, arg in enumerate(self.args):
            args['rowexpr%s' % (num,)] = arg.tostr()
        upd_lines = []
        if recursive:
            for arg in self.args:
                hasattr(arg, 'pop_nested') and arg.pop_nested(upd_lines)
                # self._pop_nested(arg, upd_lines)
            upd_lines.append(tpl % args)
            return upd_lines
        else:
            return tpl % args
    def init_str(self):
        return self._expand_tpl(self.init)
    def update_str(self, recursive=False):
        return self._expand_tpl(self.update, recursive)
    def end_str(self):
        if hasattr(self, 'end'):
            return self._expand_tpl(self.end)
        else:
            return ''

def match_node(node, node_type, node_props):
    if not isinstance(node, node_type):
        return iter([])
    for name, val in node_props.iteritems():
        if not (hasattr(node, name) and getattr(node, name) == val):
            return iter([])
    return iter([node])
