import fcntl
import io
import os
import pkg_resources
import random
import resource
import socket
import sys
import textwrap
import time
import traceback
import inspect
import errno
from importlib import import_module

from errors import *

DEV_NULL = getattr(os, 'devnull', '/dev/null')

try:
    from os import closerange
except ImportError:
    def closerange(fd_low, fd_high):
        # Iterate through and close all file descriptors.
        for fd in range(fd_low, fd_high):
            try:
                os.close(fd)
            except OSError:  # ERROR, fd wasn't open to begin with (ignored)
                pass

try:
    from setproctitle import setproctitle
    def _setproctitle(title):
        setproctitle("culexx: %s" % title)
except ImportError:
    def _setproctitle(title):
        return

def import_app(module):
    parts = module.split(":", 1)
    if len(parts) == 1:
        module, obj = module, "application"
    else:
        module, obj = parts[0], parts[1]

    try:
        __import__(module)
    except ImportError:
        if module.endswith(".py") and os.path.exists(module):
            raise ImportError("Failed to find application, did "
                "you mean '%s:%s'?" % (module.rsplit(".", 1)[0], obj))
        else:
            raise

    mod = sys.modules[module]

    try:
        app = eval(obj, mod.__dict__)
    except NameError:
        raise AppImportError("Failed to find application: %r" % module)

    if app is None:
        raise AppImportError("Failed to find application object: %r" % obj)

    return app

def load_class(uri):
    if inspect.isclass(uri):
        return uri

    components = uri.split('.')
    klass = components.pop(-1)

    try:
        mod = import_module('.'.join(components))
    except:
        exc = traceback.format_exc()
        raise RuntimeError(
                "class uri %r invalid or not found: \n\n[%s]" %
                (uri, exc))
    return getattr(mod, klass)

def get_maxfd():
    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if (maxfd == resource.RLIM_INFINITY):
        maxfd = MAXFD
    return maxfd

def getcwd():
    # get current path, try to use PWD env first
    try:
        a = os.stat(os.environ['PWD'])
        b = os.stat(os.getcwd())
        if a.st_ino == b.st_ino and a.st_dev == b.st_dev:
            cwd = os.environ['PWD']
        else:
            cwd = os.getcwd()
    except:
        cwd = os.getcwd()
    return cwd

def perform_fork():
    try: 
        if os.fork(): # parent
            sys.exit(0) 
    except OSError, e: 
        sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
        sys.exit(1)

def daemonize(enable_stdio_inheritance=False):
    """
    Standard daemonization of a process.
    http://www.svbug.com/documentation/comp.unix.programmer-FAQ/faq_2.html#SEC16
    """

    # exit first parent
    perform_fork()

    # become a session leader to lose controlling TTY
    os.setsid()

    # exit second parent
    perform_fork()

    # clear file creation mask.
    os.umask(0)

    # attach file descriptors 0, 1, and 2 to /dev/null.

    # In both the following any file descriptors above stdin
    # stdout and stderr are left untouched. The inheritence
    # option simply allows one to have output go to a file
    # specified by way of shell redirection when not wanting
    # to use --error-log option.

    fd_null = os.open(DEV_NULL, os.O_RDWR)

    if not enable_stdio_inheritance:
        # Remap all of stdin, stdout and stderr on to
        # /dev/null. The expectation is that users have
        # specified the --error-log option.
        closerange(0, 3)

        if fd_null != 0:
            os.dup2(fd_null, 0)

        os.dup2(fd_null, 1)
        os.dup2(fd_null, 2)
    else:
        # Always redirect stdin to /dev/null as we would
        # never expect to need to read interactive input.
        if fd_null != 0:
            os.close(0)
            os.dup2(fd_null, 0)

        # If stdout and stderr are still connected to
        # their original file descriptors we check to see
        # if they are associated with terminal devices.
        # When they are we map them to /dev/null so that
        # are still detached from any controlling terminal
        # properly. If not we preserve them as they are.
        #
        # If stdin and stdout were not hooked up to the
        # original file descriptors, then all bets are
        # off and all we can really do is leave them as
        # they were.
        #
        # This will allow 'culexx ... > output.log 2>&1'
        # to work with stdout/stderr going to the file
        # as expected.
        #
        # Note that if using --error-log option, the log
        # file specified through shell redirection will
        # only be used up until the log file specified
        # by the option takes over. As it replaces stdout
        # and stderr at the file descriptor level, then
        # anything using stdout or stderr, including having
        # cached a reference to them, will still work.
        def redirect(stream, fd_expect):
            try:
                fd = stream.fileno()
                if fd == fd_expect and stream.isatty():
                    os.close(fd)
                    os.dup2(fd_null, fd)
            except AttributeError:
                pass

        redirect(sys.stdout, 1)
        redirect(sys.stderr, 2)
