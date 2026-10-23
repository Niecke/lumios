"""
Tests for the @traced decorator and the tracing setup in main.py.
"""

import main
from tracing import traced


class TestTraced:
    def test_preserves_function_metadata(self):
        @traced()
        def sample():
            """Sample docstring."""

        assert sample.__name__ == "sample"
        assert sample.__doc__ == "Sample docstring."

    def test_executes_function(self):
        @traced()
        def add(a, b=1):
            return a + b

        assert add(2, b=3) == 5

    def test_custom_name_executes_function(self):
        @traced("custom.name")
        def work():
            return "done"

        assert work() == "done"


class TestInitCloudTrace:
    def test_disabled_does_not_touch_tracer_provider(self, monkeypatch):
        monkeypatch.setattr(main, "CLOUD_TRACE_ENABLED", False)
        from opentelemetry import trace

        before = trace.get_tracer_provider()
        main._init_cloud_trace(object())
        assert trace.get_tracer_provider() is before
