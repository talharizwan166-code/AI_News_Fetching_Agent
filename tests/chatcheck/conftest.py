import threading

import pytest

from chatcheck.mock_server import MockServer


@pytest.fixture
def mock_chatbot():
    with MockServer(("127.0.0.1", 0)) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        server.url = f"http://127.0.0.1:{server.server_port}"
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)
