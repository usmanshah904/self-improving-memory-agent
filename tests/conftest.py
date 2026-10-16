import pytest


@pytest.fixture(autouse=True)
def temp_memory(tmp_path, monkeypatch):
    """Every test gets its own empty memory store."""
    path = tmp_path / "memories.json"
    monkeypatch.setenv("MEMORY_FILE", str(path))
    return path
