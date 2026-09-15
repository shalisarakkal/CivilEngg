import logging
import sys
from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True


def configure_logging() -> None:
    """Configure structured, correlation-id-tagged logging.

    Request/response bodies are never logged here: only method, path, status,
    duration, and the correlation id, so extracted document text and question
    content never end up in application logs.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s")
    )
    handler.addFilter(CorrelationIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
