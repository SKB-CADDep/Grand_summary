# API-контракт Material Library (MVP)

Черновик HTTP API для задачи **25.1** (FastAPI).  
Реализация опирается на сервисы из `src/services/` и `src/core/`.

---

## 1. Общие соглашения

| Параметр | Значение |
|----------|----------|
| Base URL | `http://127.0.0.1:8000/api` |
| Формат | JSON, UTF-8 |
| Content-Type | `application/json; charset=utf-8` |
| Ошибки | `{ "detail": "текст ошибки" }` |
| Успех без тела | `{ "ok": true }` где указано |

### Коды HTTP

| Код | Когда |
|-----|-------|
| 200 | Успешный GET/PUT/DELETE |
| 201 | Создан ресурс (POST) |
| 400 | Некорректное тело запроса |
| 404 | Материал / источник / workspace не найден |
| 409 | Конфликт (дубликат id, workspace не открыт) |
| 422 | Ошибка валидации (Pydantic) |
| 500 | Внутренняя ошибка сервера |

---

## 2. Workspace (сессия)

На один инстанс API (десктоп / dev-сервер) — **один активный workspace**: путь к папке с JSON материалов.

### POST `/workspace/open`

Открывает рабочую папку и загружает материалы. **Сбрасывает** кэш материалов.

**Тело:**
```json
{
  "directory": "C:/Users/Data/Materials"
}
```

**Ответ 200:**
```json
{
  "directory": "C:/Users/Data/Materials",
  "count": 61,
  "application_areas": ["Авиа", "Энергетика"]
}
```

**Ошибки:**
- `400` — путь не указан или не существует
- `500` — ошибка чтения файлов

### GET `/workspace`

**Ответ 200:**
```json
{
  "directory": "C:/Users/Data/Materials",
  "count": 61,
  "application_areas": ["Авиа"]
}
```

**Ошибки:**
- `404` — workspace не открыт

---

## 3. Health

### GET `/health`

**Ответ 200:**
```json
{
  "status": "ok",
  "workspace": "C:/Users/Data/Materials"
}
```

`workspace` — `null`, если папка не открыта.

---

## 4. Материалы

Сервис: `MaterialRepository` + модель `Material`.

### GET `/materials`

Список материалов (краткая форма).

**Ответ 200:**
```json
[
  {
    "id": "uuid-...",
    "name": "08Х18Н10Т",
    "areas": ["Химическая аппаратура"],
    "filename": "08Х18Н10Т.json"
  }
]
```

**Ошибки:**
- `409` — workspace не открыт

### GET `/materials/{id}`

Полный JSON материала (как в файле на диске).

**Ответ 200:** объект материала (`material_id`, `metadata`, `physical_properties`, …).

**Ошибки:**
- `404` — материал не найден

### PUT `/materials/{id}`

Сохранить материал. Тело — полный JSON; `material_id` в теле должен совпадать с `{id}`.

**Тело:** JSON материала.

**Ответ 200:**
```json
{ "ok": true, "filename": "08Х18Н10Т.json" }
```

**Ошибки:**
- `400` — несовпадение id или невалидный JSON
- `404` — материал не найден (для нового — отдельный POST в фазе 2)

---

## 5. Справочники свойств

Сервис: `PropertiesCatalog`.

### GET `/catalogs/properties`

**Ответ 200:**
```json
{
  "physical": {
    "modulus_elasticity": {
      "name": "Модуль упругости",
      "symbol": "E",
      "unit": "МПа",
      "unit_type": "Модуль упругости",
      "temperature_dependent": true
    }
  },
  "mechanical": {
    "yield_strength": { "...": "..." }
  }
}
```

---

## 6. Таблица твёрдости

Сервис: `HardnessTable`.

### GET `/catalogs/hardness/columns`

**Ответ 200:**
```json
{
  "columns": ["d10", "HB", "HRA", "HRC", "HRB", "HV", "HSD"],
  "system_unit": "HB"
}
```

### POST `/catalogs/hardness/convert`

**Тело:**
```json
{
  "value": 600,
  "from_unit": "HB",
  "to_unit": "HRC"
}
```

**Ответ 200:**
```json
{
  "result": 59.225,
  "from_unit": "HB",
  "to_unit": "HRC"
}
```

`result: null` — значение вне диапазона таблицы или неизвестная единица.

**Ошибки:**
- `400` — отсутствует `value`, `from_unit` или `to_unit`

---

## 7. Источники

Сервис: `SourceService`. Файл: `{app_directory}/source.json`.

### GET `/sources`

**Ответ 200:**
```json
{
  "property_sources": [ { "id_source": "...", "name_source": "...", "...": "..." } ],
  "strength_sources": [],
  "chemical_sources": []
}
```

### POST `/sources`

**Тело:**
```json
{
  "group": "property_sources",
  "name": "ГОСТ 12345",
  "description": "",
  "hyperlink": "https://..."
}
```

`group`: `property_sources` | `strength_sources` | `chemical_sources`.

**Ответ 201:** созданный объект источника с `id_source`.

### PUT `/sources/{id}`

**Тело:**
```json
{
  "name": "Новое имя",
  "description": "",
  "hyperlink": ""
}
```

**Ответ 200:** обновлённый источник.

**Ошибки:**
- `404` — источник не найден

### DELETE `/sources/{id}`

**Ответ 200:** `{ "ok": true }`

**Ошибки:**
- `404` — источник не найден

---

## 8. Маппинг сервисов → роутеры (25.1)

| Роутер | Сервис |
|--------|--------|
| `routers/workspace.py` | `MaterialRepository.load_materials_from_dir` |
| `routers/materials.py` | `MaterialRepository` |
| `routers/catalogs.py` | `PropertiesCatalog`, `HardnessTable` |
| `routers/sources.py` | `SourceService` |

Зависимости в `backend/dependencies.py`:
```python
def get_repository() -> MaterialRepository: ...
def get_sources() -> SourceService: ...
def get_properties() -> PropertiesCatalog: ...
def get_hardness() -> HardnessTable: ...
```

---

## 9. Вне scope MVP

- CRUD элементов (`elements_catalog`) — задача 34
- Подбор / расчёт / сравнение / Эшби — отдельные эндпоинты фазы 2
- JWT / multi-user — не требуется для десктопа
- WebSocket — не требуется

---

## 10. История изменений

| Дата | Версия | Изменение |
|------|--------|-----------|
| 2026-07-07 | 0.1 | Черновик MVP (задача 18) |
