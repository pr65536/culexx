# -*- coding: utf-8 -
#
# This file is part of culexx released under the MIT license.
# See the NOTICE for more information.

import copy
import grp
import inspect
try:
    import argparse
except ImportError: # python 2.6
    from . import argparse_compat as argparse
import os
import pwd
import sys
import textwrap
import logging

from . import __version__
from errors import ConfigError
from . import util
from gunicorn import six

KNOWN_SETTINGS = []
PLATFORM = sys.platform

def wrap_method(func):
    def _wrapped(instance, *args, **kwargs):
        return func(*args, **kwargs)
    return _wrapped


def make_settings(ignore=None):
    settings = {}
    ignore = ignore or ()
    for s in KNOWN_SETTINGS:
        setting = s()
        if setting.name in ignore:
            continue
        settings[setting.name] = setting.copy()
    return settings

class Config(object):

    def __init__(self, usage=None, prog=None):
        self.settings = make_settings()
        self.usage = usage
        self.prog = prog or os.path.basename(sys.argv[0])
        self.env_orig = os.environ.copy()

    def __getattr__(self, name):
        if name not in self.settings:
            raise AttributeError("No configuration setting for: %s" % name)
        return self.settings[name].get()

    def __setattr__(self, name, value):
        if name != "settings" and name in self.settings:
            raise AttributeError("Invalid access!")
        super(Config, self).__setattr__(name, value)

    def set(self, name, value):
        if name not in self.settings:
            raise AttributeError("No configuration setting for: %s" % name)
        self.settings[name].set(value)

    def parser(self):
        kwargs = {
            "usage": self.usage,
            "prog": self.prog
        }
        parser = argparse.ArgumentParser(**kwargs)
        parser.add_argument("-v", "--version",
                action="version", default=argparse.SUPPRESS,
                version="%(prog)s (version ***" +  __version__ + ")\n",
                help="show program's version number and exit")
        parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

        keys = list(self.settings)
        def sorter(k):
            return (self.settings[k].section, self.settings[k].order)

        keys = sorted(self.settings, key=self.settings.__getitem__)
        for k in keys:
            self.settings[k].add_option(parser)
        return parser

    @property
    def uid(self):
        return self.settings['user'].get()

    @property
    def gid(self):
        return self.settings['group'].get()

    @property
    def proc_name(self):
        pn = self.settings['proc_name'].get()
        if pn is not None:
            return pn
        else:
            return self.settings['default_proc_name'].get()

    @property
    def logger_class(self):
        uri = self.settings['logger_class'].get()

        logger_class = util.load_class(uri)

        return logger_class

    @property
    def is_ssl(self):
        return self.certfile or self.keyfile

    @property
    def ssl_options(self):
        opts = {}
        for attr in('certfile', 'keyfile', 'cert_reqs', 'ssl_version', \
                'ca_certs', 'suppress_ragged_eofs', 'do_handshake_on_connect',
                'ciphers'):

            # suppress_ragged_eofs/do_handshake_on_connect are booleans that can
            # be False hence we use hasattr instead of getattr(self, attr, None).
            if hasattr(self, attr):
                value = getattr(self, attr)
                opts[attr] = value
        return opts

    @property
    def env(self):
        raw_env = self.settings['raw_env'].get()
        env = {}

        if not raw_env:
            return env

        for e in raw_env:
            s = six.bytes_to_str(e)
            try:
                k, v = s.split('=')
            except ValueError:
                raise RuntimeError("environement setting %r invalid" % s)

            env[k] = v

        return env


class SettingMeta(type):
    def __new__(cls, name, bases, attrs):
        super_new = super(SettingMeta, cls).__new__
        parents = [b for b in bases if isinstance(b, SettingMeta)]
        if not parents:
            return super_new(cls, name, bases, attrs)

        attrs["order"] = len(KNOWN_SETTINGS)
        attrs["validator"] = wrap_method(attrs["validator"])

        new_class = super_new(cls, name, bases, attrs)
        new_class.fmt_desc(attrs.get("desc", ""))
        KNOWN_SETTINGS.append(new_class)
        return new_class

    def fmt_desc(cls, desc):
        desc = textwrap.dedent(desc).strip()
        setattr(cls, "desc", desc)
        setattr(cls, "short", desc.splitlines()[0])


class Setting(object):
    name = None
    value = None
    section = None
    cli = None
    validator = None
    type = None
    meta = None
    action = None
    default = None
    short = None
    desc = None
    nargs = None
    const = None


    def __init__(self):
        if self.default is not None:
            self.set(self.default)

    def add_option(self, parser):
        if not self.cli:
            return
        args = tuple(self.cli)

        help_txt = "%s [%s]" % (self.short, self.default)
        help_txt = help_txt.replace("%", "%%")

        kwargs = {
            "dest": self.name,
            "action": self.action or "store",
            "type": self.type or str,
            "default": None,
            "help": help_txt
        }

        if self.meta is not None:
            kwargs['metavar'] = self.meta

        if kwargs["action"] != "store":
            kwargs.pop("type")

        if self.nargs is not None:
            kwargs["nargs"] = self.nargs

        if self.const is not None:
            kwargs["const"] = self.const

        parser.add_argument(*args, **kwargs)

    def copy(self):
        return copy.copy(self)

    def get(self):
        return self.value

    def set(self, val):
        assert six.callable(self.validator), "Invalid validator: %s" % self.name
        self.value = self.validator(val)

    def __lt__(self, other):
        return (self.section == other.section and
                self.order < other.order)
    __cmp__ = __lt__

Setting = SettingMeta('Setting', (Setting,), {})


def validate_bool(val):
    if isinstance(val, bool):
        return val
    if not isinstance(val, six.string_types):
        raise TypeError("Invalid type for casting: %s" % val)
    if val.lower().strip() == "true":
        return True
    elif val.lower().strip() == "false":
        return False
    else:
        raise ValueError("Invalid boolean: %s" % val)


def validate_dict(val):
    if not isinstance(val, dict):
        raise TypeError("Value is not a dictionary: %s " % val)
    return val


def validate_pos_int(val):
    if not isinstance(val, six.integer_types):
        val = int(val, 0)
    else:
        # Booleans are ints!
        val = int(val)
    if val < 0:
        raise ValueError("Value must be positive: %s" % val)
    return val


def validate_string(val):
    if val is None:
        return None
    if not isinstance(val, six.string_types):
        raise TypeError("Not a string: %s" % val)
    return val.strip()


def validate_list_string(val):
    if not val:
        return []

    # legacy syntax
    if isinstance(val, six.string_types):
        val = [val]

    return [validate_string(v) for v in val]


def validate_string_to_list(val):
    val = validate_string(val)

    if not val:
        return []

    return [v.strip() for v in val.split(",") if v]


def validate_class(val):
    if inspect.isfunction(val) or inspect.ismethod(val):
        val = val()
    if inspect.isclass(val):
        return val
    return validate_string(val)


def validate_callable(arity):
    def _validate_callable(val):
        if isinstance(val, six.string_types):
            try:
                mod_name, obj_name = val.rsplit(".", 1)
            except ValueError:
                raise TypeError("Value '%s' is not import string. "
                                "Format: module[.submodules...].object" % val)
            try:
                mod = __import__(mod_name, fromlist=[obj_name])
                val = getattr(mod, obj_name)
            except ImportError as e:
                raise TypeError(str(e))
            except AttributeError:
                raise TypeError("Can not load '%s' from '%s'"
                    "" % (obj_name, mod_name))
        if not six.callable(val):
            raise TypeError("Value is not six.callable: %s" % val)
        if arity != -1 and arity != len(inspect.getargspec(val)[0]):
            raise TypeError("Value must have an arity of: %s" % arity)
        return val
    return _validate_callable


def validate_user(val):
    if val is None:
        return os.geteuid()
    if isinstance(val, int):
        return val
    elif val.isdigit():
        return int(val)
    else:
        try:
            return pwd.getpwnam(val).pw_uid
        except KeyError:
            raise ConfigError("No such user: '%s'" % val)


def validate_group(val):
    if val is None:
        return os.getegid()

    if isinstance(val, int):
        return val
    elif val.isdigit():
        return int(val)
    else:
        try:
            return grp.getgrnam(val).gr_gid
        except KeyError:
            raise ConfigError("No such group: '%s'" % val)

def validate_chdir(val):
    # valid if the value is a string
    val = validate_string(val)

    # transform relative paths
    path = os.path.abspath(os.path.normpath(os.path.join(util.getcwd(), val)))

    # test if the path exists
    if not os.path.exists(path):
        raise ConfigError("can't chdir to %r" % val)

    return path


def validate_file(val):
    if val is None:
        return None

    # valid if the value is a string
    val = validate_string(val)

     # transform relative paths
    path = os.path.abspath(os.path.normpath(os.path.join(util.getcwd(), val)))

    # test if the path exists
    if not os.path.exists(path):
        raise ConfigError("%r not found" % val)

    return path


def get_default_config_file():
    config_path = os.path.join(os.path.abspath(os.getcwd()),
            'culexx.conf.py')
    if os.path.exists(config_path):
        return config_path
    return None


class DefaultProcName(Setting):
    name = "default_proc_name"
    section = "Process Naming"
    validator = validate_string
    default = "culexx"
    desc = """\
        Internal setting that is adjusted for each type of application.
        """

class ConfigFile(Setting):
    name = "config"
    section = "Config File"
    cli = ["-c", "--config"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        The path to a Gunicorn config file.

        Only has an effect when specified on the command line or as part of an
        application specific configuration.
        """

class Debug(Setting):
    name = "debug"
    section = "Debugging"
    cli = ["--debug"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Turn on debugging in the server.

        This limits the number of worker processes to 1 and changes some error
        handling that's sent to clients.
        """

class Chdir(Setting):
    name = "chdir"
    section = "Server Mechanics"
    cli = ["--chdir"]
    validator = validate_chdir
    default = util.getcwd()
    desc = """\
        Chdir to specified directory before apps loading.
        """


class Daemon(Setting):
    name = "daemon"
    section = "Server Mechanics"
    cli = ["-D", "--daemon"]
    validator = validate_bool
    action = "store_true"
    default = False
    desc = """\
        Daemonize the Gunicorn process.

        Detaches the server from the controlling terminal and enters the
        background.
        """

class Env(Setting):
    name = "raw_env"
    action = "append"
    section = "Server Mechanics"
    cli = ["-e", "--env"]
    meta = "ENV"
    validator = validate_list_string
    default = []

    desc = """\
        Set environment variable (key=value).

        Pass variables to the execution environment. Ex.::

            $ culexx -b 127.0.0.1:8000 --env FOO=1 test:app

        and test for the foo variable environement in your application.
        """

class Pidfile(Setting):
    name = "pidfile"
    section = "Server Mechanics"
    cli = ["-p", "--pid"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
        A filename to use for the PID file.

        If not set, no PID file will be written.
        """

class User(Setting):
    name = "user"
    section = "Server Mechanics"
    cli = ["-u", "--user"]
    meta = "USER"
    validator = validate_user
    default = os.geteuid()
    desc = """\
        Switch worker processes to run as this user.

        A valid user id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getpwnam(value) or None to not change
        the worker process user.
        """

class Group(Setting):
    name = "group"
    section = "Server Mechanics"
    cli = ["-g", "--group"]
    meta = "GROUP"
    validator = validate_group
    default = os.getegid()
    desc = """\
        Switch worker process to run as this group.

        A valid group id (as an integer) or the name of a user that can be
        retrieved with a call to pwd.getgrnam(value) or None to not change
        the worker processes group.
        """

class Umask(Setting):
    name = "umask"
    section = "Server Mechanics"
    cli = ["-m", "--umask"]
    meta = "INT"
    validator = validate_pos_int
    type = int
    default = 0
    desc = """\
        A bit mask for the file mode on files written by Gunicorn.

        Note that this affects unix socket permissions.

        A valid value for the os.umask(mode) call or a string compatible with
        int(value, 0) (0 means Python guesses the base, so values like "0",
        "0xFF", "0022" are valid for decimal, hex, and octal representations)
        """

class ErrorLog(Setting):
    name = "errorlog"
    section = "Logging"
    cli = ["--error-logfile", "--log-file"]
    meta = "FILE"
    validator = validate_string
    default = '-'
    desc = """\
        The Error log file to write to.

        "-" means log to stderr.
        """

class Loglevel(Setting):
    name = "loglevel"
    section = "Logging"
    cli = ["--log-level"]
    meta = "LEVEL"
    validator = validate_string
    default = "info"
    desc = """\
        The granularity of Error log outputs.

        Valid level names are:

        * debug
        * info
        * warning
        * error
        * critical
        """

class LoggerClass(Setting):
    name = "logger_class"
    section = "Logging"
    cli = ["--logger-class"]
    meta = "STRING"
    validator = validate_class
    default = "lib.culexx.clogging.Logger"
    desc = """\
        The logger you want to use to log events in culexx.

        The default class (``lib.culexx.clogging.Logger``) handle most of
        normal usages in logging. It provides error and access logging.

        You can provide your own worker by giving culexx a
        python path to a subclass like culexx.glogging.Logger.
        Alternatively the syntax can also load the Logger class
        with `egg:culexx#simple`
        """

class LogConfig(Setting):
    name = "logconfig"
    section = "Logging"
    cli = ["--log-config"]
    meta = "FILE"
    validator = validate_string
    default = None
    desc = """\
    The log config file to use.
    Culexx uses the standard Python logging module's Configuration
    file format.
    """

class Syslog(Setting):
    name = "syslog"
    section = "Logging"
    cli = ["--log-syslog"]
    validator = validate_bool
    action = 'store_true'
    default = False
    desc = """\
    Send *Culexx* logs to syslog.
    """

class EnableStdioInheritance(Setting):
    name = "enable_stdio_inheritance"
    section = "Logging"
    cli = ["-R", "--enable-stdio-inheritance"]
    validator = validate_bool
    default = False
    action = "store_true"
    desc = """\
    Enable stdio inheritance

    Enable inheritance for stdio file descriptors in daemon mode.

    Note: To disable the python stdout buffering, you can to set the user
    environment variable ``PYTHONUNBUFFERED`` .
    """

class Procname(Setting):
    name = "proc_name"
    section = "Process Naming"
    cli = ["-n", "--name"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        A base to use with setproctitle for process naming.

        This affects things like ``ps`` and ``top``. If you're going to be
        running more than one instance of Gunicorn you'll probably want to set a
        name to tell them apart. This requires that you install the setproctitle
        module.

        It defaults to 'culexx'.
        """

class DefaultProcName(Setting):
    name = "default_proc_name"
    section = "Process Naming"
    validator = validate_string
    default = "culexx"
    desc = """\
        Internal setting that is adjusted for each type of application.
        """

class PythonPath(Setting):
    name = "pythonpath"
    section = "Server Mechanics"
    cli = ["--pythonpath"]
    meta = "STRING"
    validator = validate_string
    default = None
    desc = """\
        A directory to add to the Python path.

        e.g.
        '/home/djangoprojects/myproject'.
        """