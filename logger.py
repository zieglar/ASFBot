import logging
DEFAULT_LOG_LEVEL = logging.DEBUG
DEFAULT_FORMATTER = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_HANDLER_MARKER = "_asfbot_console_handler"
_log_level = DEFAULT_LOG_LEVEL
logger = logging.getLogger("ASFBot")
logger.setLevel(_log_level)


def _ensure_console_handler(target_logger):
    for handler in target_logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            handler.setLevel(_log_level)
            handler.setFormatter(DEFAULT_FORMATTER)
            return handler

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(_log_level)
    handler.setFormatter(DEFAULT_FORMATTER)
    target_logger.addHandler(handler)
    return handler


def set_logger(name):
    global logger
    logger = logging.getLogger(name)
    logger.setLevel(_log_level)
    _ensure_console_handler(logger)
    return logger


def set_level(verbosity):
    global _log_level
    numeric_level = get_numeric_log_level(verbosity)
    _log_level = numeric_level
    logger.setLevel(numeric_level)
    for handler in logger.handlers:
        handler.setLevel(numeric_level)


def get_numeric_log_level(verbosity):
    numeric_level = getattr(logging, verbosity.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % verbosity)
    return numeric_level


def get_logger(name=None):
    if name:
        return logger.getChild(name)
    return logger


def add_file_handler(file_path, log_level=DEFAULT_LOG_LEVEL, formatter=DEFAULT_FORMATTER):
    fh = logging.FileHandler(file_path)
    fh.setLevel(log_level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
