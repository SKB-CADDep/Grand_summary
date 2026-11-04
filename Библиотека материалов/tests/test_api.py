import pytest
from fastapi.testclient import TestClient
from backend.main import app
from tests.conftest import DATA_DIR

@pytest.fixture
def open_workspace(client):
    response = client.post("/api/workspace/open",
        json={"directory": DATA_DIR})
    assert response.status_code == 200
    return response.json()

@pytest.fixture
def material_id(client, open_workspace):
    materials = client.get("/api/materials").json()
    assert len(materials) > 0
    id = materials[0]["id"]
    return id

@pytest.fixture
def source_id(client):
    response = client.post("/api/sources",
        json={
            "group": "property_sources",
            "name": "Тест API",
            "description": "smoke",
            "hyperlink": "https://example.com",
        })
    assert response.status_code == 201
    sid = response.json()["id_source"]
    yield sid
    client.delete(f"/api/sources/{sid}")

def test_get_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status":"ok", "workspace":None}

def test_workspace_open(client):
    user_data = {"directory": "C:\\Users\\Лиза\\Desktop\\jbsidian\\data"}
    response = client.post("/api/workspace/open", json=user_data)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] > 0
    assert data["directory"] == user_data["directory"]

def test_get_workspace(client, open_workspace):
    response = client.get("/api/workspace")
    data = response.json()
    assert response.status_code == 200
    assert data["count"] > 0
    assert data["directory"] == open_workspace["directory"]

def test_get_health_after_open(client, open_workspace):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status":"ok", "workspace": "C:\\Users\\Лиза\\Desktop\\jbsidian\\data"}

def test_get_materials(client, open_workspace):
    response = client.get("/api/materials")
    data = response.json()
    assert isinstance(data, list)
    item = data[0]
    assert {"id", "name", "areas", "filename"} <= set(item.keys())
    assert response.status_code == 200

def test_get_materials_by_id(client, material_id):
    response = client.get(f"/api/materials/{material_id}")
    assert response.status_code == 200
    assert response.json()["material_id"] == material_id

def test_get_properties(client):
    response = client.get(f"/api/catalogs/properties")
    data = response.json()
    assert response.status_code == 200
    assert len(data["physical"]) > 0
    assert len(data["mechanical"]) > 0

def test_get_columns(client):
    response = client.get("/api/catalogs/hardness/columns")
    data = response.json()
    assert response.status_code == 200
    assert data["columns"] is not None
    assert data["system_unit"] == "HB"

def test_post_convert(client):
    usage_data = {"value":600, "from_unit": "HB", "to_unit": "HRC"}
    response = client.post("/api/catalogs/hardness/convert", json=usage_data)
    data = response.json()
    assert response.status_code == 200
    assert data["result"] is not None

def test_get_sources(client):
    response = client.get("/api/sources")
    assert response.status_code == 200
    data = response.json()
    assert "property_sources" in data.keys()
    assert "strength_sources" in data.keys()
    assert "chemical_sources" in data.keys()

def test_post_sources(client):
    usage_data = {
        "group": "property_sources",
        "name": "Тест API",
        "description": "smoke",
        "hyperlink": "https://example.com"
    }
    response = client.post("/api/sources", json=usage_data)
    data = response.json()
    assert response.status_code == 201
    assert data["id_source"] is not None

def test_get_sources_by_id(client, source_id):
    response = client.get(f"/api/sources/{source_id}")
    assert response.status_code == 200

def test_update_source(client, source_id):
    usage_data = { "name": "Тест API (обновлён)", "description": "smoke", "hyperlink": "" }
    response = client.put(f"/api/sources/{source_id}", json=usage_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name_source"] == "Тест API (обновлён)"

def test_delete_source(client, source_id):
    response = client.delete(f"/api/sources/{source_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True

def test_get_false_workspace(client):
    user_data = {"directory": "/no/such/data"}
    response = client.post("/api/workspace/open", json=user_data)
    assert response.status_code == 400
    assert response.json()["detail"] == "Путь не существует"

def test_get_false_materials(client):
    response = client.get("/api/materials")
    assert response.status_code == 409
    assert response.json()["detail"] == "Workspace не открыт"

def test_get_nonexistent_id(client, open_workspace):
    response = client.get("/api/materials/0000000-0000000000-00000000000")
    assert response.status_code == 404

def test_get_nonexistant_source(client):
    response = client.get("/api/sources/000000000-0000")
    assert response.status_code == 404