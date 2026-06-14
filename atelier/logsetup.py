"""Minimal stdlib logging setup. No heavy imports at module load."""

import logging
import logging.handlers
import os

_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def get_logger(name, log_path=None):
    """Return a configured logging.Logger.

    INFO level, a StreamHandler, and (if log_path given) a rotating file handler.
    Idempotent: repeated calls with the same name do not stack handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(_FORMAT)

    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler)
        for h in logger.handlers
    )
    if not has_stream:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    if log_path:
        target = os.path.abspath(str(log_path))
        already = any(
            isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "baseFilename", None) == target
            for h in logger.handlers
        )
        if not already:
            fh = logging.handlers.RotatingFileHandler(target, maxBytes=5_000_000, backupCount=3)
            fh.setFormatter(fmt)
            logger.addHandler(fh)

    return logger
