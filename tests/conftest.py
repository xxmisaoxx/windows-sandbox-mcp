import pytest

from winsandbox_mcp.session import SessionManager


@pytest.fixture
def session(tmp_path):
    manager = SessionManager(tmp_path)
    manager.session = "a" * 32
    manager.directory = tmp_path / manager.session
    manager.inbox = manager.directory / "inbox"
    manager.outbox = manager.directory / "outbox"
    manager.evidence = manager.directory / "artifacts"
    for path in (manager.inbox, manager.outbox, manager.evidence):
        path.mkdir(parents=True)
    manager.state = "ready"
    return manager
