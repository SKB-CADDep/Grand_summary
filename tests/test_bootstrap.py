from __future__ import annotations

from src import bootstrap


def test_core_modules_are_importable():
    assert bootstrap._core_missing() == []


def test_skip_bootstrap_env(monkeypatch):
    called = []
    monkeypatch.setenv("GRAND_SUMMARY_SKIP_BOOTSTRAP", "1")
    monkeypatch.setattr(bootstrap, "_run", lambda *args, **kwargs: called.append(args))
    bootstrap.ensure_python_packages()
    assert called == []
