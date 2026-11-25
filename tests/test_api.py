from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook


def _triangle_file(path: Path) -> Path:
    wb = Workbook()
    sheet = wb.active
    sheet["A3"] = "Наименование параметра"
    sheet["B3"] = "1"
    sheet["C3"] = "2"
    sheet["A10"] = "Высота сопловой лопатки, мм"
    sheet["B10"] = 120
    sheet["C10"] = 125
    sheet["A47"] = "Высота РЛ, мм"
    sheet["B47"] = 80
    wb.save(path)
    return path


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["user"]
    assert data["app"] == "grand_summary"


def test_me(client):
    response = client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["username"]
    assert response.json()["guide_seen"] is False


def test_guide_seen_once_per_user(client):
    first = client.get("/api/me").json()
    assert first["guide_seen"] is False
    marked = client.post("/api/me/guide-seen")
    assert marked.status_code == 200
    assert marked.json()["guide_seen"] is True
    assert client.get("/api/me").json()["guide_seen"] is True
    other = client.get("/api/me", headers={"X-Remote-User": "new.user"}).json()
    assert other["guide_seen"] is False


def test_history_preferences_persist_per_user(client):
    initial = client.get("/api/me/preferences")
    assert initial.status_code == 200
    assert initial.json() == {
        "history_position": "right",
        "history_panel_open": True,
        "history_right_width": 360,
        "history_bottom_height": 260,
        "configured": False,
    }

    saved = client.put(
        "/api/me/preferences",
        json={
            "history_position": "bottom",
            "history_panel_open": False,
            "history_right_width": 420,
            "history_bottom_height": 320,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["configured"] is True

    reopened = client.get("/api/me/preferences")
    assert reopened.json() == saved.json()
    other_user = client.get(
        "/api/me/preferences", headers={"X-Remote-User": "another.user"}
    )
    assert other_user.status_code == 200
    assert other_user.json()["configured"] is False
    assert other_user.json()["history_position"] == "right"


def test_objects_loaded_from_shared_catalog(client):
    response = client.get("/api/objects")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["external_id"] == "101"
    assert data[0]["name"] == "ТЭЦ-1 (ст.3) К-200 (зав.T-101)"


def test_create_object_does_not_change_catalog_file(client):
    from src.paths import objects_database_path

    catalog_path = objects_database_path()
    original = catalog_path.read_text(encoding="utf-8")
    response = client.post(
        "/api/objects",
        json={
            "factory_number": "T-202",
            "turbine_name": "К-300",
            "station_name": "ТЭЦ-2",
            "station_number": "5",
            "series_turbines": "К-300",
            "kind": "steam",
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "ТЭЦ-2 (ст.5) К-300 (зав.T-202)"
    assert catalog_path.read_text(encoding="utf-8") == original
    names = [item["name"] for item in client.get("/api/objects").json()]
    assert "ТЭЦ-2 (ст.5) К-300 (зав.T-202)" in names


def test_default_objects_catalog_is_local_test_folder(monkeypatch):
    monkeypatch.delenv("GRAND_SUMMARY_OBJECTS_FILE", raising=False)
    monkeypatch.delenv("GRAND_SUMMARY_OBJECTS_DIR", raising=False)
    from src.paths import objects_database_path, project_root

    path = objects_database_path()
    assert path == project_root() / "временно бд объектов для тестов" / "projects.json"
    assert path.is_file()


def test_workbook_requires_object_and_table(client):
    objects = client.get("/api/objects").json()
    object_id = objects[0]["id"]
    opened = client.post("/api/workbooks", json={"object_id": object_id})
    assert opened.status_code == 200
    workbook_id = opened.json()["id"]
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog")
    assert catalog.status_code == 200
    assert len(catalog.json()["parameters"]) > 50
    assert len(catalog.json()["columns"]) >= 39


def test_confirm_requires_comment(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    response = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "100", "comment": ""},
    )
    assert response.status_code == 422


def test_draft_confirm_history_unsaved(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    draft = client.patch(
        f"/api/workbooks/{workbook_id}/cells/r010/s1",
        json={"value": "111"},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    unsaved = client.get(f"/api/workbooks/{workbook_id}/unsaved")
    assert unsaved.status_code == 200
    assert unsaved.json()[0]["parameter_key"] == "r010"
    confirm = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "111", "comment": "Уточнение по тепловому расчёту"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"
    history = client.get(f"/api/workbooks/{workbook_id}/cells/r010/s1/history")
    assert history.status_code == 200
    item = history.json()[0]
    assert item["new_value"] == "111"
    assert item["comment"] == "Уточнение по тепловому расчёту"
    assert item["author"]
    assert client.get(f"/api/workbooks/{workbook_id}/unsaved").json() == []


def test_add_cell_comment_keeps_value_and_status(client):
    workbook_id = _workbook_id(client)
    confirmed = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "100", "comment": "Исходное подтверждение"},
    )
    assert confirmed.status_code == 200
    original_status = confirmed.json()["status"]
    original_value = confirmed.json()["value"]

    response = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/comment",
        json={"comment": "Комментарий без изменения значения", "expected_updated_at": confirmed.json()["updated_at"]},
    )

    assert response.status_code == 200
    assert response.json()["value"] == original_value
    assert response.json()["status"] == original_status
    history = client.get(f"/api/workbooks/{workbook_id}/cells/r010/s1/history")
    assert history.status_code == 200
    latest = history.json()[-1]
    assert latest["old_value"] == original_value
    assert latest["new_value"] == original_value
    assert latest["comment"] == "Комментарий без изменения значения"
    last_comment = client.get(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/last-comment"
    )
    assert last_comment.status_code == 200
    assert last_comment.json() == {"comment": "Комментарий без изменения значения"}


def test_reader_can_toggle_unification_but_values_stay_locked(client, monkeypatch):
    from src.services import acl

    workbook_id = _workbook_id(client)
    username = client.get("/api/me").json()["username"]
    acl_config = {"editors": ["another-user"], "readers": ["*"]}
    monkeypatch.setattr(acl, "_load", lambda: acl_config)
    url = f"/api/workbooks/{workbook_id}/cells/r010/s1"

    unified = client.patch(f"{url}/unification", json={"unified": True})
    assert unified.status_code == 200
    assert unified.json()["unified"] is True

    acl_config["editors"] = [username]
    blocked_edit = client.patch(url, json={"value": "999"})
    assert blocked_edit.status_code == 400
    assert "унифицированная" in blocked_edit.json()["detail"].lower()

    acl_config["editors"] = ["another-user"]
    unmarked = client.patch(f"{url}/unification", json={"unified": False})
    assert unmarked.status_code == 200
    assert unmarked.json()["unified"] is False


def test_import_triangle(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]

    def make_file(geometry_value: str, flow_value: str) -> BytesIO:
        workbook = Workbook()
        geometry = workbook.active
        geometry.title = "Геом. данные"
        geometry["A1"] = geometry_value
        flow_path = workbook.create_sheet("Проточная часть")
        flow_path["B2"] = flow_value
        workbook.create_sheet("Лист для игнорирования")["A1"] = "Не импортировать"
        stream = BytesIO()
        workbook.save(stream)
        stream.seek(0)
        return stream

    first_upload = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", make_file("Геометрия v1", "Проточная часть v1"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert first_upload.status_code == 200
    first_sheets = first_upload.json()["sheets"]
    assert [sheet["name"] for sheet in first_sheets] == ["Геом. данные", "Проточная часть"]
    assert first_sheets[0]["rows"][0][0] == "Геометрия v1"
    assert first_sheets[1]["rows"][1][1] == "Проточная часть v1"
    assert len(first_sheets) == 2

    second_upload = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", make_file("Геометрия v2", "Проточная часть v2"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert second_upload.status_code == 200
    stored_sheets = client.get(f"/api/workbooks/{workbook_id}/triangles")
    assert stored_sheets.status_code == 200
    assert len(stored_sheets.json()) == 2
    assert stored_sheets.json()[0]["rows"][0][0] == "Геометрия v2"
    assert stored_sheets.json()[1]["rows"][1][1] == "Проточная часть v2"
    assert client.get(f"/api/workbooks/{workbook_id}/versions").json() == []


def _triangle_sync_file(
    stage_label: str,
    angle_value: float | None = None,
    profile_value: str | None = None,
) -> BytesIO:
    workbook = Workbook()
    geometry = workbook.active
    geometry.title = "Геом. данные"
    geometry["B11"] = stage_label
    geometry["C11"] = 3.555
    geometry["D11"] = 0.5
    geometry["E11"] = 123.456
    geometry["F11"] = 0.754
    flow_path = workbook.create_sheet("Проточная часть")
    flow_path["B11"] = stage_label
    flow_path["D11"] = 1.256
    flow_path["R11"] = "ручное значение"
    if profile_value is not None:
        flow_path["Q11"] = profile_value
    if angle_value is not None:
        flow_path["H11"] = angle_value
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def test_sync_selected_triangle_cells(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    client.post(
        f"/api/workbooks/{workbook_id}/cells/r011/s1/confirm",
        json={"value": "preserve", "comment": "Исходное значение"},
    )
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", _triangle_sync_file(stage_label), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200
    assert imported.json()["sheets"][0]["rows"][10][2] == "3,56"
    assert imported.json()["sheets"][0]["rows"][10][4] == "123,46"

    response = client.post(
        f"/api/workbooks/{workbook_id}/sync-triangles",
        json={"mode": "selected", "cells": [{"sheet_key": "geometry", "row": 11, "column": 5}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 1
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{workbook_id}").json()["cells"]
    }
    assert cells[("r010", "s1")]["value"] == "123,46"
    assert cells[("r010", "s1")]["status"] == "triangle"
    assert cells[("r011", "s1")]["value"] == "preserve"
    history = client.get(f"/api/workbooks/{workbook_id}/cells/r010/s1/history").json()
    assert "треугольников" in history[0]["comment"]


def test_sync_selected_unmapped_cell_to_chosen_parameter(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", _triangle_sync_file(stage_label, profile_value="Тз, Д-00123"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text

    response = client.post(
        f"/api/workbooks/{workbook_id}/sync-triangles",
        json={
            "mode": "selected",
            "target_parameter_key": "r016",
            "cells": [
                {"sheet_key": "flow_path", "row": 11, "column": 18},
                {"sheet_key": "flow_path", "row": 11, "column": 4},
                {"sheet_key": "flow_path", "row": 11, "column": 17},
            ],
        },
    )
    assert response.status_code == 200, response.text
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{workbook_id}").json()["cells"]
    }
    assert cells[("r016", "s1")]["value"] == "ручное значение"
    assert cells[("r013", "s1")]["value"] == "1,26"
    assert cells[("r060", "s1")]["value"] == "Тз"
    assert cells[("r061", "s1")]["value"] == "Д-00123"


def test_sync_triangle_installation_angle_uses_degrees_minutes_seconds(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", _triangle_sync_file(stage_label, 12.345678), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["sheets"][1]["rows"][10][7] == "12,345678"

    response = client.post(
        f"/api/workbooks/{workbook_id}/sync-triangles",
        json={"mode": "selected", "cells": [{"sheet_key": "flow_path", "row": 11, "column": 8}]},
    )
    assert response.status_code == 200, response.text
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{workbook_id}").json()["cells"]
    }
    assert cells[("r007", "s1")]["value"] == '12°20\'44"'


def test_sync_triangle_partiality_percentage_to_fraction(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", _triangle_sync_file(stage_label), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text

    response = client.post(
        f"/api/workbooks/{workbook_id}/sync-triangles",
        json={"mode": "selected", "cells": [{"sheet_key": "geometry", "row": 11, "column": 3}]},
    )
    assert response.status_code == 200, response.text
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{workbook_id}").json()["cells"]
    }
    assert cells[("r011", "s1")]["value"] == "0,0356"


def test_sync_all_triangle_parameters_replaces_mapped_cells(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    sheet_id = client.post(f"/api/workbooks/{workbook_id}/sheets", json={"name": "Лист ИД"}).json()["id"]
    for parameter_key, value in (("r014", "777"), ("r010", "old"), ("r016", "keep")):
        client.post(
            f"/api/workbooks/{sheet_id}/cells/{parameter_key}/s1/confirm",
            json={"value": value, "comment": "Исходное значение"},
        )
    client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", _triangle_sync_file(stage_label), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    response = client.post(f"/api/workbooks/{sheet_id}/sync-triangles", json={"mode": "all"})
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 4
    assert response.json()["cleared"] == 0
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{sheet_id}").json()["cells"]
    }
    assert cells[("r008", "s1")]["value"] == "0,75"
    assert cells[("r009", "s1")]["value"] == "5000"
    assert cells[("r010", "s1")]["value"] == "old"
    assert cells[("r011", "s1")]["value"] == "0,0356"
    assert cells[("r013", "s1")]["value"] == "1,26"
    assert cells[("r014", "s1")]["value"] == "777"
    assert cells[("r016", "s1")]["value"] == "keep"


def test_sync_all_uses_requested_triangle_coordinates(client):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    stage_label = client.get(f"/api/workbooks/{workbook_id}/catalog").json()["columns"][0]["label"]
    sheet_id = client.post(f"/api/workbooks/{workbook_id}/sheets", json={"name": "Лист ИД"}).json()["id"]
    client.post(
        f"/api/workbooks/{sheet_id}/cells/r016/s1/confirm",
        json={"value": "manual", "comment": "Не переносить автоматически"},
    )

    source = Workbook()
    geometry = source.active
    geometry.title = "Геом. данные"
    geometry["B11"] = stage_label
    for address, value in {
        "C11": 3.5, "D11": 1.25, "E11": 999, "F11": 0.5, "G11": 52,
        "H11": 2.34, "J11": 0.6, "K11": 54,
    }.items():
        geometry[address] = value
    flow_path = source.create_sheet("Проточная часть")
    flow_path["B11"] = stage_label
    for address, value in {
        "C11": "Профиль СЛ", "D11": 100, "E11": 101, "F11": 102,
        "G11": 103, "H11": 104, "I11": 999, "J11": "Профиль РЛ",
        "K11": 105, "L11": 106, "N11": 107, "Q11": "Тз, Д-00123",
        "W11": 108, "X11": 109, "AB11": 110, "AC11": 111, "AE11": 112,
    }.items():
        flow_path[address] = value
    stream = BytesIO()
    source.save(stream)
    stream.seek(0)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangle.xlsx", stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    triangle_sheets = client.get(f"/api/workbooks/{workbook_id}/triangles").json()
    flow_coordinates = next(sheet for sheet in triangle_sheets if sheet["key"] == "flow_path")["coordinate_mapping"]
    assert flow_coordinates["24"] == ["r022"]

    response = client.post(f"/api/workbooks/{sheet_id}/sync-triangles", json={"mode": "all"})
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 24
    cells = {
        (cell["parameter_key"], cell["column_key"]): cell["value"]
        for cell in client.get(f"/api/workbooks/{sheet_id}").json()["cells"]
    }
    expected = {
        "r006": "Профиль СЛ", "r007": "104°00'00\"", "r008": "0,5", "r009": "12500",
        "r010": "101", "r011": "0,035", "r012": "102", "r013": "100",
        "r014": "52", "r015": "103", "r022": "109", "r026": "110",
        "r035": "111", "r036": "112", "r043": "Профиль РЛ", "r047": "106",
        "r048": "105", "r049": "54", "r050": "107", "r051": "0,6",
        "r052": "23400", "r060": "Тз", "r061": "Д-00123", "r083": "108",
    }
    assert {key: cells[(key, "s1")] for key in expected} == expected
    assert cells[("r016", "s1")] == "manual"


def test_report_preview_and_docx(client):
    from docx import Document
    from docx.oxml.ns import qn

    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "150", "comment": "Первая выдача"},
    )
    version = client.post(
        f"/api/workbooks/{workbook_id}/versions",
        json={"kind": "issued", "description": "Выдано"},
    ).json()
    client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "155", "comment": "Корректировка высоты"},
    )
    preview = client.get(
        f"/api/workbooks/{workbook_id}/report-preview",
        params={"report_type": "short", "compare_version_id": version["id"]},
    )
    assert preview.status_code == 200
    tables = preview.json()["tables"]
    changed = False
    for table in tables:
        for row in table["rows"]:
            if row["parameter_key"] == "r010":
                changed = row["cells"][0]["changed"]
    assert changed
    report = client.post(
        f"/api/workbooks/{workbook_id}/reports",
        json={
            "type": "short",
            "compare_version_id": version["id"],
            "selected_parameter_keys": ["r010"],
        },
    )
    assert report.status_code == 200
    assert report.content[:2] == b"PK"
    assert "Уточнение по тепловому расчёту".encode("utf-8") not in report.content
    assert "Корректировка высоты".encode("utf-8") not in report.content
    report_document = Document(BytesIO(report.content))
    baseline_changed_cell = next(
        cell
        for table in report_document.tables
        for row in table.rows
        for cell in row.cells
        if cell.text == "155"
    )
    assert baseline_changed_cell._tc.tcPr.find(qn("w:shd")) is None
    with ZipFile(BytesIO(report.content)) as archive:
        document_xml = archive.read("word/document.xml")
    assert "Высота лопаток lc".encode("utf-8") in document_xml
    assert "Ширина профиля в корне".encode("utf-8") not in document_xml

    client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "160"},
    )
    automatic_preview = client.get(
        f"/api/workbooks/{workbook_id}/report-preview",
        params={"report_type": "short"},
    )
    assert automatic_preview.status_code == 200
    auto_changed = next(
        row["cells"][0]["changed"]
        for table in automatic_preview.json()["tables"]
        for row in table["rows"]
        if row["parameter_key"] == "r010"
    )
    assert auto_changed


def test_export_report_table_docx(client):
    from docx import Document
    from docx.oxml.ns import qn

    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    confirmed = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "150"},
    )
    draft = client.patch(
        f"/api/workbooks/{workbook_id}/cells/r011/s1",
        json={"value": "151"},
    )
    assert confirmed.status_code == 200
    assert draft.status_code == 200
    response = client.post(
        f"/api/workbooks/{workbook_id}/export-report-table",
        json={
            "selected_parameter_keys": ["r010", "r011"],
            "selected_column_keys": ["s1"],
            "table_number": 7,
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    document = Document(BytesIO(response.content))
    section = document.sections[0]
    assert section.page_width > section.page_height
    data_cells = {
        row.cells[2].text: row.cells[2]
        for row in document.tables[0].rows[1:]
        if row.cells[2].text in {"150", "151"}
    }
    confirmed_shading = data_cells["150"]._tc.tcPr.find(qn("w:shd"))
    assert confirmed_shading is not None
    assert confirmed_shading.get(qn("w:fill")) == "C8E6C9"
    assert data_cells["151"]._tc.tcPr.find(qn("w:shd")) is None
    document_text = " ".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    assert "Таблица 7 – Данные по направляющим лопаткам и диафрагмам ступеней ЦСД" in document_text
    assert "К-200" in document_text
    assert "ТЭЦ-1" in document_text
    assert "T-101" in document_text
    assert "Высота лопаток lc" in document_text


def _workbook_id(client) -> str:
    objects = client.get("/api/objects").json()
    return client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]


def test_export_excel_current_and_all_sheets(client):
    workbook_id = _workbook_id(client)
    root_sheets = client.get(f"/api/workbooks/{workbook_id}/sheets").json()
    root_name = root_sheets[0]["name"]
    client.patch(f"/api/workbooks/{workbook_id}/cells/r010/s1", json={"value": "111"})

    current = client.get(
        f"/api/workbooks/{workbook_id}/export-excel",
        params={"scope": "current"},
    )
    assert current.status_code == 200
    assert current.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    current_excel = load_workbook(BytesIO(current.content), data_only=True)
    assert current_excel.sheetnames == [root_name]
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    parameter_row = next(
        index
        for index, item in enumerate(catalog["parameters"], start=2)
        if item["key"] == "r010"
    )
    assert current_excel[root_name].cell(parameter_row, 4).value == "111"
    current_excel.close()

    child = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Лист 2"},
    ).json()
    client.patch(f"/api/workbooks/{child['id']}/cells/r010/s1", json={"value": "222"})
    triangles = Workbook()
    triangles.active.title = "Геом. данные"
    triangles.active["A1"] = "Проверка геометрии"
    flow_path = triangles.create_sheet("Проточная часть")
    flow_path["B2"] = "Проверка проточной части"
    triangle_file = BytesIO()
    triangles.save(triangle_file)
    triangle_file.seek(0)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-triangle",
        files={"file": ("triangles.xlsx", triangle_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200

    all_sheets = client.get(
        f"/api/workbooks/{child['id']}/export-excel",
        params={"scope": "all"},
    )
    assert all_sheets.status_code == 200
    all_excel = load_workbook(BytesIO(all_sheets.content), data_only=True)
    assert all_excel.sheetnames == [root_name, "Лист 2", "Геом. данные", "Проточная часть"]
    assert all_excel[root_name].cell(parameter_row, 4).value == "111"
    assert all_excel["Лист 2"].cell(parameter_row, 4).value == "222"
    assert all_excel["Геом. данные"]["A1"].value == "Проверка геометрии"
    assert all_excel["Проточная часть"]["B2"].value == "Проверка проточной части"
    all_excel.close()
    assert client.get(
        f"/api/workbooks/{workbook_id}/export-excel",
        params={"scope": "invalid"},
    ).status_code == 400


def test_discard_draft(client):
    workbook_id = _workbook_id(client)
    client.patch(f"/api/workbooks/{workbook_id}/cells/r010/s1", json={"value": "111"})
    assert client.get(f"/api/workbooks/{workbook_id}/unsaved").json()
    discarded = client.post(f"/api/workbooks/{workbook_id}/cells/r010/s1/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "empty"
    assert discarded.json()["draft_value"] is None
    assert client.get(f"/api/workbooks/{workbook_id}/unsaved").json() == []


def test_session_restore_undo_draft_and_confirm(client):
    workbook_id = _workbook_id(client)
    before = client.get(f"/api/workbooks/{workbook_id}").json()
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    assert "extra_parameters" in catalog
    drafted = client.patch(f"/api/workbooks/{workbook_id}/cells/r010/s1", json={"value": "77"})
    assert drafted.json()["status"] == "draft"
    restored = client.post(
        f"/api/workbooks/{workbook_id}/session-restore",
        json={
            "cells": [
                {
                    "parameter_key": cell["parameter_key"],
                    "column_key": cell["column_key"],
                    "value": cell["value"],
                    "draft_value": cell["draft_value"],
                    "status": cell["status"],
                    "hyperlink": cell["hyperlink"],
                    "locked": cell["locked"],
                }
                for cell in before["cells"]
            ],
            "extra_parameters": catalog["extra_parameters"],
            "parameter_overrides": catalog["parameter_overrides"],
            "deleted_parameters": catalog["deleted_parameters"],
            "clear_keys": [{"parameter_key": "r010", "column_key": "s1"}],
        },
    )
    assert restored.status_code == 200
    cells = {(item["parameter_key"], item["column_key"]): item for item in restored.json()["cells"]}
    assert cells[("r010", "s1")]["status"] in {"empty", "confirmed"}
    assert cells[("r010", "s1")]["draft_value"] is None
    confirmed = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "88", "comment": "Проверка отмены"},
    )
    assert confirmed.status_code == 200
    change_id = confirmed.json()["last_change_id"]
    assert change_id
    history = client.get(f"/api/workbooks/{workbook_id}/cells/r010/s1/history").json()
    assert history
    undone = client.post(
        f"/api/workbooks/{workbook_id}/session-restore",
        json={
            "cells": [
                {
                    "parameter_key": "r010",
                    "column_key": "s1",
                    "value": None,
                    "draft_value": None,
                    "status": "empty",
                    "hyperlink": None,
                    "locked": False,
                }
            ],
            "remove_change_ids": [change_id],
        },
    )
    assert undone.status_code == 200
    assert client.get(f"/api/workbooks/{workbook_id}/cells/r010/s1/history").json() == []


def test_add_parameter_and_edit(client):
    workbook_id = _workbook_id(client)
    created = client.post(
        f"/api/workbooks/{workbook_id}/parameters",
        json={"label": "Доп. параметр", "group": "custom", "unit": "мм"},
    )
    assert created.status_code == 200
    key = created.json()["key"]
    assert key.startswith("p_custom_")
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    assert any(item["key"] == key for item in catalog["parameters"])
    nested = client.post(
        f"/api/workbooks/{workbook_id}/parameters",
        json={"label": "Вложенный", "unit": "кг", "indent": 2, "insert_after": key},
    )
    assert nested.status_code == 200
    nested_key = nested.json()["key"]
    renamed = client.patch(
        f"/api/workbooks/{workbook_id}/parameters/{key}",
        json={"label": "Переименован", "unit": "шт", "indent": 1},
    )
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Переименован"
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    by_key = {item["key"]: item for item in catalog["parameters"]}
    assert by_key[key]["unit"] == "шт"
    assert by_key[nested_key]["indent"] == 2
    deleted = client.delete(f"/api/workbooks/{workbook_id}/parameters/{nested_key}")
    assert deleted.status_code == 200
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    assert nested_key not in {item["key"] for item in catalog["parameters"]}
    draft = client.patch(f"/api/workbooks/{workbook_id}/cells/{key}/s1", json={"value": "9"})
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    confirmed = client.post(
        f"/api/workbooks/{workbook_id}/cells/{key}/s1/confirm",
        json={"value": "9", "comment": "Проверка журнала"},
    )
    assert confirmed.status_code == 200
    journal = client.get("/api/journal").json()
    actions = {item["action"] for item in journal}
    assert "parameter_added" in actions
    assert "parameter_changed" in actions
    assert "parameter_deleted" in actions
    assert "confirmed" in actions
    assert any(item["action_label"] for item in journal)


def test_changelog_releases(client):
    data = client.get("/api/changelog").json()
    assert data["text"]
    assert data["releases"]
    first = data["releases"][0]
    assert first["version"]
    assert first["date"]
    assert first["title"]
    assert first["items"]


def test_hyperlink_in_docx(client):
    workbook_id = _workbook_id(client)
    confirmed = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={
            "value": "150",
            "comment": "Ссылка на чертёж",
            "hyperlink": "https://example.com/drawing",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["hyperlink"] == "https://example.com/drawing"
    report = client.post(f"/api/workbooks/{workbook_id}/reports", json={"type": "short"})
    assert report.status_code == 200
    with ZipFile(BytesIO(report.content)) as archive:
        rels = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".rels") or name.endswith(".xml")
        )
    assert "https://example.com/drawing" in rels
    assert "Ссылка на чертёж" not in rels


def test_catalog_dictionaries(client):
    workbook_id = _workbook_id(client)
    catalog = client.get(f"/api/workbooks/{workbook_id}/catalog").json()
    by_key = {item["key"]: item for item in catalog["parameters"]}
    assert "Венцовая диафрагма" in by_key["r021"]["options"]
    assert by_key["r016"]["options"] == ["12Х18Н10Т", "15Х11МФ", "20Х13"]


def test_vane_diaphragm_copies_and_locks(client):
    workbook_id = _workbook_id(client)
    material = client.post(
        f"/api/workbooks/{workbook_id}/cells/r016/s1/confirm",
        json={"value": "20Х13", "comment": "Материал лопатки"},
    )
    assert material.status_code == 200
    vane = client.post(
        f"/api/workbooks/{workbook_id}/cells/r021/s1/confirm",
        json={"value": "Венцовая диафрагма", "comment": "Тип исполнения"},
    )
    assert vane.status_code == 200
    workbook = client.get(f"/api/workbooks/{workbook_id}").json()
    cells = {(item["parameter_key"], item["column_key"]): item for item in workbook["cells"]}
    assert cells[("r030", "s1")]["value"] == "20Х13"
    assert cells[("r016", "s1")]["locked"] is True
    assert cells[("r030", "s1")]["locked"] is True
    locked = client.patch(
        f"/api/workbooks/{workbook_id}/cells/r016/s1",
        json={"value": "15Х11МФ"},
    )
    assert locked.status_code == 400


def test_cfb_band_does_not_match_vane(client):
    workbook_id = _workbook_id(client)
    client.post(
        f"/api/workbooks/{workbook_id}/cells/r016/s1/confirm",
        json={"value": "20Х13", "comment": "Материал лопатки"},
    )
    client.post(
        f"/api/workbooks/{workbook_id}/cells/r021/s1/confirm",
        json={
            "value": "Не венцовая, ЦФБ с позиционированным бандажом",
            "comment": "Тип исполнения",
        },
    )
    workbook = client.get(f"/api/workbooks/{workbook_id}").json()
    cells = {(item["parameter_key"], item["column_key"]): item for item in workbook["cells"]}
    assert cells[("r032", "s1")]["value"] == "20Х13"
    assert cells[("r032", "s1")]["locked"] is True
    assert cells[("r016", "s1")]["locked"] is False
    r030 = cells.get(("r030", "s1"))
    assert r030 is None or r030.get("value") in (None, "")


def test_conflict_409(client):
    workbook_id = _workbook_id(client)
    first = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "100", "comment": "Первое значение"},
    )
    assert first.status_code == 200
    conflict = client.patch(
        f"/api/workbooks/{workbook_id}/cells/r010/s1",
        json={"value": "101", "expected_updated_at": "2000-01-01T00:00:00+00:00"},
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["updated_by"]
    assert detail["display"] == "100"


def test_project_revision_changes_after_cell_update(client):
    workbook_id = _workbook_id(client)
    before = client.get(f"/api/workbooks/{workbook_id}/revision").json()["revision"]
    changed = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "100", "comment": "Проверка совместной работы"},
        headers={"X-Remote-User": "editor.one"},
    )
    assert changed.status_code == 200
    after = client.get(
        f"/api/workbooks/{workbook_id}/revision",
        headers={"X-Remote-User": "editor.two"},
    ).json()["revision"]
    assert after != before


def test_notification_on_other_author_confirm(client):
    workbook_id = _workbook_id(client)
    first = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "100", "comment": "Иван"},
        headers={"X-Remote-User": "ivan"},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/workbooks/{workbook_id}/cells/r010/s1/confirm",
        json={"value": "110", "comment": "Пётр"},
        headers={"X-Remote-User": "petr"},
    )
    assert second.status_code == 200
    notes = client.get("/api/notifications", headers={"X-Remote-User": "ivan"}).json()
    assert notes
    assert notes[0]["author"] == "petr"
    assert notes[0]["read"] is False
    marked = client.post(
        f"/api/notifications/{notes[0]['id']}/read",
        headers={"X-Remote-User": "ivan"},
    )
    assert marked.status_code == 200
    assert marked.json()["read"] is True


def test_acl_forbidden(client, tmp_path, monkeypatch):
    acl_file = tmp_path / "acl.json"
    acl_file.write_text('{"editors": ["boss"], "readers": ["guest"]}', encoding="utf-8")
    monkeypatch.setenv("GRAND_SUMMARY_ACL", str(acl_file))
    from src.services.acl import reload

    reload()
    try:
        valid_payload = {
            "factory_number": "T-303",
            "turbine_name": "К-400",
            "station_name": "ТЭЦ-3",
            "station_number": "7",
            "series_turbines": "К-400",
            "kind": "steam",
        }
        denied = client.post("/api/objects", json=valid_payload)
        assert denied.status_code == 403
        guest_read = client.get("/api/objects", headers={"X-Remote-User": "guest"})
        assert guest_read.status_code == 200
        guest_write = client.post(
            "/api/objects",
            json=valid_payload,
            headers={"X-Remote-User": "guest"},
        )
        assert guest_write.status_code == 403
        created = client.post(
            "/api/objects",
            json=valid_payload,
            headers={"X-Remote-User": "boss"},
        )
        assert created.status_code == 201
    finally:
        monkeypatch.delenv("GRAND_SUMMARY_ACL", raising=False)
        reload()


def test_objects_list_reads_shared_catalog(client):
    response = client.get("/api/objects")
    assert response.status_code == 200
    assert response.json()[0]["external_id"] == "101"


def test_database_url_postgres(monkeypatch):
    monkeypatch.setenv("GRAND_SUMMARY_DB", "postgresql://u:p@localhost/grand")
    from backend.database import _database_url

    assert _database_url() == "postgresql://u:p@localhost/grand"


def test_import_excel_from_child_sheet(client, tmp_path):
    workbook_id = _workbook_id(client)
    child = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Лист до импорта"},
    ).json()
    xlsx = _triangle_file(tmp_path / "import-from-child.xlsx")
    with xlsx.open("rb") as handle:
        imported = client.post(
            f"/api/workbooks/{child['id']}/import-excel",
            files={"file": ("import-from-child.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert imported.status_code == 200
    result = imported.json()
    active = next(sheet for sheet in result["sheets"] if sheet["id"] == result["active_sheet_id"])
    assert active["name"] == "Sheet"
    assert client.get(f"/api/workbooks/{active['id']}").status_code == 200


def test_import_excel_sheets_and_copy(client):
    excel = Workbook()
    first = excel.active
    first.title = "Основные данные"
    first.append(["Наименование параметра", "1", "2"])
    first.append(["Высота сопловой лопатки, мм", 120, 125])
    second = excel.create_sheet("Дополнительные данные")
    second.append(["Наименование параметра", "1", "2"])
    second.append(["Высота сопловой лопатки, мм", 130, 135])
    protocol = excel.create_sheet("Протокол изменений")
    protocol.append(["Дата", "Пользователь", "Изменение"])
    file_content = BytesIO()
    excel.save(file_content)
    file_content.seek(0)

    workbook_id = _workbook_id(client)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("sheets.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200
    result = imported.json()
    assert result["imported"] == 4
    assert [sheet["name"] for sheet in result["sheets"]] == ["Основные данные", "Дополнительные данные"]

    first_id, second_id = (sheet["id"] for sheet in result["sheets"])
    first_data = client.get(f"/api/workbooks/{first_id}").json()
    first_cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in first_data["cells"]}
    assert first_cells[("r010", "s1")]["value"] == "120"
    assert first_cells[("r010", "s1")]["status"] == "initial"
    assert first_cells[("r010", "s2")]["value"] == "125"
    assert first_cells[("r010", "s2")]["status"] == "initial"

    copied = client.post(
        f"/api/workbooks/{second_id}/sheets",
        json={"name": "Копия дополнительного"},
    )
    assert copied.status_code == 200
    copied_cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in copied.json()["cells"]}
    assert copied_cells[("r010", "s1")]["value"] == "130"
    assert copied_cells[("r010", "s1")]["status"] == "initial"
    assert copied.json()["sheet_name"] == "Копия дополнительного"

    copied_id = copied.json()["id"]
    draft = client.patch(
        f"/api/workbooks/{copied_id}/cells/r010/s1",
        json={"value": "131"},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    discarded = client.post(f"/api/workbooks/{copied_id}/cells/r010/s1/discard")
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "initial"

    client.patch(
        f"/api/workbooks/{copied_id}/cells/r010/s1",
        json={"value": "131"},
    )
    confirmed = client.post(
        f"/api/workbooks/{copied_id}/cells/r010/s1/confirm",
        json={"value": "131", "comment": "Изменено пользователем"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"


def test_excel_sheets_become_change_journal_and_orange_can_be_cleared(client):
    excel = Workbook()
    first = excel.active
    first.title = "Основной"
    first.append(["Наименование параметра", "1", "2"])
    first.append(["Высота сопловой лопатки, мм", 120, 125])
    second = excel.create_sheet("15.03.2026")
    second.append(["Наименование параметра", "1", "2"])
    second.append(["Высота сопловой лопатки, мм", 130, 125])
    third = excel.create_sheet("01.04.2026")
    third.append(["Наименование параметра", "1", "2"])
    third.append(["Высота сопловой лопатки, мм", 140, None])
    third.append(["Угол установки профиля в корневом сечении (α'уст)", 15, None])
    content = BytesIO()
    excel.save(content)
    content.seek(0)

    workbook_id = _workbook_id(client)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("journal.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["journaled"] == 4
    assert [sheet["name"] for sheet in result["sheets"]] == ["Основной", "15.03.2026", "01.04.2026"]
    primary_id, middle_id, last_id = (sheet["id"] for sheet in result["sheets"])

    primary_cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{primary_id}").json()["cells"]
    }
    assert primary_cells[("r010", "s1")]["value"] == "120"
    assert primary_cells[("r010", "s1")]["excel_highlight"] is False
    assert client.get(f"/api/workbooks/{primary_id}/cells/r010/s1/history").json() == []

    middle_cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{middle_id}").json()["cells"]
    }
    assert middle_cells[("r010", "s1")]["value"] == "130"
    assert middle_cells[("r010", "s1")]["status"] == "initial"
    assert middle_cells[("r010", "s1")]["excel_highlight"] is True
    assert middle_cells[("r010", "s2")]["value"] == "125"
    assert middle_cells[("r010", "s2")]["excel_highlight"] is False
    middle_history = client.get(f"/api/workbooks/{middle_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in middle_history] == [
        "Данные из основного листа",
        "Изменение листа «15.03.2026»",
    ]
    assert middle_history[0]["new_value"] == "120"
    assert middle_history[0]["old_value"] is None
    assert middle_history[1]["old_value"] == "120"
    assert middle_history[1]["new_value"] == "130"

    last_cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{last_id}").json()["cells"]
    }
    assert last_cells[("r010", "s1")]["value"] == "140"
    assert last_cells[("r010", "s1")]["excel_highlight"] is True
    assert last_cells[("r010", "s2")]["value"] in {None, ""}
    assert last_cells[("r010", "s2")]["excel_highlight"] is True
    assert last_cells[("r007", "s1")]["value"] == "15"
    assert last_cells[("r007", "s1")]["excel_highlight"] is True
    last_history = client.get(f"/api/workbooks/{last_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in last_history] == [
        "Данные из основного листа",
        "Изменение листа «15.03.2026»",
        "Изменение листа «01.04.2026»",
    ]
    assert [item["new_value"] for item in last_history] == ["120", "130", "140"]
    angle_history = client.get(f"/api/workbooks/{last_id}/cells/r007/s1/history").json()
    assert [item["comment"] for item in angle_history] == ["Изменение листа «01.04.2026»"]
    assert angle_history[0]["old_value"] is None
    assert angle_history[0]["new_value"] == "15"

    cleared = client.post(f"/api/workbooks/{last_id}/clear-excel-highlight")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] == 4
    refreshed = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{last_id}").json()["cells"]
    }
    assert refreshed[("r010", "s1")]["value"] == "140"
    assert refreshed[("r010", "s1")]["excel_highlight"] is False
    assert refreshed[("r010", "s2")]["excel_highlight"] is False
    assert refreshed[("r007", "s1")]["excel_highlight"] is False
    kept = client.get(f"/api/workbooks/{last_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in kept] == [item["comment"] for item in last_history]
    middle_after = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{middle_id}").json()["cells"]
    }
    assert middle_after[("r010", "s1")]["excel_highlight"] is False
    assert middle_after[("r010", "s1")]["value"] == "130"


def test_other_sheet_inherits_unchanged_primary_cells(client):
    workbook_id = _workbook_id(client)
    excel = Workbook()
    sheet = excel.active
    sheet.title = "Основной"
    sheet.append(["Наименование параметра", "1", "2"])
    sheet.append(["Высота сопловой лопатки, мм", 120, 125])
    content = BytesIO()
    excel.save(content)
    content.seek(0)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("base.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    primary_id = imported.json()["sheets"][0]["id"]
    journal = client.post(f"/api/workbooks/{primary_id}/sheets", json={"name": "01.04.2026"})
    assert journal.status_code == 200, journal.text
    journal_id = journal.json()["id"]
    inherited = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in journal.json()["cells"]
    }
    assert inherited[("r010", "s1")]["value"] == "120"
    assert inherited[("r010", "s2")]["value"] == "125"

    changed = client.post(
        f"/api/workbooks/{journal_id}/cells/r010/s1/confirm",
        json={"value": "130", "comment": "Изменение журнала", "expected_updated_at": inherited[("r010", "s1")]["updated_at"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["value"] == "130"

    journal_again = client.get(f"/api/workbooks/{journal_id}").json()
    journal_cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in journal_again["cells"]}
    primary_cells = {
        (cell["parameter_key"], cell["column_key"]): cell
        for cell in client.get(f"/api/workbooks/{primary_id}").json()["cells"]
    }
    assert journal_cells[("r010", "s1")]["value"] == "130"
    assert journal_cells[("r010", "s2")]["value"] == "125"
    assert primary_cells[("r010", "s1")]["value"] == "120"
    assert journal_cells[("r010", "s2")]["updated_at"] == primary_cells[("r010", "s2")]["updated_at"]


def test_cell_history_starts_from_primary_sheet_value(client):
    workbook_id = _workbook_id(client)
    excel = Workbook()
    sheet = excel.active
    sheet.title = "Основной"
    sheet.append(["Наименование параметра", "1"])
    sheet.append(["Высота сопловой лопатки, мм", 120])
    content = BytesIO()
    excel.save(content)
    content.seek(0)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("base.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    primary_id = imported.json()["sheets"][0]["id"]
    journal = client.post(f"/api/workbooks/{primary_id}/sheets", json={"name": "01.04.2026"})
    journal_id = journal.json()["id"]
    inherited = {(cell["parameter_key"], cell["column_key"]): cell for cell in journal.json()["cells"]}

    first = client.post(
        f"/api/workbooks/{journal_id}/cells/r010/s1/confirm",
        json={"value": "130", "comment": "Первая правка", "expected_updated_at": inherited[("r010", "s1")]["updated_at"]},
    )
    assert first.status_code == 200, first.text
    history = client.get(f"/api/workbooks/{journal_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in history] == ["Данные из основного листа", "Первая правка"]
    assert history[0]["new_value"] == "120"
    assert history[0]["old_value"] is None
    assert history[-1]["old_value"] == "120"
    assert history[-1]["new_value"] == "130"

    second = client.post(
        f"/api/workbooks/{journal_id}/cells/r010/s1/confirm",
        json={"value": "140", "comment": "Вторая правка", "expected_updated_at": first.json()["updated_at"]},
    )
    assert second.status_code == 200, second.text
    history = client.get(f"/api/workbooks/{journal_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in history] == [
        "Данные из основного листа",
        "Первая правка",
        "Вторая правка",
    ]
    assert history[0]["new_value"] == "120"

    empty = client.post(
        f"/api/workbooks/{journal_id}/cells/r007/s1/confirm",
        json={"value": "15", "comment": "Пустая исходная"},
    )
    assert empty.status_code == 200, empty.text
    empty_history = client.get(f"/api/workbooks/{journal_id}/cells/r007/s1/history").json()
    assert [item["comment"] for item in empty_history] == ["Пустая исходная"]

    copied = client.post(f"/api/workbooks/{journal_id}/sheets", json={"name": "14.04.2026"})
    assert copied.status_code == 200, copied.text
    copied_id = copied.json()["id"]
    copied_cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in copied.json()["cells"]}
    carried = client.get(f"/api/workbooks/{copied_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in carried] == [
        "Данные из основного листа",
        "Первая правка",
        "Вторая правка",
    ]
    continued = client.post(
        f"/api/workbooks/{copied_id}/cells/r010/s1/confirm",
        json={
            "value": "150",
            "comment": "Правка копии",
            "expected_updated_at": copied_cells[("r010", "s1")]["updated_at"],
        },
    )
    assert continued.status_code == 200, continued.text
    carried = client.get(f"/api/workbooks/{copied_id}/cells/r010/s1/history").json()
    assert [item["comment"] for item in carried] == [
        "Данные из основного листа",
        "Первая правка",
        "Вторая правка",
        "Правка копии",
    ]
    assert carried[0]["new_value"] == "120"
    assert carried[-1]["old_value"] == "140"
    assert carried[-1]["new_value"] == "150"


def test_issued_sheet_is_frozen_and_its_copy_hides_old_changes(client):
    workbook_id = _workbook_id(client)
    excel = Workbook()
    sheet = excel.active
    sheet.title = "Основной"
    sheet.append(["Наименование параметра", "1", "2"])
    sheet.append(["Высота сопловой лопатки, мм", 120, 125])
    content = BytesIO()
    excel.save(content)
    content.seek(0)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("base.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200, imported.text
    primary_id = imported.json()["sheets"][0]["id"]
    journal = client.post(f"/api/workbooks/{primary_id}/sheets", json={"name": "01.04.2026"})
    assert journal.status_code == 200, journal.text
    journal_id = journal.json()["id"]
    inherited = {(cell["parameter_key"], cell["column_key"]): cell for cell in journal.json()["cells"]}
    changed = client.post(
        f"/api/workbooks/{journal_id}/cells/r010/s1/confirm",
        json={"value": "130", "comment": "Перед выдачей", "expected_updated_at": inherited[("r010", "s1")]["updated_at"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "confirmed"

    blocked_primary = client.patch(
        f"/api/workbooks/{primary_id}/sheets/{primary_id}/issued",
        json={"issued": True},
    )
    assert blocked_primary.status_code == 400

    issued = client.patch(
        f"/api/workbooks/{primary_id}/sheets/{journal_id}/issued",
        json={"issued": True},
    )
    assert issued.status_code == 200, issued.text
    assert next(item["is_issued"] for item in issued.json()["sheets"] if item["id"] == journal_id)
    frozen = {(cell["parameter_key"], cell["column_key"]): cell for cell in client.get(f"/api/workbooks/{journal_id}").json()["cells"]}
    assert frozen[("r010", "s1")]["value"] == "130"
    assert frozen[("r010", "s2")]["value"] == "125"
    denied = client.post(
        f"/api/workbooks/{journal_id}/cells/r010/s1/confirm",
        json={"value": "131", "comment": "После выдачи"},
    )
    assert denied.status_code == 400

    copied = client.post(f"/api/workbooks/{journal_id}/sheets", json={"name": "14.04.2026"})
    assert copied.status_code == 200, copied.text
    assert copied.json()["is_issued"] is False
    copied_cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in copied.json()["cells"]}
    assert copied_cells[("r010", "s1")]["value"] == "130"
    assert copied_cells[("r010", "s1")]["status"] == "initial"
    assert copied_cells[("r010", "s2")]["value"] == "125"
    fresh = client.post(
        f"/api/workbooks/{copied.json()['id']}/cells/r010/s1/confirm",
        json={"value": "140", "comment": "Новое изменение", "expected_updated_at": copied_cells[("r010", "s1")]["updated_at"]},
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["status"] == "confirmed"
    assert fresh.json()["value"] == "140"
    still_frozen = {(cell["parameter_key"], cell["column_key"]): cell for cell in client.get(f"/api/workbooks/{journal_id}").json()["cells"]}
    assert still_frozen[("r010", "s1")]["value"] == "130"

    cleared = client.patch(
        f"/api/workbooks/{primary_id}/sheets/{journal_id}/issued",
        json={"issued": False},
    )
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"/api/workbooks/{journal_id}").json()["is_issued"] is False


def test_import_excel_rejects_xls(client):
    workbook_id = _workbook_id(client)
    response = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("legacy.xls", b"not an xlsx", "application/vnd.ms-excel")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Поддерживаются только файлы .xlsx"


def test_delete_sheet_preserves_primary_sheet_and_allows_reimport(client, tmp_path):
    workbook_id = _workbook_id(client)
    primary = client.get(f"/api/workbooks/{workbook_id}").json()
    copied = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Временный лист"},
    ).json()
    persisted_sheets = client.get(f"/api/workbooks/{workbook_id}/sheets").json()
    assert [sheet["id"] for sheet in persisted_sheets] == [primary["id"], copied["id"]]

    deleted = client.delete(
        f"/api/workbooks/{workbook_id}/sheets/{copied['id']}"
    )
    assert deleted.status_code == 200
    assert deleted.json()["active_sheet_id"] == primary["id"]
    assert [sheet["id"] for sheet in deleted.json()["sheets"]] == [primary["id"]]
    assert client.get(f"/api/workbooks/{copied['id']}").status_code == 404

    object_id = client.get("/api/objects").json()[0]["id"]
    reopened = client.post("/api/workbooks", json={"object_id": object_id})
    assert reopened.status_code == 200
    assert reopened.json()["id"] == primary["id"]
    workbook_id = reopened.json()["id"]
    xlsx = _triangle_file(tmp_path / "reimport-after-delete.xlsx")
    with xlsx.open("rb") as handle:
        imported = client.post(
            f"/api/workbooks/{workbook_id}/import-excel",
            files={"file": ("reimport-after-delete.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert imported.status_code == 200
    assert imported.json()["active_sheet_id"] == primary["id"]
    assert client.get(f"/api/workbooks/{workbook_id}").status_code == 200
    assert [sheet["id"] for sheet in client.get(f"/api/workbooks/{workbook_id}/sheets").json()] == [primary["id"]]


def test_delete_root_sheet_promotes_remaining_sheet(client):
    workbook_id = _workbook_id(client)
    root = client.get(f"/api/workbooks/{workbook_id}").json()
    copied = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Импортированный лист"},
    ).json()
    extra = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Ещё один лист"},
    ).json()

    last_only = client.delete(f"/api/workbooks/{workbook_id}/sheets/{workbook_id}")
    assert last_only.status_code == 200
    payload = last_only.json()
    assert payload["active_sheet_id"] == copied["id"]
    assert [sheet["id"] for sheet in payload["sheets"]] == [copied["id"], extra["id"]]
    assert client.get(f"/api/workbooks/{root['id']}").status_code == 404
    assert client.get(f"/api/workbooks/{copied['id']}").json()["parent_workbook_id"] is None
    assert client.get(f"/api/workbooks/{extra['id']}").json()["parent_workbook_id"] == copied["id"]

    reopened = client.post("/api/workbooks", json={"object_id": root["object_id"]})
    assert reopened.status_code == 200
    assert reopened.json()["id"] == copied["id"]
    sheets = client.get(f"/api/workbooks/{copied['id']}/sheets").json()
    assert [sheet["id"] for sheet in sheets] == [copied["id"], extra["id"]]

    leftover = client.delete(f"/api/workbooks/{copied['id']}/sheets/{copied['id']}")
    assert leftover.status_code == 200
    assert leftover.json()["active_sheet_id"] == extra["id"]
    assert [sheet["id"] for sheet in leftover.json()["sheets"]] == [extra["id"]]

    blocked = client.delete(f"/api/workbooks/{extra['id']}/sheets/{extra['id']}")
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Нельзя удалить единственный лист проекта"


def test_import_dated_object_workbook_after_deleting_a_sheet(client, tmp_path):
    object_id = client.get("/api/objects").json()[0]["id"]
    root = client.post("/api/workbooks", json={"object_id": object_id}).json()
    copied = client.post(
        f"/api/workbooks/{root['id']}/sheets",
        json={"name": "Удаляемый лист"},
    ).json()
    deleted = client.delete(f"/api/workbooks/{root['id']}/sheets/{copied['id']}")
    assert deleted.status_code == 200

    reopened = client.post("/api/workbooks", json={"object_id": object_id})
    assert reopened.status_code == 200
    workbook_id = reopened.json()["id"]

    excel = Workbook()
    sheet_names = ["01.04.2026", "14.04.2026", "12.05.2026", "23.06.2026", "30.07.2026", "21.09.2026"]
    for index, name in enumerate(sheet_names):
        sheet = excel.active if index == 0 else excel.create_sheet(name)
        sheet.title = name
        sheet.append(["Дата внесения изменений", "Служебная записка"])
        sheet.append([None, "№ ступени"])
        sheet.append(["Наименование параметра", "1", "2"])
        sheet.append(["Характеристики проточной части:"])
        sheet.append(["Высота сопловой лопатки, мм", 120 + index, 125 + index])
    protocol = excel.create_sheet("Протокол изменений")
    protocol.append(["Дата", "Автор", "Изменение"])
    file_content = BytesIO()
    excel.save(file_content)
    file_content.seek(0)

    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("object-parameters.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200
    result = imported.json()
    assert result["imported"] == 12
    assert [sheet["name"] for sheet in result["sheets"]] == sheet_names
    assert all(client.get(f"/api/workbooks/{sheet['id']}").status_code == 200 for sheet in result["sheets"])
    assert "Протокол изменений" not in [sheet["name"] for sheet in result["sheets"]]


def test_save_project_preserves_sheet_and_draft_status(client):
    workbook_id = _workbook_id(client)
    copied = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Черновой лист"},
    ).json()
    draft = client.patch(
        f"/api/workbooks/{copied['id']}/cells/r010/s1",
        json={"value": "Черновик"},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"

    saved = client.post(f"/api/workbooks/{copied['id']}/save")
    assert saved.status_code == 200
    assert saved.json()["sheet_count"] == 2
    assert saved.json()["cell_count"] == 1
    assert saved.json()["draft_count"] == 1

    workbook_after_save = client.get(f"/api/workbooks/{copied['id']}").json()
    current_cell = next(
        cell
        for cell in workbook_after_save["cells"]
        if cell["parameter_key"] == "r010" and cell["column_key"] == "s1"
    )
    assert current_cell["status"] == "draft"
    assert current_cell["draft_value"] == "Черновик"
    assert [sheet["id"] for sheet in client.get(f"/api/workbooks/{workbook_id}/sheets").json()] == [workbook_id, copied["id"]]

    journal = client.get("/api/journal", params={"workbook_id": workbook_id}).json()
    assert any(item["action"] == "project_saved" for item in journal)


def test_report_preview_uses_selected_sheet(client):
    workbook_id = _workbook_id(client)
    copied = client.post(
        f"/api/workbooks/{workbook_id}/sheets",
        json={"name": "Лист для отчёта"},
    ).json()
    saved = client.post(
        f"/api/workbooks/{copied['id']}/cells/r010/s1/confirm",
        json={"value": "246", "comment": "Значение для листа"},
    )
    assert saved.status_code == 200

    preview = client.get(
        f"/api/workbooks/{copied['id']}/report-preview",
        params={"report_type": "full"},
    )
    assert preview.status_code == 200
    row = next(row for table in preview.json()["tables"] for row in table["rows"] if row["parameter_key"] == "r010")
    cell = next(cell for cell in row["cells"] if cell["column_key"] == "s1")
    assert cell["value"] == "246"


def test_baseline_feature_is_not_exposed_and_sheet_renaming_still_works(client):
    root_id = _workbook_id(client)
    root = client.get(f"/api/workbooks/{root_id}").json()
    copied = client.post(
        f"/api/workbooks/{root_id}/sheets",
        json={"name": "Новая копия"},
    ).json()
    assert "is_baseline" not in root
    assert "is_baseline" not in copied

    renamed = client.patch(
        f"/api/workbooks/{root_id}/sheets/{copied['id']}/name",
        json={"name": "Актуальный лист"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["sheet_name"] == "Актуальный лист"
    primary_rename = client.patch(
        f"/api/workbooks/{root_id}/sheets/{root_id}/name",
        json={"name": "Переименование основного"},
    )
    assert primary_rename.status_code == 400
    duplicate = client.post(
        f"/api/workbooks/{root_id}/sheets",
        json={"name": "Еще одна копия"},
    ).json()
    duplicate_name = client.patch(
        f"/api/workbooks/{root_id}/sheets/{duplicate['id']}/name",
        json={"name": "Актуальный лист"},
    )
    assert duplicate_name.status_code == 400

    removed_route = client.patch(
        f"/api/workbooks/{root_id}/sheets/{root_id}/baseline",
        json={"is_baseline": True},
    )
    assert removed_route.status_code == 404
    assert client.get(f"/api/workbooks/{copied['id']}/report-preview").status_code == 200

    reopened = client.post("/api/workbooks", json={"object_id": root["object_id"]})
    assert reopened.status_code == 200
    persisted = client.get(f"/api/workbooks/{root_id}/sheets").json()
    assert all("is_baseline" not in sheet for sheet in persisted)


def test_primary_sheet_moves_to_front_without_changing_project_root(client):
    root_id = _workbook_id(client)
    root = client.get(f"/api/workbooks/{root_id}").json()
    assert root["sheet_name"] == "Исходные данные"
    copied = client.post(
        f"/api/workbooks/{root_id}/sheets",
        json={"name": "Будущий основной"},
    ).json()

    promoted = client.patch(f"/api/workbooks/{root_id}/sheets/{copied['id']}/primary")
    assert promoted.status_code == 200
    assert promoted.json()["active_sheet_id"] == copied["id"]
    assert [sheet["id"] for sheet in promoted.json()["sheets"]] == [copied["id"], root_id]
    assert [sheet["order"] for sheet in promoted.json()["sheets"]] == [0, 1]
    assert client.get(f"/api/workbooks/{copied['id']}").json()["parent_workbook_id"] == root_id

    reopened = client.post("/api/workbooks", json={"object_id": root["object_id"]})
    assert reopened.status_code == 200
    assert reopened.json()["id"] == root_id
    sheets = client.get(f"/api/workbooks/{root_id}/sheets").json()
    assert sheets[0]["id"] == copied["id"]
    assert [(sheet["id"], sheet["is_primary"]) for sheet in sheets] == [
        (copied["id"], True),
        (root_id, False),
    ]

    blocked_write = client.patch(
        f"/api/workbooks/{copied['id']}/cells/r010/s1",
        json={"value": "Нельзя изменить"},
    )
    assert blocked_write.status_code == 400
    blocked_delete = client.delete(f"/api/workbooks/{root_id}/sheets/{copied['id']}")
    assert blocked_delete.status_code == 400
    blocked_rename = client.patch(
        f"/api/workbooks/{root_id}/sheets/{copied['id']}/name",
        json={"name": "Попытка переименования"},
    )
    assert blocked_rename.status_code == 400
    blocked_triangle_sync = client.post(
        f"/api/workbooks/{copied['id']}/sync-triangles",
        json={"mode": "all", "cells": []},
    )
    assert blocked_triangle_sync.status_code == 400

    demoted = client.patch(f"/api/workbooks/{root_id}/sheets/{copied['id']}/ordinary")
    assert demoted.status_code == 200
    assert next(sheet for sheet in demoted.json()["sheets"] if sheet["id"] == copied["id"])["is_primary"] is False
    allowed_write = client.patch(
        f"/api/workbooks/{copied['id']}/cells/r010/s1",
        json={"value": "Изменение после снятия статуса"},
    )
    assert allowed_write.status_code == 200
    assert allowed_write.json()["status"] == "draft"


def test_import_excel_matches_short_labels_and_preamble(client):
    excel = Workbook()
    sheet = excel.active
    sheet.title = "01.04.2026"
    sheet.append(["Дата внесения изменений", "Служебная записка"])
    sheet.append([None, "№ ступени"])
    sheet.append(["Наименование параметра", "Ед. изм.", "1", "2"])
    sheet.append(["Характеристики проточной части:"])
    sheet.append(["Высота сопловой лопатки, мм", "мм", 120, 125])
    file_content = BytesIO()
    excel.save(file_content)
    file_content.seek(0)

    workbook_id = _workbook_id(client)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("object-parameters.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200
    result = imported.json()
    assert result["imported"] == 2
    data = client.get(f"/api/workbooks/{result['active_sheet_id']}").json()
    cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in data["cells"]}
    assert cells[("r010", "s1")]["value"] == "120"
    assert cells[("r010", "s2")]["value"] == "125"


def test_import_excel_roundtrip_exported_layout(client):
    excel = Workbook()
    sheet = excel.active
    sheet.title = "Лист проекта"
    sheet.append(["Наименование параметра", "Ед. изм.", None, "1", "2"])
    sheet.append(["Характеристики проточной части:", None, None, None, None])
    sheet.append(["Высота сопловой лопатки (L'), мм", "мм", None, 77, 80])
    file_content = BytesIO()
    excel.save(file_content)
    file_content.seek(0)

    workbook_id = _workbook_id(client)
    imported = client.post(
        f"/api/workbooks/{workbook_id}/import-excel",
        files={"file": ("export.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert imported.status_code == 200
    assert imported.json()["imported"] == 2
    active = imported.json()["active_sheet_id"]
    data = client.get(f"/api/workbooks/{active}").json()
    cells = {(cell["parameter_key"], cell["column_key"]): cell for cell in data["cells"]}
    assert cells[("r010", "s1")]["value"] == "77"
    assert cells[("r010", "s2")]["value"] == "80"
