import pytest
import scripts.config as cfg


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("WIKI_DIR", str(tmp_path / "wiki"))
    cfg._settings = None
    yield tmp_path
    cfg._settings = None
