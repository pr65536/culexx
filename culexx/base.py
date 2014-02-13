import os
import sys
from . import util
from .arbiter import Arbiter
from .config import Config, get_default_config_file
import traceback

class Base(object):

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
            Arbiter(self).run()
        except RuntimeError as e:
            sys.stderr.write("\nError: %s\n\n" % e)
            sys.stderr.flush()
            sys.exit(1)