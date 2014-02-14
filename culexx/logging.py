import os, sys
import logging
from logging.config import fileConfig

LOGGING_DEFAULTS = {
    'version': 1,
    'disable_existing_loggers': False,
    
    'loggers': {
        '': {
            # this sets root level logger to log debug and higher level
            # logs to console. All other loggers inherit settings from
            # root level logger.
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False, # this tells logger to send logging message
                                # to its parent (will send if set to True)
        },
        'culexx.error': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': True,
            "qualname": "culexx.error",
        },
    },
    'handlers': {
        'console': {
            # logging handler that outputs log messages to terminal
            'class': 'logging.StreamHandler',
            'level': 'DEBUG', # message level to be written to console
            'formatter': "generic",
            'stream': "sys.stdout"
        },
    },
    'formatters': {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "class": "logging.Formatter"
        }
    }
}

default_logger = logging.getLogger()
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
default_logger.addHandler(ch)

def loggers():
    """ get list of all loggers """
    root = logging.root
    existing = root.manager.loggerDict.keys()
    return [logging.getLogger(name) for name in existing]

class Logger(object):

    LOG_LEVELS = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG
    }

    error_fmt = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
    datefmt = r"%Y-%m-%d %H:%M:%S"

    syslog_fmt = "[%(process)d] %(message)s"

    def __init__(self, cfg):
        self.error_log = logging.getLogger("culexx.error")
        self.error_log.propagate = False
        self.error_handlers = []
        self.cfg = cfg
        self.setup(cfg)

    def setup(self, cfg):
        loglevel = self.LOG_LEVELS.get(cfg.loglevel.lower(), logging.INFO)
        self.error_log.setLevel(loglevel)

        # set gunicorn.error handler
        self._set_handler(self.error_log, cfg.errorlog,
                logging.Formatter(self.error_fmt, self.datefmt))

        if cfg.logconfig:
            if os.path.exists(cfg.logconfig):
                fileConfig(cfg.logconfig, defaults=LOGGING_DEFAULTS,
                        disable_existing_loggers=False)
            else:
                raise RuntimeError("Error: log config '%s' not found" %
                        cfg.logconfig)

    def critical(self, msg, *args, **kwargs):
        self.error_log.critical(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.error_log.error(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.error_log.warning(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.error_log.info(msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self.error_log.debug(msg, *args, **kwargs)

    def exception(self, msg, *args):
        self.error_log.exception(msg, *args)

    def log(self, lvl, msg, *args, **kwargs):
        if isinstance(lvl, basestring):
            lvl = self.LOG_LEVELS.get(lvl.lower(), logging.INFO)
        self.error_log.log(lvl, msg, *args, **kwargs)

    def _get_culexx_handler(self, log):
        for h in log.handlers:
            if getattr(h, "_culexx", False) == True:
                return h

    def _set_handler(self, log, output, fmt):
        # remove previous gunicorn log handler
        h = self._get_culexx_handler(log)
        if h:
            log.handlers.remove(h)

        if output is not None:
            if output == "-":
                h = logging.StreamHandler()
            else:
                pass
                # util.check_is_writeable(output)
                # h = logging.FileHandler(output)

            h.setFormatter(fmt)
            h._gunicorn = True
            log.addHandler(h)
