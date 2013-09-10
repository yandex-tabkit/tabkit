#!/bin/bash

source ./yacontext-bash-common.sh

function example_no_sigpipe {
    echo This does not cause a pipefail
    no_sigpipe yes | head

    echo This does
    yes | head
    echo You will not see this message 
}

dispatch $@
auto_help "[-o option]"