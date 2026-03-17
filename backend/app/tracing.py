import functools
from opentelemetry import trace


def traced(name: str | None = None):
    """Decorator that wraps a function in an OpenTelemetry span.

    Usage:
        @traced()
        def fetch_users(): ...

        @traced("custom.span_name")
        def do_work(): ...
    """

    def decorator(fn):
        span_name = name or f"{fn.__module__}.{fn.__qualname__}"
        tracer = trace.get_tracer(fn.__module__)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with tracer.start_as_current_span(span_name):
                return fn(*args, **kwargs)

        return wrapper

    return decorator
