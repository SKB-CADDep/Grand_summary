from __future__ import annotations

PRELIMINARY = "preliminary"
FINAL = "final"
UPDATE = "update"
DEFAULT = PRELIMINARY

CHOICES: tuple[tuple[str, str], ...] = (
    (PRELIMINARY, "Предварительные данные"),
    (FINAL, "Конечные данные"),
    (UPDATE, "Обновление"),
)
LABELS = dict(CHOICES)


def normalize_issued_kind(kind: str | None, issued: bool = True) -> str:
    if not issued:
        return ""
    value = (kind or "").strip()
    return value if value in LABELS else DEFAULT


def issued_kind_label(kind: str | None, issued: bool = True) -> str:
    key = normalize_issued_kind(kind, issued)
    return LABELS.get(key, "")
