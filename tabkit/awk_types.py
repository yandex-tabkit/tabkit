from tabkit.awk_expr import *
from tabkit.awk_expr import _GrpExprFunc

def infer_types(objs):
    return (infer_type(expr) for expr in objs)

def infer_type(obj):
    if isinstance(obj, RowExprConst):
        return obj.type
    if isinstance(obj, RowExprField):
        return obj.ctx.data_desc.get_field(obj.name).type
    if isinstance(obj, RowExprVar):
        if isinstance(obj, _GrpExprFunc):
            if obj.func in ["ifmin", "ifmax"]:
                return infer_type(obj.args[1])
            if obj.func in ["first", "last"]:
                return infer_type(obj.args[0])
            if obj.func in ["max", "min", "sum", "product", "median", "var"]:
                type = infer_type(obj.args[0])
                if type not in ['int', 'float']:
                    type = 'float'
                return type
            if obj.func in ["cnt"]:
                return "int"
            if obj.func in ["avg"]:
                return "float"
            if obj.func in [
                    "concat", "concat_uniq", "concat_sorted",
                    "chain_concat_uniq", "concat_sample",
                ]:
                return "str"
        else:
            return infer_type(obj.get_var_expr())
    if isinstance(obj, RowExprOp):
        arg_types = list(infer_type(arg) for arg in obj.args)
        if obj.op in [""]:
            if "any" in arg_types:
                return "any"
            return "str"
        if obj.op in ["&&", "||", "!", "==", "!=", ">", "<", ">=", "<="]:
            return "bool"
        if obj.op in "+-*^%":
            if "any" in arg_types:
                return "any"
            if "float" in arg_types:
                return "float"
            return "int"
        if obj.op == "/":
            if "any" in arg_types:
                return "any"
            return "float"
        print obj.op, arg_types
    if isinstance(obj, RowExprFunc):
        if obj.func == "int":
            return "int"
        if obj.func == "sprintf":
            return "str"
        if obj.func == "log":
            return "float"
    if isinstance(obj, RowExprIf):
        arg_types = [infer_type(obj.body), infer_type(obj.orelse)]
        for type in ['any', 'str', 'float', 'int']:
            if type in arg_types:
                return type
    return "any"

