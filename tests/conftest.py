import pytest
import scripts.config as cfg


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("WIKI_DIR", str(tmp_path / "wiki_content" / "legacy"))
    cfg._settings = None
    yield tmp_path
    cfg._settings = None


def pytest_collection_modifyitems(config, items):
    etl_p0_files = {
        "tests/test_db.py",
        "tests/test_worker.py",
        "tests/test_integration.py",
    }
    for item in items:
        nodeid = item.nodeid
        test_file = nodeid.split("::", 1)[0]
        if test_file in etl_p0_files:
            item.add_marker(pytest.mark.p0)
            item.add_marker(pytest.mark.suite_etl)
        elif test_file == "tests/test_mcp_server.py":
            item.add_marker(pytest.mark.suite_fastmcp)
        else:
            item.add_marker(pytest.mark.suite_legacy)
