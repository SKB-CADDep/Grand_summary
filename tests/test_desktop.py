from __future__ import annotations

import inspect

from desktop import run as desktop_run


def test_desktop_run_has_no_webengine():
    source = inspect.getsource(desktop_run)
    assert "QWebEngineView" not in source
    assert "QtWebEngine" not in source
    assert "require_frontend_build" not in source


def test_api_client_talks_to_app(client):
    from desktop.client import ApiClient

    api = ApiClient()
    try:
        me = api.me()
        assert "username" in me
        assert api.objects() == client.get("/api/objects").json()
    finally:
        api.close()


def test_native_ui_imports_without_webengine():
    from desktop.ui.window import MainWindow
    from desktop.ui.table_page import TablePage
    from desktop.ui.object_page import ObjectPage
    from desktop.ui.triangle_page import TrianglePage
    from desktop.ui.report_page import ReportPage

    assert MainWindow is not None
    assert TablePage is not None
    assert ObjectPage is not None
    assert TrianglePage is not None
    assert ReportPage is not None
    source = inspect.getsource(MainWindow)
    assert "QWebEngineView" not in source
