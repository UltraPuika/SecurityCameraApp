import logging
import re

_URL_CREDS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]*:[^/\s@]*@")
_ENCODED_URL_CREDS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*%3A%2F%2F)[^\s&\"']*?%40")
# go2rtc registration URLs carry the full upstream source (with credentials) in src=.
_SRC_PARAM = re.compile(r"(?i)([?&]src=)[^&\s\"']+")
_KEYED = re.compile(
    r"(?i)(\"?(?:password|passwd|app_?secret|access_?token|token|sign|authorization)\"?\s*[:=]\s*\"?)"
    r"([^\"\s,}&]+)"
)


def redact(text: str) -> str:
    text = _URL_CREDS.sub(r"\1***:***@", text)
    text = _ENCODED_URL_CREDS.sub(r"\1***%40", text)
    text = _SRC_PARAM.sub(r"\1***", text)
    return _KEYED.sub(r"\1***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def install() -> None:
    # httpx logs every request URL at INFO; those can contain stream sources.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    f = RedactingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logger = logging.getLogger(name)
        if not any(isinstance(x, RedactingFilter) for x in logger.filters):
            logger.addFilter(f)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(x, RedactingFilter) for x in handler.filters):
            handler.addFilter(f)
