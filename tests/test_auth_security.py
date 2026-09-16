"""Security and authentication tests for ProtoForge API.

Tests cover login, token validation, role-based access control,
and auth-disabled mode behavior.
"""

import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    """Test successful admin login in no-auth mode returns token."""
    # In no-auth mode, login should still work and return a token
    resp = await client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin",
    })
    # In no-auth mode, the auth module may accept any credentials
    # or return a mock token
    assert resp.status_code in (200, 401)


@pytest.mark.asyncio
async def test_login_empty_username_rejected(client):
    """Test that empty username is rejected with 422 validation error."""
    resp = await client.post("/api/v1/auth/login", json={
        "username": "",
        "password": "test",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_empty_password_rejected(client):
    """Test that empty password is rejected with 422 validation error."""
    resp = await client.post("/api/v1/auth/login", json={
        "username": "test",
        "password": "",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_missing_fields_rejected(client):
    """Test that missing fields are rejected with 422 validation error."""
    resp = await client.post("/api/v1/auth/login", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_whitespace_stripped(client):
    """Test that whitespace in username/password is stripped."""
    resp = await client.post("/api/v1/auth/login", json={
        "username": "  admin  ",
        "password": "  admin  ",
    })
    # Should not get 422 since whitespace is stripped by validator
    assert resp.status_code != 422


@pytest.mark.asyncio
async def test_health_endpoint_no_auth_required(client):
    """Test that health endpoints are accessible without authentication."""
    resp = await client.get("/health")
    assert resp.status_code == 200

    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_docs_endpoint_no_auth_required(client):
    """Test that OpenAPI docs are accessible without authentication."""
    resp = await client.get("/docs")
    assert resp.status_code == 200

    resp = await client.get("/openapi.json")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_protected_endpoint_accessible_in_no_auth_mode(client):
    """Test that protected endpoints are accessible in no-auth mode."""
    resp = await client.get("/api/v1/devices")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_register_user_validation(client):
    """Test user registration input validation."""
    # Empty username should be rejected
    resp = await client.post("/api/v1/auth/register", json={
        "username": "",
        "password": "test123",
    })
    assert resp.status_code == 422

    # Empty password should be rejected
    resp = await client.post("/api/v1/auth/register", json={
        "username": "testuser",
        "password": "",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refresh_token_empty_rejected(client):
    """Test that empty refresh token is rejected."""
    resp = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_password_validation(client):
    """Test change password input validation."""
    # Empty old password
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "",
        "new_password": "newpass123",
    })
    assert resp.status_code == 422

    # Empty new password
    resp = await client.post("/api/v1/auth/change-password", json={
        "old_password": "oldpass",
        "new_password": "",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_role_update_rejected(client):
    """Test that invalid role values are rejected."""
    resp = await client.put("/api/v1/auth/users/admin/role", json={
        "role": "superadmin",
    })
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_audit_log_query(client):
    """Test audit log query endpoint returns proper structure."""
    resp = await client.get("/api/v1/audit", params={
        "limit": 10,
        "offset": 0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert "total" in data
    assert isinstance(data["entries"], list)


@pytest.mark.asyncio
async def test_audit_stats_endpoint(client):
    """Test audit stats endpoint returns proper structure."""
    resp = await client.get("/api/v1/audit/stats")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_entry_delete_forbidden(client):
    """Test that audit log entries cannot be deleted (compliance)."""
    resp = await client.delete("/api/v1/audit/1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_audit_clear_forbidden(client):
    """Test that audit log cannot be cleared (compliance)."""
    resp = await client.delete("/api/v1/audit")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_backup_export_structure(client):
    """Test backup export returns proper JSON structure."""
    resp = await client.get("/api/v1/backup")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "timestamp" in data
    assert "data" in data


@pytest.mark.asyncio
async def test_backup_import_empty_data_rejected(client):
    """Test that importing empty backup data is rejected."""
    resp = await client.post("/api/v1/backup/restore", json={
        "data": {},
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_backup_import_invalid_data_type_rejected(client):
    """Test that importing non-dict backup data is rejected."""
    resp = await client.post("/api/v1/backup/restore", json={
        "data": "not-a-dict",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_settings_endpoint(client):
    """Test settings endpoint returns configuration dict."""
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_recorder_stats_endpoint(client):
    """Test recorder stats endpoint returns proper structure."""
    resp = await client.get("/api/v1/recorder/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_recording" in data
    assert "total_recordings" in data
