"""Add actual rejection-log evidence without altering the frozen worker or fakes."""

import logging
import re
from unittest.mock import patch

from . import worker

_REASON = re.compile(r"Unsafe draft: (?:HTML or markdown comment|role delimiter|control character|"
                     r"generator instruction or template fragment|article instruction echo \(requested identifier\)|"
                     r"email address outside article and allowlist|URL outside article and allowlist)\Z")


class RejectionLogHandler(logging.Handler):
    def __init__(self, trace):
        super().__init__(logging.WARNING)
        self.trace = trace

    def emit(self, record):
        # Only persist the target's known safe categorical validation reason.
        # Never persist arbitrary provider/agent log messages or exception values.
        if (record.name == "src.generator" and record.msg == "Draft validation rejected: %s"
                and isinstance(record.args, tuple) and len(record.args) == 1
                and isinstance(record.args[0], str) and _REASON.fullmatch(record.args[0])):
            self.trace.emit("draft_rejected", {"logger": record.name, "level": record.levelname,
                                               "reason": record.args[0]})


def main():
    original = worker.execute

    def execute(case, trace, directory, broker=None):
        handler = RejectionLogHandler(trace)
        logger = logging.getLogger("src.generator")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        logging.getLogger().addHandler(logging.NullHandler())
        logging.disable(logging.NOTSET)
        try:
            with patch("logging.disable", lambda level: None):
                return original(case, trace, directory, broker)
        finally:
            logger.removeHandler(handler)

    with patch.object(worker, "execute", execute):
        return worker.main()


if __name__ == "__main__":
    raise SystemExit(main())
