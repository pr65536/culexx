# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os
import random
import select
import signal
import sys
import traceback
import pdb
import time
import util

from errors import AppImportError

class Arbiter(object):
    """
    Arbiter maintain the workers processes alive. It launches or
    kills them if needed. It also manages application reloading
    via SIGHUP/USR2.
    """

    # A flag indicating if a worker failed to
    # to boot. If a worker process exist with
    # this error code, the arbiter will terminate.
    WORKER_BOOT_ERROR = 3

    # A flag indicating if an application failed to be loaded
    APP_LOAD_ERROR = 4

    START_CTX = {}

    PIPE = []

    SIG_QUEUE = []
    SIGNALS = [getattr(signal, "SIG%s" % x) \
            for x in "HUP QUIT INT TERM".split()]
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )

    def __init__(self, app):
        os.environ["SERVER_SOFTWARE"] = "culexx"
        self.app = app
        self.cfg = app.cfg
        self.log = self.cfg.logger_class(app.cfg)

        # reopen files
        if 'CULEXX_FD' in os.environ:
            self.log.reopen_files()

        self.debug = self.cfg.debug
        self.proc_name = self.cfg.proc_name

        if self.cfg.debug:
            self.log.debug("Current configuration:")
            for config, value in sorted(self.cfg.settings.items(),
                    key=lambda setting: setting[1]):
                self.log.debug("  %s: %s", config, value.value)

        self.pidfile = None
        self.reexec_pid = 0
        self.master_name = "Master"

        cwd = util.getcwd()

        args = sys.argv[:]
        args.insert(0, sys.executable)

        # init start context
        self.START_CTX = {
            "args": args,
            "cwd": cwd,
            0: sys.executable
        }

    def start(self):
        """\
        Initialize the arbiter. Start listening and set pidfile if needed.
        """
        self.log.info("Starting culexx %s", '0.0.1')

        self.pid = os.getpid()
        if self.cfg.pidfile is not None:
            self.pidfile = Pidfile(self.cfg.pidfile)
            self.pidfile.create(self.pid)

        # set enviroment' variables
        if self.cfg.env:
            for k, v in self.cfg.env.items():
                os.environ[k] = v

        self.init_signals()

        self.app.mosq_app.connect()


    def init_signals(self):
        """\
        Initialize master signal handling. Most of the signals
        are queued. Child signals only wake up the master.
        """
        # close old PIPE
        # if self.PIPE:
        #     [os.close(p) for p in self.PIPE]

        # # initialize the pipe
        # self.PIPE = pair = os.pipe()
        # for p in pair:
        #     util.set_non_blocking(p)
        #     util.close_on_exec(p)

        # self.log.close_on_exec()

        # initialize all signals
        [signal.signal(s, self.signal) for s in self.SIGNALS]


    def signal(self, sig, frame):
        if len(self.SIG_QUEUE) < 5:
            self.SIG_QUEUE.append(sig)
            self.wakeup()


    def run(self):
        "Main master loop."
        self.start()
        util._setproctitle("master [%s]" % self.proc_name)

        # while True:
        #     try:
        #         sig = self.SIG_QUEUE.pop(0) if len(self.SIG_QUEUE) else None
        #         if sig is None:
        #             self.sleep()

        #             continue

        #         if sig not in self.SIG_NAMES:
        #             self.log.info("Ignoring unknown signal: %s", sig)
        #             continue

        #         signame = self.SIG_NAMES.get(sig)
        #         handler = getattr(self, "handle_%s" % signame, None)
        #         if not handler:
        #             self.log.error("Unhandled signal: %s", signame)
        #             continue
        #         self.log.info("Handling signal: %s", signame)
        #         handler()
        #         self.wakeup()
        #     except StopIteration:
        #         self.halt()
        #     except KeyboardInterrupt:
        #         self.halt()
        #     except HaltServer as inst:
        #         self.halt(reason=inst.reason, exit_status=inst.exit_status)
        #     except SystemExit:
        #         raise
        #     except Exception:
        #         self.log.info("Unhandled exception in main loop:\n%s",
        #                     traceback.format_exc())
        #         self.stop(False)
        #         if self.pidfile is not None:
        #             self.pidfile.unlink()
        #         sys.exit(-1)

    def handle_hup(self):
        """\
        HUP handling.
        - Reload configuration
        - Start the new worker processes with a new configuration
        - Gracefully shutdown the old worker processes
        """

        self.log.info("Hang up: %s", self.master_name)
        # self.reload()

    def handle_quit(self):
        "SIGQUIT handling"
        self.log.info("Quit: %s", self.master_name)
        # raise StopIteration

    def handle_int(self):
        "SIGINT handling"
        self.log.info("SigInt: %s", self.master_name)
        self.stop(False)
        # raise StopIteration

    def handle_term(self):
        "SIGTERM handling"
        self.log.info("Sigterm: %s", self.master_name)
        self.stop(False)
        # raise StopIteratioan

    def wakeup(self):
        """\
        Wake up the arbiter by writing to the PIPE
        """
        try:
            os.write(self.PIPE[1], b'.')
        except IOError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    def stop(self, graceful=True):
        """\
        Stop workers

        :attr graceful: boolean, If True (the default) workers will be
        killed gracefully  (ie. trying to wait for the current connection)
        """
        sig = signal.SIGQUIT
        if not graceful:
            sig = signal.SIGTERM
        limit = time.time() + self.cfg.graceful_timeout