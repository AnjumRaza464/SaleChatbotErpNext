"""Security tests for role-based access.

They run entirely offline: the agent and ERPNext client are stubbed, so the
tests exercise authentication, module authorization, ownership checks and the
tool allowlists without network access.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Isolated environment before the app is imported.
_tmp = tempfile.mkdtemp(prefix="erp-rbac-")
os.environ.update({
    "DATA_DIR": _tmp,
    "ERPNEXT_BASE_URL": "http://erpnext.invalid",
    "ERPNEXT_API_KEY": "k",
    "ERPNEXT_API_SECRET": "s",
    "OPENAI_API_KEY": "sk-test",
    "ADMIN_EMAIL": "admin@test.local",
    "ADMIN_PASSWORD": "admin-pass-123",
    "SESSION_SECRET": "test-secret",
})

from app.agent import agent as agent_mod  # noqa: E402
from app.agent.scope import ADMIN_MODULE, COMMON_TOOLS, MODULE_TOOLS, set_scope, tools_for  # noqa: E402
from app.api.routes import chat as chat_route  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.core.errors import ValidationError  # noqa: E402
from app.main import app, _bootstrap_admin  # noqa: E402
from app.services.erpnext import context as ctx_mod  # noqa: E402
from app.services.erpnext.modules import generic  # noqa: E402
from app.services.erpnext.registry import get_registry  # noqa: E402
from app.storage.db import get_db  # noqa: E402
from app.core.config import get_settings  # noqa: E402

SALES_PW = "sales-pass-123"
HR_PW = "hr-pass-1234"


async def _fake_agent(message, history, attachments=None, module=ADMIN_MODULE, user_id=None):
    """Stand-in for run_agent: records the module it was called with."""
    yield agent_mod.AgentEvent("token", {"text": f"ok:{module}"})
    yield agent_mod.AgentEvent("done", {"content": f"ok:{module}", "datasets": [{"title": "T", "columns": ["a"], "rows": [{"a": 1}], "summary": {}, "tool": "x"}], "tool_calls": []})


@pytest.fixture(scope="module", autouse=True)
def _setup(request):
    db = get_db()
    _bootstrap_admin(db, get_settings())
    db.create_user("sales@test.local", "Sales User", hash_password(SALES_PW), ["sales"])
    db.create_user("hr@test.local", "HR User", hash_password(HR_PW), ["hr"])
    original = chat_route.run_agent
    chat_route.run_agent = _fake_agent
    ctx_mod._ctx.loaded = True  # skip ERPNext calls in lifespan-free tests
    yield
    chat_route.run_agent = original


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(c: AsyncClient, email: str, password: str) -> None:
    r = await c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------- 1. anonymous
@pytest.mark.asyncio
async def test_anonymous_requests_are_rejected(client):
    assert (await client.post("/api/chat", json={"message": "hi", "module": "sales", "attachment_ids": []})).status_code == 401
    assert (await client.get("/api/conversations")).status_code == 401
    assert (await client.get("/api/admin/users")).status_code == 401


# -------------------------------------------------------- 2. module authorization
@pytest.mark.asyncio
async def test_sales_user_cannot_use_hr_module(client):
    await _login(client, "sales@test.local", SALES_PW)
    r = await client.post("/api/chat", json={"message": "attendance", "module": "hr", "attachment_ids": []})
    assert r.status_code == 403
    r = await client.post("/api/chat", json={"message": "sales", "module": "sales", "attachment_ids": []})
    assert r.status_code == 200 and "ok:sales" in r.text
    assert (await client.get("/api/conversations", params={"module": "hr"})).status_code == 403
    assert (await client.get("/api/admin/users")).status_code == 403


# ------------------------------------------------------ 3. tool / doctype scoping
def test_registry_exposes_only_allowlisted_tools():
    reg = get_registry()
    all_names = {t.name for t in reg.tools}
    for module in MODULE_TOOLS:
        exposed = {s["function"]["name"] for s in reg.openai_schemas(tools_for(module))}
        assert exposed == (MODULE_TOOLS[module] | COMMON_TOOLS) & all_names
        # HR salary tool never leaks into other modules
        if module != "hr":
            assert "get_salary_register" not in exposed
            assert "get_attendance_summary" not in exposed
    assert {s["function"]["name"] for s in reg.openai_schemas(None)} == all_names


@pytest.mark.asyncio
async def test_registry_refuses_out_of_scope_tool_even_if_named():
    reg = get_registry()
    with pytest.raises(PermissionError):
        await reg.call("get_sales_summary", None, {}, tools_for("hr"))


def test_generic_tools_respect_doctype_allowlist():
    set_scope("sales")
    with pytest.raises(ValidationError):
        generic._check_doctype("Attendance")
    with pytest.raises(ValidationError):
        generic._check_doctype("Salary Slip")
    generic._check_doctype("Sales Invoice")  # allowed
    set_scope("hr")
    generic._check_doctype("Attendance")
    with pytest.raises(ValidationError):
        generic._check_doctype("Sales Invoice")
    set_scope("accounts")
    generic._check_doctype("Journal Entry")
    generic._check_doctype("GL Entry")
    with pytest.raises(ValidationError):
        generic._check_doctype("Salary Slip")
    with pytest.raises(ValidationError):
        generic._check_doctype("Stock Entry")
    set_scope(ADMIN_MODULE)
    generic._check_doctype("Sales Invoice")
    generic._check_doctype("Attendance")
    with pytest.raises(ValidationError):  # security doctypes stay blocked for everyone
        generic._check_doctype("User")


# ------------------------------------------------------------ 4. ownership checks
@pytest.mark.asyncio
async def test_conversations_and_exports_are_private(client):
    await _login(client, "sales@test.local", SALES_PW)
    r = await client.post("/api/chat", json={"message": "today sales", "module": "sales", "attachment_ids": []})
    assert r.status_code == 200
    convs = (await client.get("/api/conversations", params={"module": "sales"})).json()
    assert convs and convs[0]["module"] == "sales"
    conv = (await client.get(f"/api/conversations/{convs[0]['id']}")).json()
    dataset_id = conv["messages"][-1]["datasets"][0]["id"]
    message_id = conv["messages"][-1]["id"]
    assert (await client.get(f"/api/export/dataset/{dataset_id}")).status_code == 200

    # Another user cannot see or export it.
    other = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    async with other:
        await _login(other, "hr@test.local", HR_PW)
        assert (await other.get(f"/api/conversations/{convs[0]['id']}")).status_code == 404
        assert (await other.get(f"/api/export/dataset/{dataset_id}")).status_code == 404
        assert (await other.get(f"/api/export/message/{message_id}")).status_code == 404
        assert (await other.delete(f"/api/conversations/{convs[0]['id']}")).status_code == 404
        hr_list = (await other.get("/api/conversations")).json()
        assert all(c["id"] != convs[0]["id"] for c in hr_list)


@pytest.mark.asyncio
async def test_attachment_of_other_user_is_rejected(client):
    db = get_db()
    hr = db.get_user_by_email("hr@test.local")
    up = db.save_upload("x.csv", str(Path(_tmp) / "x.csv"), "csv", 3, "", "", hr["id"])
    await _login(client, "sales@test.local", SALES_PW)
    r = await client.post("/api/chat", json={"message": "analyse", "module": "sales", "attachment_ids": [up["id"]]})
    assert r.status_code == 200 and "Upload not found" in r.text  # streamed error event


# --------------------------------------------------------- 5. admin & lifecycle
@pytest.mark.asyncio
async def test_admin_manages_users_and_disabled_user_is_locked_out(client):
    await _login(client, "admin@test.local", "admin-pass-123")
    me = (await client.get("/api/auth/me")).json()
    assert me["is_admin"] and set(me["modules"]) >= {"sales", "warehouse", "stock", "hr", "accounts", "all"}
    r = await client.post("/api/admin/users", json={"email": "temp@test.local", "full_name": "Temp", "password": "temp-pass-123", "modules": ["stock", "warehouse"]})
    assert r.status_code == 201 and r.json()["modules"] == ["stock", "warehouse"]
    uid = r.json()["id"]
    assert (await client.post("/api/admin/users", json={"email": "bad@test.local", "full_name": "B", "password": "bad-pass-123", "modules": ["payroll"]})).status_code == 400

    temp = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    async with temp:
        await _login(temp, "temp@test.local", "temp-pass-123")
        assert (await temp.post("/api/chat", json={"message": "x", "module": "stock", "attachment_ids": []})).status_code == 200
        assert (await temp.post("/api/chat", json={"message": "x", "module": "sales", "attachment_ids": []})).status_code == 403
        # Admin disables the user: the existing session stops working immediately.
        assert (await client.patch(f"/api/admin/users/{uid}", json={"is_active": False})).status_code == 200
        assert (await temp.get("/api/auth/me")).status_code == 401
    assert (await client.delete(f"/api/admin/users/{uid}")).status_code == 204
    audit = (await client.get("/api/admin/audit")).json()
    assert any(a["action"] == "user_deleted" for a in audit)
