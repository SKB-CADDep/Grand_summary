from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook


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


def test_objects_seeded(client):
    response = client.get("/api/objects")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert "external_id" in data[0]


def test_create_object(client):
    response = client.post(
        "/api/objects",
        json={"name": "Новый объект", "cylinder": "ЦНД", "external_id": "OBJ-X"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Новый объект"


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


def test_import_triangle(client, tmp_path):
    objects = client.get("/api/objects").json()
    workbook_id = client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]
    xlsx = _triangle_file(tmp_path / "triangle.xlsx")
    with xlsx.open("rb") as handle:
        response = client.post(
            f"/api/workbooks/{workbook_id}/import-triangle",
            files={"file": ("triangle.xlsx", handle, "application/vnd.ms-excel")},
        )
    assert response.status_code == 200
    assert response.json()["imported"] >= 2
    cells = {(item["parameter_key"], item["column_key"]): item for item in response.json()["cells"]}
    assert cells[("r010", "s1")]["value"] == "120"
    assert cells[("r010", "s2")]["value"] == "125"
    versions = client.get(f"/api/workbooks/{workbook_id}/versions").json()
    assert any(item["kind"] == "triangle_import" for item in versions)


def test_report_preview_and_docx(client):
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
        json={"type": "short", "compare_version_id": version["id"]},
    )
    assert report.status_code == 200
    assert report.content[:2] == b"PK"
    assert "Уточнение по тепловому расчёту".encode("utf-8") not in report.content
    assert "Корректировка высоты".encode("utf-8") not in report.content


def _workbook_id(client) -> str:
    objects = client.get("/api/objects").json()
    return client.post("/api/workbooks", json={"object_id": objects[0]["id"]}).json()["id"]


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
    assert "20Х13" in by_key["r016"]["options"]


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
        denied = client.post("/api/objects", json={"name": "Нет прав"})
        assert denied.status_code == 403
        guest_read = client.get("/api/objects", headers={"X-Remote-User": "guest"})
        assert guest_read.status_code == 200
        guest_write = client.post(
            "/api/objects",
            json={"name": "Гость"},
            headers={"X-Remote-User": "guest"},
        )
        assert guest_write.status_code == 403
        created = client.post(
            "/api/objects",
            json={"name": "От начальника"},
            headers={"X-Remote-User": "boss"},
        )
        assert created.status_code == 201
    finally:
        monkeypatch.delenv("GRAND_SUMMARY_ACL", raising=False)
        reload()


def test_objects_sync(client):
    response = client.get("/api/objects/sync")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_database_url_postgres(monkeypatch):
    monkeypatch.setenv("GRAND_SUMMARY_DB", "postgresql://u:p@localhost/grand")
    from backend.database import _database_url

    assert _database_url() == "postgresql://u:p@localhost/grand"
