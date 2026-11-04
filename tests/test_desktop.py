from __future__ import annotations

import pytest

from desktop.run import pick_port, require_frontend_build


def test_pick_port_returns_free_tcp_port():
    port = pick_port()
    assert 1 <= port <= 65535


def test_require_frontend_build_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("desktop.run.dist_dir", lambda: tmp_path / "missing-dist")
    with pytest.raises(SystemExit):
        require_frontend_build()
