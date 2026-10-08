"""Authentication, CSRF, RBAC and cross-tenant isolation."""

from app.db import SessionLocal
from app.models import Membership, TestArtifact, TestExecution, TestResult

from .conftest import Api, make_project, register


def _case(api, project_id, title="Smoke"):
    r = api.post(f"/api/projects/{project_id}/test-cases", json={
        "title": title, "steps": [{"action": "navigate", "value": "https://example.com/"}, {"action": "assert_title", "value": "Example"}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_register_login_logout(client):
    api, org_id, email = register(client)
    me = api.get("/api/auth/me").json()
    assert me["email"] == email and me["organizations"][0]["role"] == "owner"
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "Sup3rSecret!42"}).status_code == 200
    assert api.get("/api/auth/me").status_code == 200


def test_weak_password_and_duplicate_email_rejected(client):
    r = client.post("/api/auth/register", json={"name": "a", "email": "weak@example.com", "password": "short", "organization_name": "o"})
    assert r.status_code == 422
    api, _, email = register(client)
    r = client.post("/api/auth/register", json={"name": "a", "email": email, "password": "Sup3rSecret!42", "organization_name": "o"})
    assert r.status_code == 409


def test_csrf_required_for_cookie_mutations(api):
    r = api.c.post(f"/api/organizations/{api.org_id}/projects", json={"name": "No CSRF"})
    assert r.status_code == 403
    r = api.c.post(f"/api/organizations/{api.org_id}/projects", json={"name": "Bad CSRF"}, headers={"x-csrf-token": "forged"})
    assert r.status_code == 403
    assert api.post(f"/api/organizations/{api.org_id}/projects", json={"name": "With CSRF"}).status_code == 201


def test_cross_tenant_isolation(client, api):
    project = make_project(api, "Tenant A project", "https://example.com")
    case = _case(api, project["id"])
    env = api.get(f"/api/projects/{project['id']}/environments").json()[0]
    api.put(f"/api/projects/{project['id']}/environments/{env['id']}/variables", json={"key": "password", "value": "TopSecret1", "is_secret": True})

    # Fabricate an execution, result and artifact directly so artifact access can be tested without running Playwright.
    with SessionLocal() as db:
        ex = TestExecution(project_id=project["id"], status="passed", total=1, passed=1)
        db.add(ex)
        db.flush()
        res = TestResult(execution_id=ex.id, test_case_id=case["id"], test_title="Smoke", status="passed")
        db.add(res)
        db.flush()
        art = TestArtifact(project_id=project["id"], execution_id=ex.id, result_id=res.id, kind="log", name="x",
                           content_type="text/plain", storage_key="org/x/y.txt")
        db.add(art)
        db.commit()
        ex_id, res_id, art_id = ex.id, res.id, art.id

    # Tenant B: separate client (separate cookie jar).
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as other:
        b, b_org, _ = register(other, "Tenant B")
        pid, cid = project["id"], case["id"]
        forbidden = [
            ("get", f"/api/projects/{pid}"),
            ("get", f"/api/projects/{pid}/test-cases"),
            ("get", f"/api/projects/{pid}/test-cases/{cid}"),
            ("get", f"/api/projects/{pid}/environments"),
            ("get", f"/api/projects/{pid}/executions"),
            ("get", f"/api/executions/{ex_id}"),
            ("get", f"/api/results/{res_id}"),
            ("get", f"/api/artifacts/{art_id}"),
            ("get", f"/api/executions/{ex_id}/report"),
            ("get", f"/api/organizations/{api.org_id}"),
            ("get", f"/api/organizations/{api.org_id}/projects"),
            ("get", f"/api/organizations/{api.org_id}/members"),
            ("get", f"/api/organizations/{api.org_id}/dashboard"),
            ("patch", f"/api/projects/{pid}"),
            ("post", f"/api/projects/{pid}/test-cases"),
            ("post", f"/api/projects/{pid}/executions"),
            ("post", f"/api/projects/{pid}/discoveries"),
            ("post", f"/api/projects/{pid}/api-collections"),
            ("delete", f"/api/projects/{pid}/test-cases/{cid}"),
            ("delete", f"/api/projects/{pid}"),
        ]
        bodies = {"patch": {"name": "hijack"}, "post": {"title": "x", "steps": [], "test_case_ids": [cid], "url": "https://example.com",
                                                       "authorized": True, "spec_text": "{}"}}
        for method, url in forbidden:
            kwargs = {"json": bodies[method]} if method in bodies else {}
            r = getattr(b, method)(url, **kwargs)
            assert r.status_code == 404, (method, url, r.status_code, r.text)
        # Tenant B's dashboard does not include tenant A's data.
        dash = b.get(f"/api/organizations/{b_org}/dashboard").json()
        assert dash["projects"] == 0 and dash["tests"] == 0

    # Tenant A's data is untouched and secrets are never returned.
    assert api.get(f"/api/projects/{project['id']}").json()["name"] == "Tenant A project"
    env = api.get(f"/api/projects/{project['id']}/environments").json()[0]
    pw = next(v for v in env["variables"] if v["key"] == "password")
    assert pw["value"] is None and pw["has_value"] is True
    assert "TopSecret1" not in api.get(f"/api/projects/{project['id']}/environments").text


def test_viewer_role_is_read_only(client, api):
    project = make_project(api, "RBAC", "https://example.com")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as other:
        viewer, _, viewer_email = register(other, "Viewer home org")
        inv = api.post(f"/api/organizations/{api.org_id}/invitations", json={"email": viewer_email, "role": "viewer"}).json()
        assert viewer.post(f"/api/invitations/{inv['accept_token']}/accept").status_code == 200
        assert viewer.get(f"/api/projects/{project['id']}").status_code == 200
        r = viewer.post(f"/api/projects/{project['id']}/test-cases", json={"title": "x", "steps": []})
        assert r.status_code == 403
        assert viewer.get(f"/api/organizations/{api.org_id}/audit-logs").status_code == 403


def test_api_token_is_scoped_to_its_project(client, api):
    p1 = make_project(api, "Token P1", "https://example.com")
    p2 = make_project(api, "Token P2", "https://example.com")
    tok = api.post(f"/api/organizations/{api.org_id}/api-tokens", json={"name": "ci", "project_id": p1["id"]}).json()["token"]
    h = {"authorization": f"Bearer {tok}"}
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as ci:
        assert ci.get(f"/api/projects/{p1['id']}/test-cases", headers=h).status_code == 200
        assert ci.get(f"/api/projects/{p2['id']}/test-cases", headers=h).status_code == 404
        # Token auth is not subject to cookie CSRF.
        assert ci.post(f"/api/projects/{p1['id']}/test-cases", headers=h, json={"title": "From CI", "steps": []}).status_code == 201
        assert ci.get(f"/api/projects/{p1['id']}/test-cases", headers={"authorization": "Bearer llx_invalid"}).status_code == 401


def test_last_owner_cannot_be_demoted(api):
    members = api.get(f"/api/organizations/{api.org_id}/members").json()["members"]
    r = api.patch(f"/api/organizations/{api.org_id}/members/{members[0]['id']}", json={"role": "member"})
    assert r.status_code == 409


def test_audit_log_records_actions_without_secret_values(api):
    project = make_project(api, "Audited", "https://example.com")
    env = api.get(f"/api/projects/{project['id']}/environments").json()[0]
    api.put(f"/api/projects/{project['id']}/environments/{env['id']}/variables", json={"key": "token", "value": "VerySecretValue9", "is_secret": True})
    logs = api.get(f"/api/organizations/{api.org_id}/audit-logs").json()
    actions = [l["action"] for l in logs]
    assert "project.created" in actions and "environment.variable_set" in actions
    assert "VerySecretValue9" not in str(logs)


def test_runs_blocked_for_invalid_tests(api):
    project = make_project(api, "Invalid run", "https://example.com")
    r = api.post(f"/api/projects/{project['id']}/test-cases", json={"title": "No assertion", "steps": [{"action": "navigate", "value": "/"}]})
    case = r.json()
    assert case["validation_status"] == "invalid"
    r = api.post(f"/api/projects/{project['id']}/executions", json={"test_case_ids": [case["id"]]})
    assert r.status_code == 422
    assert "validation errors" in str(r.json()["detail"])
