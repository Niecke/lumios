import json
import logging
import os
import sys
import threading


def setup_app_logger(app) -> None:
    app.logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(JsonFormatter())
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "log_type"):
            log_type = record.log_type
        elif record.name == "gunicorn.access":
            log_type = "request"
        elif record.name.startswith(("gunicorn", "alembic", "flask_migrate")):
            log_type = "startup"
        else:
            log_type = "request"

        entry = {
            "timestamp": record.created,
            "type": log_type,
            "msg": record.getMessage(),
            "level": record.levelname.lower(),
            "method": f"{record.module}.{record.funcName}",
            "pid": os.getpid(),
            "tid": threading.get_ident(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)
