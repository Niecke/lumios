"""services/worker_probe.py: the /live and /ready endpoints of a worker pod."""

import urllib.error
import urllib.request

import pytest

from services.worker_probe import ProbeState, start_probe_server


@pytest.fixture
def serve():
    servers = []

    def start(state):
        server = start_probe_server(state, 0, host="127.0.0.1")
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_ready_is_503_until_the_schema_is_there(serve):
    state = ProbeState()
    base = serve(state)

    assert _get(base + "/ready")[0] == 503
    state.set_ready(True)
    assert _get(base + "/ready") == (200, "ready")
    state.set_ready(False)
    assert _get(base + "/ready")[0] == 503


def test_live_is_200_whatever_the_schema_state(serve):
    state = ProbeState()
    base = serve(state)

    assert _get(base + "/live") == (200, "live")
    state.set_ready(True)
    assert _get(base + "/live")[0] == 200


def test_live_is_503_when_the_database_was_not_seen_for_too_long(serve):
    state = ProbeState(live_max_age=0)
    base = serve(state)

    assert _get(base + "/live")[0] == 503


def test_mark_db_ok_keeps_the_worker_live():
    state = ProbeState(live_max_age=60)
    state._last_db_ok -= 120
    assert not state.is_live()

    state.mark_db_ok()

    assert state.is_live()


def test_unknown_path_is_404_and_query_string_is_ignored(serve):
    state = ProbeState()
    base = serve(state)

    assert _get(base + "/other")[0] == 404
    assert _get(base + "/live?x=1")[0] == 200
