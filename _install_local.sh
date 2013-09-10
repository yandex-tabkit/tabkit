#!/bin/bash

set -e
set -o pipefail

function create_sitecustomize {
mkdir -p ~/.local
cat > ~/.local/sitecustomize.py <<-DELIMITER
import sys, os
sys.path.append(
    os.path.join(
        os.path.expanduser('~/.local/lib/'),
        "python" + ".".join(map(str, sys.version_info[:2])),
        "site-packages",
    )
)

# install the apport exception handler if available
try:
    import apport_python_hook
except ImportError:
    pass
else:
    apport_python_hook.install()
DELIMITER
}

record=$(mktemp .install_local_record.XXXXXX)
for py in $(pyversions -s); do
    if echo $py | grep -q '^python2\.[45]$'; then
        WARN=1
        create_sitecustomize
        "$py" setup.py clean
        "$py" setup.py install --prefix=~/.local --record "$record"
    else
        "$py" setup.py clean
        "$py" setup.py install --user --record "$record"
    fi
done

prefix=~/.local/bin/
cat "$record" | (grep -E "^$prefix" || true) | xargs -r -I'{}' ln -vsf '{}' ~/bin/
rm "$record"

if [ "$WARN" = 1 ]; then
    echo
    echo "------------"
    echo "WARNING!!!"
    echo "to use locally installed modules with python2.4 and python2.5"
    echo "add following line to your .bashrc:"
    echo
    echo "  export PYTHONPATH=~/.local"
    echo
    echo "------------"
fi
