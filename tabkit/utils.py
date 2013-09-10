from __future__ import with_statement

import sys
import os
import gzip
from subprocess import Popen, PIPE
from collections import defaultdict
from pipes import quote
from itertools import islice
from optparse import IndentedHelpFormatter
from textwrap import dedent

from tabkit.header import parse_header, read_fd_header, read_file_header
from tabkit.datasrc import DataDesc, merge_data_fields, merge_meta
from tabkit.safe_popen import safe_popen, safe_system

try:
    from functools import partial
except ImportError:
    def partial(func, *args, **keywords):
        def newfunc(*fargs, **fkeywords):
            newkeywords = keywords.copy()
            newkeywords.update(fkeywords)
            return func(*(args + fargs), **newkeywords)
        newfunc.func = func
        newfunc.args = args
        newfunc.keywords = keywords
        return newfunc

def exception_handler(func):
    if '--pytrace' in sys.argv:
        func()
    else:
        try:
            func()
        except SyntaxError, err:
            msg, (fname, line, col, code) = err.args
            err = "%s in %r (line=%s, column=%s)" % (msg, code, line, col)
            print >> sys.stderr, sys.argv[0] + ":", type(err).__name__ + ":", err
        except Exception, err:
            print >> sys.stderr, sys.argv[0] + ":", type(err).__name__ + ":", err
            sys.exit(1)

class InputFile(object):
    def __init__(self, header):
        self.header = header
    def desc(self):
        return parse_header(self.header)
    def get_fileobj(self):
        raise Exception('Redefine me')
    def cmd_arg(self):
        raise Exception('Redefine me')
    def is_stdin(self):
        raise Exception('Redefine me')

class PlainFile(InputFile):
    def __init__(self, fname, header=None):
        self.fname = fname
        self.header = header or read_file_header(fname)
        self.has_header = not header
    def get_fileobj(self):
        return open(self.fname)
    def cmd_arg(self):
        if self.has_header:
            return "<(tail -qn +2 %s || kill $$)" % (quote(self.fname),)
        else:
            return quote(self.fname)
    def is_stdin(self):
        return False

class GzipFile(InputFile):
    def __init__(self, fname, header=None):
        self.fname = fname
        self.has_header = not header
        if not self.has_header:
            self.header = header
        else:
            fobj = gzip.open(fname)
            try:
                self.header = fobj.readline()
            finally:
                fobj.close()
    def get_fileobj(self):
        return gzip.open(self.fname)
    def cmd_arg(self):
        if self.has_header:
            return "<(set -o pipefail; gzip -cd %s|tail -qn +2 || kill $$)" % (quote(self.fname),)
        else:
            return "<(gzip -cd %s || kill $$)" % (quote(self.fname),)
    def is_stdin(self):
        return False

class FdFile(InputFile):
    def __init__(self, fname, fd, header=None):
        self.fname = '/dev/fd/%d' % (fd,)
        self.fd = fd
        self.header = header or read_fd_header(fd)
    def get_fileobj(self):
        return os.fdopen(self.fd, 'r')
    def cmd_arg(self):
        return '/dev/fd/%d' % (self.fd,)
    def is_stdin(self):
        return self.fd == 0

class StreamFile(FdFile):
    def __init__(self, fname, fobj, header=None):
        super(StreamFile, self).__init__(fname, fobj.fileno(), header)
        self.fobj = fobj
    def get_fileobj(self):
        return self.fobj

class StdinFile(StreamFile):
    def __init__(self, header=None):
        super(StdinFile, self).__init__('-', sys.stdin, header)

def input_file_from_cmdline_arg(fname, header=None, gzip=False):
    if fname == '-':
        return StdinFile(header)
    elif os.path.isfile(fname):
        if gzip:
            return GzipFile(fname, header)
        else:
            return PlainFile(fname, header)
    elif os.path.exists(fname):
        if fname.startswith('/dev/fd/'):
            return FdFile(fname, int(fname.split('/', 3)[3]), header)
        else:
            return StreamFile(fname, open(fname), header)
    else:
        raise Exception('File does not exist: %r' % (fname,))

class FilesList(object):
    def __init__(self, fnames, stdin_fallback=True, header=None, gzip=False):
        self.header = header
        self.input_files = []

        if stdin_fallback and not fnames:
            fnames = ['-']

        got_stdin = False
        for fname in fnames:
            input_file = input_file_from_cmdline_arg(fname, header, gzip=gzip)
            if input_file.is_stdin():
                if got_stdin:
                    raise Exception('"-" specified as input file more than once')
                got_stdin = True
            self.input_files.append(input_file)

    def __len__(self):
        return len(self.input_files)

    def __iter__(self):
        return iter(self.input_files)

    def get_size(self):
        size = 0
        for fname, desc in self.names_descs():
            if os.path.isfile(fname):
                size += os.stat(fname).st_size
            elif desc.size != None:
                size += desc.size
            else:
                return None
        return size

    def names_descs(self):
        for ifile in self.input_files:
            yield ifile.fname, ifile.desc()

    def concat_desc(self):
        fields = None
        order = []
        for fname, desc in self.names_descs():
            order = desc.order
            if fields:
                fields = merge_data_fields(fields, desc.fields)
            else:
                fields = desc.fields
        if len(self) != 1:
            order = []
        return DataDesc(fields, order)

    def concat_meta(self):
        return proper_reduce(merge_meta, (desc.meta for fname, desc in self.names_descs()))

    def readlines(self):
        for ifile in self.input_files:
            with ifile.get_fileobj() as fobj:
                for line in fobj:
                    yield line

    def cmd_args(self):
        args = []
        for ifile in self.input_files:
            args.append(ifile.cmd_arg())
        return args

    def cmd_args_str(self):
        if len(self.input_files) == 1 and self.input_files[0].is_stdin():
            return ''
        else:
            return ' '.join(self.cmd_args())

def parse_renamings(renaming_opts, descs):
    field_names = [[field.name for field in desc.fields] for desc in descs]
    renamings = defaultdict(dict)
    for rename in renaming_opts:
        if '=' not in rename:
            raise Exception("bad renaming rule: %r (no equality sign)" % (rename,))
        else:
            left, right = (part.strip() for part in rename.split('=', 1))

            if '.' in left and '.' in right:
                raise Exception("bad renaming rule: %r (dots on both sides)" % (rename,))
            elif '.' in left:
                filenum_str, old_name = left.split('.', 1)
                new_name = right
            elif '.' in right:
                filenum_str, old_name = right.split('.', 1)
                new_name = left
            else:
                raise Exception("bad renaming rule: %r (no filenum)" % (rename,))

            if filenum_str in ['1', '2']:
                filenum = int(filenum_str) - 1
            else:
                raise Exception("bad renaming rule: %r (wrong filenum %r, must be 1 or 2)" % (
                    rename, filenum_str
                ))

            if old_name == '*':
                if new_name.count('*') != 1:
                    raise Exception("bad renaming rule: %r (bad target pattern)" % (rename,))
                for field_name in field_names[filenum]:
                    renamings[filenum][field_name] = new_name.replace('*', field_name)
            elif old_name not in field_names[filenum]:
                raise Exception("Not found field %r in file %r while renaming: %r" % (
                    old_name, filenum, rename,
                ))
            else:
                renamings[filenum][old_name] = new_name
    return renamings

def proper_reduce(func, args):
    args_iter = iter(args)
    res = list(islice(args_iter, 2))
    if len(res) == 1:
        return res[0]
    else:
        res = func(*list(res))
        for arg in args_iter:
            res = func(res, arg)
        return res

##
## OPTPARSE UTILS
##

def add_header(parser):
    parser.add_option(
        '-H', '--header', dest="header",
        help="assume there are no headers in input files and use HEADER instead",
    )

def add_no_out_header(parser):
    parser.add_option(
        '-N', '--no-out-header', dest="no_out_header", action="store_true",
        help="don't print resulting header (useful for mapreduce)",
    )

def add_pytrace(parser):
    parser.add_option(
        '--pytrace', dest="pytrace", action="store_true",
        help="verbose python errors"
    )

def add_print_cmd(parser):
    parser.add_option(
        '--print-cmd', dest="print_cmd", action="store_true",
        help="dry run, print commands that must be run",
    )

def add_awk_exec(parser):
    parser.add_option(
        '-A', '--awk-exec', dest="awk_exec",
        help="use AWK_EXEC as awk executable",
    )
    
def add_meta(parser):
    parser.add_option(
        '--meta', dest="meta", action="store",
        help="specify metadata in yaml-parseable format (outter curls are optional, space after colon are optional if no quotes used)"
    )
    parser.add_option(
        '-M', '--pass-meta', dest="pass_meta", action="store_true",
        help="pass meta into result"
    )    
    parser.add_option(
        '--pass-meta-keys', dest="pass_meta_keys", action="store",
        help="specify meta keys to pass into result"
    )    

class OptUtils(object):
    add_header = staticmethod(add_header)
    add_no_out_header = staticmethod(add_no_out_header)
    add_pytrace = staticmethod(add_pytrace)
    add_print_cmd = staticmethod(add_print_cmd)
    add_awk_exec = staticmethod(add_awk_exec)
    add_meta = staticmethod(add_meta)

class OptparsePrettyFormatter(IndentedHelpFormatter):
    def format_description(self, description):
        return "\n\n".join(
            self._format_text(par) for par in dedent(description.lstrip('\n')).split('\n\n')
        ) + "\n"


def exec_path(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None
