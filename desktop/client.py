from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.responses import Response

from backend.database import init_db
from backend.main import app


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self) -> None:
        init_db()
        self._http = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        self._http.close()

    def _error(self, response: Response) -> ApiError:
        detail: Any = None
        message = getattr(response, "reason_phrase", None) or f"HTTP {response.status_code}"
        try:
            data = response.json()
            detail = data.get("detail", data)
            if isinstance(detail, str):
                message = detail
            else:
                message = str(detail)
        except Exception:
            pass
        return ApiError(message, response.status_code, detail)

    def _json(self, response: Response) -> Any:
        if response.status_code >= 400:
            raise self._error(response)
        if not response.content:
            return None
        return response.json()

    def _bytes(self, response: Response) -> bytes:
        if response.status_code >= 400:
            raise self._error(response)
        return response.content

    def me(self) -> dict:
        return self._json(self._http.get("/api/me"))

    def mark_guide_seen(self) -> dict:
        return self._json(self._http.post("/api/me/guide-seen"))

    def history_preferences(self) -> dict:
        return self._json(self._http.get("/api/me/preferences"))

    def save_history_preferences(self, body: dict) -> dict:
        return self._json(self._http.put("/api/me/preferences", json=body))

    def objects(self) -> list[dict]:
        return self._json(self._http.get("/api/objects"))

    def create_object(self, body: dict) -> dict:
        return self._json(self._http.post("/api/objects", json=body))

    def open_workbook(self, object_id: str) -> dict:
        return self._json(self._http.post("/api/workbooks", json={"object_id": object_id}))

    def workbook(self, workbook_id: str) -> dict:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}"))

    def sheets(self, workbook_id: str) -> list[dict]:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/sheets"))

    def workbook_revision(self, workbook_id: str) -> dict:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/revision"))

    def save_project(self, workbook_id: str) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/save"))

    def catalog(self, workbook_id: str) -> dict:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/catalog"))

    def copy_sheet(self, workbook_id: str, name: str) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/sheets", json={"name": name}))

    def rename_sheet(self, workbook_id: str, sheet_id: str, name: str) -> dict:
        return self._json(
            self._http.patch(f"/api/workbooks/{workbook_id}/sheets/{sheet_id}/name", json={"name": name})
        )

    def set_primary_sheet(self, workbook_id: str, sheet_id: str) -> dict:
        return self._json(self._http.patch(f"/api/workbooks/{workbook_id}/sheets/{sheet_id}/primary"))

    def unset_primary_sheet(self, workbook_id: str, sheet_id: str) -> dict:
        return self._json(self._http.patch(f"/api/workbooks/{workbook_id}/sheets/{sheet_id}/ordinary"))

    def set_sheet_issued(self, workbook_id: str, sheet_id: str, issued: bool) -> dict:
        return self._json(
            self._http.patch(
                f"/api/workbooks/{workbook_id}/sheets/{sheet_id}/issued",
                json={"issued": issued},
            )
        )

    def delete_sheet(self, workbook_id: str, sheet_id: str) -> dict:
        return self._json(self._http.delete(f"/api/workbooks/{workbook_id}/sheets/{sheet_id}"))

    def add_stage(self, workbook_id: str, label: str) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/stages", json={"label": label}))

    def update_column(self, workbook_id: str, key: str, label: str) -> dict:
        return self._json(self._http.patch(f"/api/workbooks/{workbook_id}/columns/{key}", json={"label": label}))

    def delete_column(self, workbook_id: str, key: str) -> dict:
        return self._json(self._http.delete(f"/api/workbooks/{workbook_id}/columns/{key}"))

    def add_parameter(self, workbook_id: str, body: dict) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/parameters", json=body))

    def update_parameter(self, workbook_id: str, key: str, body: dict) -> dict:
        return self._json(self._http.patch(f"/api/workbooks/{workbook_id}/parameters/{key}", json=body))

    def delete_parameter(self, workbook_id: str, key: str) -> dict:
        return self._json(self._http.delete(f"/api/workbooks/{workbook_id}/parameters/{key}"))

    def patch_cell(self, workbook_id: str, parameter_key: str, column_key: str, body: dict) -> dict:
        return self._json(
            self._http.patch(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}", json=body)
        )

    def confirm_cell(self, workbook_id: str, parameter_key: str, column_key: str, body: dict) -> dict:
        return self._json(
            self._http.post(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/confirm", json=body)
        )

    def add_cell_comment(self, workbook_id: str, parameter_key: str, column_key: str, body: dict) -> dict:
        return self._json(
            self._http.post(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/comment", json=body)
        )

    def set_cell_unification(self, workbook_id: str, parameter_key: str, column_key: str, body: dict) -> dict:
        return self._json(
            self._http.patch(
                f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/unification", json=body
            )
        )

    def discard_cell(self, workbook_id: str, parameter_key: str, column_key: str) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/discard"))

    def history(self, workbook_id: str, parameter_key: str, column_key: str) -> list[dict]:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/history"))

    def last_cell_comment(self, workbook_id: str, parameter_key: str, column_key: str) -> str | None:
        data = self._json(self._http.get(f"/api/workbooks/{workbook_id}/cells/{parameter_key}/{column_key}/last-comment"))
        return data.get("comment") if isinstance(data, dict) else None

    def unsaved(self, workbook_id: str) -> list[dict]:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/unsaved"))

    def triangles(self, workbook_id: str) -> list[dict]:
        return self._json(self._http.get(f"/api/workbooks/{workbook_id}/triangles"))

    def import_triangle(self, workbook_id: str, path: Path) -> dict:
        with path.open("rb") as handle:
            return self._json(
                self._http.post(
                    f"/api/workbooks/{workbook_id}/import-triangle",
                    files={"file": (path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )
            )

    def sync_triangles(self, workbook_id: str, body: dict) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/sync-triangles", json=body))

    def clear_excel_highlight(self, workbook_id: str) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/clear-excel-highlight"))

    def import_workbook(self, workbook_id: str, path: Path) -> dict:
        with path.open("rb") as handle:
            return self._json(
                self._http.post(
                    f"/api/workbooks/{workbook_id}/import-excel",
                    files={"file": (path.name, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                )
            )

    def export_excel(self, workbook_id: str, scope: str) -> bytes:
        return self._bytes(self._http.get(f"/api/workbooks/{workbook_id}/export-excel", params={"scope": scope}))

    def export_report_table(self, workbook_id: str, parameter_keys: list[str], column_keys: list[str], table_number: int = 1) -> bytes:
        return self._bytes(
            self._http.post(
                f"/api/workbooks/{workbook_id}/export-report-table",
                json={
                    "selected_parameter_keys": parameter_keys,
                    "selected_column_keys": column_keys,
                    "table_number": table_number,
                },
            )
        )

    def restore_session(self, workbook_id: str, body: dict) -> dict:
        return self._json(self._http.post(f"/api/workbooks/{workbook_id}/session-restore", json=body))

    def changelog(self) -> dict:
        return self._json(self._http.get("/api/changelog"))

    def journal(self, workbook_id: str | None = None) -> list[dict]:
        params = {"workbook_id": workbook_id} if workbook_id else None
        return self._json(self._http.get("/api/journal", params=params))

    def instruction(self) -> dict:
        return self._json(self._http.get("/api/instruction"))

    def notifications(self) -> list[dict]:
        return self._json(self._http.get("/api/notifications"))

    def read_notification(self, note_id: str) -> dict:
        return self._json(self._http.post(f"/api/notifications/{note_id}/read"))

    def update_status(self) -> dict:
        return self._json(self._http.get("/api/updates"))

    def apply_update(self) -> dict:
        return self._json(self._http.post("/api/updates/apply"))
