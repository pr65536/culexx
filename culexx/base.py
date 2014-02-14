import os
import sys
from . import util
from .arbiter import Arbiter
from .config import Config, get_default_config_file
import traceback

class Base(object):

    START_CTX = {}

    PIPE = []

    SIG_QUEUE = []

    SIGNALS = [getattr(signal, "SIG%s" % x) \
            for x in "HUP QUIT INT TERM".split()]

    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )

    def __init__(self, usage=None, prog=None):
        self.usage = usage
        self.cfg = None
        self.prog = prog
        self.logger = None
        self.do_load_config()

    def init(self, parser, opts, args):
        if len(args) != 1:
            parser.error("No application module specified.")

        self.cfg.set("default_proc_name", args[0])
        self.app_uri = args[0]

    def do_load_config(self):
        try:
            self.load_config()
        except Exception as e:
            sys.stderr.write("\nError: %s\n" % str(e))
            sys.stderr.flush()
            sys.exit(1)

    def load_config_from_file(self, filename):

        if not os.path.exists(filename):
            raise RuntimeError("%r doesn't exist" % filename)

        cfg = {
            "__builtins__": __builtins__,
            "__name__": "__config__",
            "__file__": filename,
            "__doc__": None,
            "__package__": None
        }
        try:
            execfile(filename, cfg, cfg)
        except Exception:
            print("Failed to read config file: %s" % filename)
            traceback.print_exc()
            sys.exit(1)

        for k, v in cfg.items():
            # Ignore unknown names
            if k not in self.cfg.settings:
                continue
            try:
                self.cfg.set(k.lower(), v)
            except:
                sys.stderr.write("Invalid value for %s: %s\n\n" % (k, v))
                raise

        return cfg

    def load_config(self):
        # init configuration
        self.cfg = Config(self.usage, prog=self.prog)

        # parse console args
        parser = self.cfg.parser()

        args = parser.parse_args()

        # optional settings from apps
        cfg = self.init(parser, args, args.args)

        if args.config:
            self.load_config_from_file(args.config)
        else:
            default_config = get_default_config_file()
            if default_config is not None:
                self.load_config_from_file(default_config)

        # Lastly, update the configuration with any command line
        # settings.
        for key, val in args.__dict__.items():
            if val is None:
                continue
            if key == "args":
                continue
            self.cfg.set(key.lower(), val)

    def load_mosqapp(self):
        self.chdir()

        # load the app
        return util.import_app(self.app_uri)

    @property
    def mosq_app(self):
        return self.load_mosqapp()

    def chdir(self):
        # chdir to the configured path before loading,
        # default is the current dir
        os.chdir(self.cfg.chdir)

        # add the path to sys.path
        sys.path.insert(0, self.cfg.chdir)


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


    def run_app(self):

        os.environ["SERVER_SOFTWARE"] = "culexx"

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

    def run(self):
        # if self.cfg.check_config:
        #     try:
        #         self.load()
        #     except:
        #         sys.stderr.write("\nError while loading the application:\n\n")
        #         traceback.print_exc()
        #         sys.stderr.flush()
        #         sys.exit(1)
        #     sys.exit(0)

        # if self.cfg.spew:
        #     debug.spew()

        # if self.cfg.daemon:
        # util.daemonize(False)

        # set python paths
        if self.cfg.pythonpath and self.cfg.pythonpath is not None:
            paths = self.cfg.pythonpath.split(",")
            for path in paths:
                pythonpath = os.path.abspath(path)
                if pythonpath not in sys.path:
                    sys.path.insert(0, pythonpath)

        try:
            self.run_app()
        except RuntimeError as e:
            sys.stderr.write("\nError: %s\n\n" % e)
            sys.stderr.flush()
            sys.exit(1)
