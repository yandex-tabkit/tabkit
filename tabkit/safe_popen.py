from subprocess import Popen, PIPE
from signal import signal, SIGPIPE, SIG_DFL

def safe_popen_args(command):
    return ['/bin/bash', '-o', 'pipefail', '-o', 'errexit', '-c', command]

class SafePopenError(Exception):
    pass

class SafePopen(Popen):
    def __init__(self, cmdline, bufsize=None, stdin=None):
        popen_args = dict(
            args = safe_popen_args(cmdline),
            shell = False,
            stdin = stdin,
            stdout = PIPE,
            preexec_fn = lambda: signal(SIGPIPE, SIG_DFL),
        )
        if bufsize != None:
            popen_args['bufsize'] = bufsize
        super(SafePopen, self).__init__(**popen_args)
        self.__cmdline = cmdline

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        self.stdout.close() # pylint: disable=E1101
        status = self.wait() # pylint: disable=E1101
        if status != 0:
            raise SafePopenError("safe_popen failed on %r, status = %r" % (
                self.__cmdline, status
            ))

def safe_popen(command, bufsize=None):
    """
    >>> list(safe_popen('echo ok'))
    ['ok\\n']

    >>> list(safe_popen('false; echo ok'))
    Traceback (most recent call last):
        ...
    SafePopenError: safe_popen failed on 'false; echo ok', status = 1

    >>> list(safe_popen('false|true; echo ok'))
    Traceback (most recent call last):
        ...
    SafePopenError: safe_popen failed on 'false|true; echo ok', status = 1
    """
    popen = SafePopen(command, bufsize)
    try:
        for line in popen.stdout: # pylint: disable=E1101
            yield line
    except:
        popen.close()
        raise
    else:
        popen.close()

def safe_system(command):
    popen = Popen(
        args = safe_popen_args(command),
        shell = False,
        preexec_fn = lambda: signal(SIGPIPE, SIG_DFL),
    )
    status = popen.wait() # pylint: disable=E1101
    if status != 0:
        raise SafePopenError("safe_system failed on %r, status = %r" % (command, status))

