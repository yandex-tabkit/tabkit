#!/usr/bin/python

import sys, os, re, shutil

def filt_imports(lines, modules):
    for line in lines:
        for mod in modules:
            match = re.match(r'(\s*)from\s+' + mod + '\s+import\s+', line)
            if match:
                line = match.group(1) + 'pass # ' + line.lstrip()
        yield line

def filt_mains(lines):
    main_ident = None
    for line in lines:
        match = re.match(r'(\s*)if __name__\s*==\s*.__main__.', line)
        if match:
            main_ident = len(match.group(1))
            line = '# ' + line
        elif main_ident != None:
            if len(line) - len(line.lstrip()) > main_ident:
                line = '# ' + line
            else:
                main_ident = None
        yield line

def is_future(line):
    return line.startswith('from __future__ import ')

def pack(fname, modules):
    lines = list(open(fname))

    # get headers
    while lines[0].startswith('#'):
        yield lines.pop(0)
    yield "# coding: utf-8"

    futures = set(line for line in lines if is_future(line))
    for mod in modules:
        for line in open(mod2fname(mod)):
            if is_future(line):
                futures.add(line)
            if line.startswith('#'):
                yield line
            else:
                break

    for mod in modules:
        yield "\n### MODULE: " + mod + "\n\n"
        for line in filt_imports(filt_mains(line for line in open(mod2fname(mod)) if not is_future(line)), modules):
            yield line
    yield "\n### MAIN" + "\n\n"
    for line in filt_imports((line for line in lines if not is_future(line)), modules):
        yield line

def mod2fname(mod):
    return '/'.join(mod.split('.')) + '.py'

def compile_tools(dstdir, scripts, modules=None):
    modules = modules or []
    for script, target in scripts:
        target = os.path.join(dstdir, target)
        dst = open(target, 'w')
        dst.writelines(pack(script, modules))
        dst.close()
        os.chmod(target, 0755)

def main(dstdir):
    compile_tools(
        dstdir,
        scripts = [
            ('tbuff', 'tbuff'),
            ('twiki', 'twiki'),
        ],
        modules = [],
    )
    compile_tools(
        dstdir,
        scripts = [
            ('tproject', 'tproject'),
        ],
        modules = [
            'tabkit.utils',
            'tabkit.datasrc',
            'tabkit.header',
            'tabkit.pyparser',
        ],
    )
    compile_tools(
        dstdir,
        scripts = [
            ('tedit_header', 'tedit_header'),
            ('tyaml_parser', 'tyaml_parser'),
            ('tplot',        'tplot'),
        ],
        modules = [
            'tabkit.utils',
            'tabkit.header',
        ]
    )
    compile_tools(
        dstdir,
        scripts = [('tpretty', 'tpretty')],
        modules = [
            'tabkit.datasrc',
            'tabkit.header',
        ],
    )
    compile_tools(
        dstdir = dstdir,
        modules = [
            'tabkit.safe_popen',
            'tabkit.datasrc',
            'tabkit.header',
            'tabkit.utils',
            'tabkit.miniast',
            'tabkit.awk',
            'tabkit.awk_grp',
            'tabkit.awk_expr',
            'tabkit.awk_types',
        ],
        scripts = [
            ('tcat',      'tcat'),
            ('tpv',       'tpv'),
            ('tcut',      'tcut'),
            ('tmap_awk',  'tmap_awk'),
            ('tgrp_awk',  'tgrp_awk'),
            ('tsrt',      'tsrt'),
            ('tjoin',     'tjoin'),
            ('tpaste',    'tpaste'),
            ('tawk',      'tawk'),
            ('t2tab',     't2tab'),
            ('tparallel', 'tparallel'),
            ('tunconcat', 'tunconcat'),
            ('trl',       'trl'),
        ],
    )

if __name__ == '__main__':
    dstdir = 'compiled_tools'
    if sys.argv[1:]:
        dstdir = sys.argv[1]
    elif not os.path.exists(dstdir):
        os.makedirs(dstdir)
    main(dstdir)

