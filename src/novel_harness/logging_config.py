"""Safe standard-library logging configuration."""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure concise structured-ish logs without recording prompt bodies."""

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=("%(asctime)s %(levelname)s %(name)s event=%(message)s"),
        stream=sys.stderr,
        force=True,
    )
