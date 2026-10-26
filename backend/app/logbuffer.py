"""In-memory ring buffer of recent (redacted) log lines for the diagnostics page."""

import logging
from collections import deque
from datetime import UTC, datetime

from app.logredact import RedactingFilter


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 200) -> None:
        super().__init__(level=logging.INFO)
        self.records: deque[dict[str, str]] = deque(maxlen=capacity)
        self.addFilter(RedactingFilter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        self.records.append(
            {
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": msg[:500],
            }
        )


_handler: RingBufferHandler | None = None


def install() -> RingBufferHandler:
    global _handler
    if _handler is None:
        _handler = RingBufferHandler()
        root = logging.getLogger()
        root.addHandler(_handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
    return _handler
