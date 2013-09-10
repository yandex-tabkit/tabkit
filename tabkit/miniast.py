from _ast import *
from _ast import __version__

def parse(expr, filename='<unknown>', mode='exec'):
    """
    Parse an expression into an AST node.
    Equivalent to compile(expr, filename, mode, PyCF_ONLY_AST).
    """
    return compile(expr, filename, mode, PyCF_ONLY_AST)

def dump(node, annotate_fields=True, include_attributes=False):
    """
    Return a formatted dump of the tree in *node*.  This is mainly useful for
    debugging purposes.  The returned string will show the names and the values
    for fields.  This makes the code impossible to evaluate, so if evaluation is
    wanted *annotate_fields* must be set to False.  Attributes such as line
    numbers and column offsets are not dumped by default.  If this is wanted,
    *include_attributes* can be set to True.
    """
    def _format(node):
        if isinstance(node, AST):
            fields = [(a, _format(b)) for a, b in iter_fields(node)]
            if annotate_fields:
                rv = '%s(%s' % (node.__class__.__name__, ', '.join(
                    ('%s=%s' % field for field in fields)
                ))
            else:
                rv = '%s(%s' % (node.__class__.__name__, ', '.join(
                    (b for a, b in fields)
                ))
            if include_attributes and node._attributes:
                rv += fields and ', ' or ' '
                rv += ', '.join('%s=%s' % (a, _format(getattr(node, a)))
                                for a in node._attributes)
            return rv + ')'
        elif isinstance(node, list):
            return '[%s]' % ', '.join(_format(x) for x in node)
        return repr(node)
    if not isinstance(node, AST):
        raise TypeError('expected AST, got %r' % node.__class__.__name__)
    return _format(node)

def iter_fields(node):
    """
    Yield a tuple of ``(fieldname, value)`` for each field in ``node._fields``
    that is present on *node*.
    """
    if node._fields:
        for field in node._fields:
            try:
                yield field, getattr(node, field)
            except AttributeError:
                pass


