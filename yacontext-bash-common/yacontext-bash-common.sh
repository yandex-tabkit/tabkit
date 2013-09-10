#!/bin/bash

set -o pipefail
set -o errexit

SIGPIPE_STATUS=0x8D

function dispatch {
    if [[ ${1:0:2} == -- ]]; then
        func=${1:2}
        if [[ $func == help ]]; then
            return
        fi
        shift 1
        ${func//-/_} $@
        exit
    fi
}

function auto_help {
    echo Usage: $0 --mode $@ [arguments]
    echo
    echo Available options are:
    cat $0 | grep ^function | awk '{print $2}' | grep -v ^_ | tr _ - | awk '{ print "  --"$1 }'
}

function no_sigpipe {
    ( "$@" || (( $? == $SIGPIPE_STATUS )))
}

function check_eof {
    # Завершается с ошибкой, если последняя строчка
    # не равна переменной окружения EOF.
    # Не удаляет последнюю строчку!
    #
    # Пример:
    # $ echo -e "1\n\2\n#End" | EOF="#End" check_eof | wc -l
    # 3
    #
    awk '{
        last = $0;
        print
    } END {
        if(last != ENVIRON["EOF"]) {
            print "EOF not received! Last line: "last > "/dev/stderr";
            exit(1);
        }
    }'
}

function writeto {
    # writeto <FILENAME> <COMMAND>
    # Пишет stdout команды COMMAND в файл FILENAME.
    # Файл появляется только в случае успешного завершения команды.
    #
    # Пример:
    # writeto files.list ls -l
    #
    fname="$1"
    shift
    tmp_fname=$(mktemp "$(dirname "$fname")/.$(basename "$fname").XXXXXX") # " <-- this quote is to fix mc syntax highlighter
    function rm_tmp { rm "$tmp_fname"; }
    trap rm_tmp ERR
    "$@" > "$tmp_fname"
    mv "$tmp_fname" "$fname"
    chmod a+r "$fname"
}

