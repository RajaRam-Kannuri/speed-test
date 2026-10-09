"""Acme CRM: a small, controlled sample application for LorvenLax end-to-end tests.

Website: /, /about, /contact, /login, /dashboard, /customers, /customers/new
API:     /api/health, /api/customers (GET, POST), /api/customers/{id} (GET, DELETE)
OpenAPI: /openapi.json

Demo login: demo@acme.test / Passw0rd!      API token: Bearer demo-token
State is in memory; POST /api/reset (token required) restores the seed data.
"""

from __future__ import annotations

import html
import itertools
import secrets
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

DEMO_USER = ("demo@acme.test", "Passw0rd!")
API_TOKEN = "demo-token"

app = FastAPI(title="Acme CRM API", version="1.0.0", description="Sample API used to demonstrate LorvenLax API testing.")
bearer = HTTPBearer(auto_error=False)

SEED = [
    {"name": "Globex Corporation", "email": "ops@globex.example.com", "plan": "Enterprise"},
    {"name": "Initech", "email": "it@initech.example.com", "plan": "Pro"},
    {"name": "Umbrella Health", "email": "admin@umbrella.example.com", "plan": "Free"},
]
customers: dict[int, dict] = {}
_ids = itertools.count(1)
sessions: set[str] = set()


def reset_data() -> None:
    global _ids
    customers.clear()
    _ids = itertools.count(1)
    for c in SEED:
        cid = next(_ids)
        customers[cid] = {"id": cid, **c}


reset_data()


# --------------------------------------------------------------------------- API

Plan = Literal["Free", "Pro", "Enterprise"]


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=50, examples=["Stark Industries"])
    email: EmailStr = Field(examples=["tony@stark.example.com"])
    plan: Plan = "Free"


class Customer(CustomerIn):
    id: int


class Error(BaseModel):
    detail: str


def require_token(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> None:
    if creds is None or creds.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")


@app.get("/api/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/customers", response_model=list[Customer], tags=["customers"])
def list_customers(plan: Optional[Plan] = None, limit: int = 50) -> list[dict]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    rows = [c for c in customers.values() if plan is None or c["plan"] == plan]
    return rows[:limit]


@app.post(
    "/api/customers",
    response_model=Customer,
    status_code=201,
    tags=["customers"],
    dependencies=[Depends(require_token)],
    responses={401: {"model": Error}, 409: {"model": Error, "description": "Email already exists"}},
)
def create_customer(body: CustomerIn) -> dict:
    if any(c["email"].lower() == body.email.lower() for c in customers.values()):
        raise HTTPException(status_code=409, detail="A customer with this email already exists")
    cid = next(_ids)
    customers[cid] = {"id": cid, **body.model_dump()}
    return customers[cid]


@app.get("/api/customers/{customer_id}", response_model=Customer, tags=["customers"], responses={404: {"model": Error}})
def get_customer(customer_id: int) -> dict:
    if customer_id not in customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customers[customer_id]


@app.delete(
    "/api/customers/{customer_id}",
    status_code=204,
    tags=["customers"],
    dependencies=[Depends(require_token)],
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def delete_customer(customer_id: int) -> Response:
    if customer_id not in customers:
        raise HTTPException(status_code=404, detail="Customer not found")
    del customers[customer_id]
    return Response(status_code=204)


@app.post("/api/reset", tags=["system"], dependencies=[Depends(require_token)], include_in_schema=False)
def reset() -> dict:
    reset_data()
    return {"status": "reset"}


# --------------------------------------------------------------------------- Website

CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c1e24}
header{background:#1f3a5f;color:#fff;padding:12px 24px;display:flex;gap:20px;align-items:center}
header a{color:#fff;text-decoration:none} header strong{margin-right:auto}
main{max-width:860px;margin:24px auto;padding:0 16px}
form{display:grid;gap:12px;max-width:420px;background:#fff;padding:20px;border-radius:8px;border:1px solid #dde}
label{display:grid;gap:4px;font-weight:500} input,select,textarea{padding:8px;font:inherit}
button{padding:9px 14px;background:#1f3a5f;color:#fff;border:0;border-radius:6px;font:inherit;cursor:pointer}
table{border-collapse:collapse;width:100%;background:#fff} td,th{border:1px solid #dde;padding:8px;text-align:left}
.error{color:#a40000;background:#fde8e8;padding:8px;border-radius:6px} .ok{color:#0a5a1a;background:#e3f6e7;padding:8px;border-radius:6px}
"""


def page(title: str, body: str, logged_in: bool = False) -> HTMLResponse:
    nav = (
        '<a href="/dashboard">Dashboard</a><a href="/customers">Customers</a><a href="/billing">Billing</a><a href="/logout">Log out</a>'
        if logged_in
        else '<a href="/">Home</a><a href="/about">About</a><a href="/contact">Contact</a><a href="/login">Sign in</a>'
    )
    return HTMLResponse(
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)} | Acme CRM</title>"
        f"<style>{CSS}</style></head><body><header><strong>Acme CRM</strong><nav style='display:flex;gap:16px'>{nav}</nav></header>"
        f"<main>{body}</main></body></html>"
    )


def logged_in(request: Request) -> bool:
    return request.cookies.get("acme_session") in sessions


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    return page("Home", "<h1>Welcome to Acme CRM</h1><p>Manage your customers in one place.</p>"
                "<p><a href='/login'>Sign in to your account</a></p>", logged_in(request))


@app.get("/about", response_class=HTMLResponse, include_in_schema=False)
def about(request: Request):
    return page("About", "<h1>About Acme</h1><p>Acme CRM has helped small teams since 2019.</p>", logged_in(request))


@app.get("/contact", response_class=HTMLResponse, include_in_schema=False)
def contact_form(request: Request, sent: int = 0):
    note = "<p class=ok role=status>Thanks! We will reply within one business day.</p>" if sent else ""
    return page("Contact", f"""<h1>Contact us</h1>{note}
      <form method=post action=/contact aria-label="Contact form">
        <label>Your name <input name=name required maxlength=40></label>
        <label>Email <input name=email type=email required></label>
        <label>Message <textarea name=message required minlength=10 maxlength=500></textarea></label>
        <button type=submit>Send message</button>
      </form>""", logged_in(request))


@app.post("/contact", include_in_schema=False)
def contact_submit(name: str = Form(""), email: str = Form(""), message: str = Form("")):
    if not name or "@" not in email or len(message) < 10:
        return page("Contact", "<h1>Contact us</h1><p class=error role=alert>Please fill in all fields.</p>")
    return RedirectResponse("/contact?sent=1", status_code=303)


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_form(request: Request, error: int = 0):
    if logged_in(request):  # like many apps, signed-in users never see the sign-in page
        return RedirectResponse("/dashboard", status_code=303)
    err = "<p class=error role=alert>Invalid email or password</p>" if error else ""
    return page("Sign in", f"""<h1>Sign in</h1>{err}
      <form method=post action=/login aria-label="Sign in form">
        <label>Email <input name=email type=email required autocomplete=username></label>
        <label>Password <input name=password type=password required autocomplete=current-password></label>
        <button type=submit>Sign in</button>
      </form>""")


@app.post("/login", include_in_schema=False)
def login_submit(email: str = Form(""), password: str = Form("")):
    if (email, password) != DEMO_USER:
        return RedirectResponse("/login?error=1", status_code=303)
    token = secrets.token_urlsafe(16)
    sessions.add(token)
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("acme_session", token, httponly=True, samesite="lax")
    return resp


@app.get("/logout", include_in_schema=False)
def logout(request: Request):
    sessions.discard(request.cookies.get("acme_session", ""))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("acme_session")
    return resp


def guard(request: Request) -> Optional[RedirectResponse]:
    return None if logged_in(request) else RedirectResponse("/login", status_code=303)


LOGIN_FORM = """<form method=post action=/login aria-label="Sign in form">
        <label>Username <input name=email type=text required autocomplete=username></label>
        <label>Password <input name=password type=password required autocomplete=current-password></label>
        <button type=submit>Sign in</button>
      </form>"""


@app.get("/billing", response_class=HTMLResponse, include_in_schema=False)
def billing(request: Request, saved: int = 0):
    # Behaves like many single-page apps: signed-out visitors get the sign-in form at the
    # same address (HTTP 200, no redirect) instead of being sent to /login.
    if not logged_in(request):
        return page("Billing", "<h1>Sign in</h1>" + LOGIN_FORM)
    note = "<p class=ok role=status>Subscription renewed</p>" if saved else ""
    return page("Billing", f"""<h1>Billing</h1>{note}
      <form method=post action=/billing aria-label="Renew subscription">
        <label>Pays * <select name=period required><option value="">Choose…</option><option>Monthly</option><option>Yearly</option></select></label>
        <label>Seats <input name=seats type=number min=1 max=50 required></label>
        <button type=submit>Renew subscription</button>
      </form>""", True)


@app.post("/billing", include_in_schema=False)
def billing_submit(request: Request, period: str = Form(""), seats: str = Form("")):
    if not logged_in(request):
        return RedirectResponse("/billing", status_code=303)
    if period not in ("Monthly", "Yearly") or not seats.isdigit():
        return page("Billing", "<h1>Billing</h1><p class=error role=alert>Choose a period and number of seats.</p>", True)
    return RedirectResponse("/billing?saved=1", status_code=303)


@app.get("/account/password", response_class=HTMLResponse, include_in_schema=False)
def change_password_form(request: Request, changed: int = 0):
    if (r := guard(request)):
        return r
    note = "<p class=ok role=status>Password changed (practice only - the demo password stays the same)</p>" if changed else ""
    return page("Change password", f"""<h1>Change password</h1>{note}
      <form method=post action=/account/password aria-label="Change password form">
        <label>Current password * <input name=current type=password required></label>
        <label>New password * <input name=new type=password required minlength=8></label>
        <label>New password again * <input name=again type=password required minlength=8></label>
        <button type=submit>Change password</button>
      </form>""", True)


@app.post("/account/password", include_in_schema=False)
def change_password(request: Request, current: str = Form(""), new: str = Form(""), again: str = Form("")):
    if (r := guard(request)):
        return r
    if current != DEMO_USER[1] or len(new) < 8 or new != again:
        return page("Change password", "<h1>Change password</h1><p class=error role=alert>Check the passwords and try again.</p>", True)
    return RedirectResponse("/account/password?changed=1", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    if (r := guard(request)):
        return r
    plans = {p: sum(1 for c in customers.values() if c["plan"] == p) for p in ("Free", "Pro", "Enterprise")}
    items = "".join(f"<li>{p}: {n}</li>" for p, n in plans.items())
    return page("Dashboard", f"<h1>Dashboard</h1><p data-testid=customer-total>{len(customers)} customers</p>"
                f"<ul>{items}</ul><p><a href='/customers/new'>Add a customer</a></p><p><a href='/account/password'>Change password</a></p>", True)


@app.get("/customers", response_class=HTMLResponse, include_in_schema=False)
def customer_list(request: Request, created: int = 0):
    if (r := guard(request)):
        return r
    note = "<p class=ok role=status>Customer created</p>" if created else ""
    rows = "".join(
        f"<tr><td>{c['id']}</td><td>{html.escape(c['name'])}</td><td>{html.escape(c['email'])}</td><td>{c['plan']}</td></tr>"
        for c in customers.values()
    )
    return page("Customers", f"""<h1>Customers</h1>{note}<p><a href="/customers/new">New customer</a></p>
      <table data-testid=customer-table><caption>All customers</caption>
      <thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Plan</th></tr></thead><tbody>{rows}</tbody></table>""", True)


@app.get("/customers/new", response_class=HTMLResponse, include_in_schema=False)
def customer_new(request: Request, error: str = ""):
    if (r := guard(request)):
        return r
    err = f"<p class=error role=alert>{html.escape(error)}</p>" if error else ""
    return page("New customer", f"""<h1>New customer</h1>{err}
      <form method=post action=/customers/new aria-label="New customer form">
        <label>Company name <input name=name required maxlength=50></label>
        <label>Contact email <input name=email type=email required></label>
        <label>Plan <select name=plan><option>Free</option><option>Pro</option><option>Enterprise</option></select></label>
        <button type=submit>Create customer</button>
      </form>""", True)


@app.post("/customers/new", include_in_schema=False)
def customer_create(request: Request, name: str = Form(""), email: str = Form(""), plan: str = Form("Free")):
    if (r := guard(request)):
        return r
    try:
        body = CustomerIn(name=name, email=email, plan=plan)
    except Exception:
        return RedirectResponse("/customers/new?error=Please+enter+a+name+and+a+valid+email", status_code=303)
    if any(c["email"].lower() == body.email.lower() for c in customers.values()):
        return RedirectResponse("/customers/new?error=That+email+is+already+used", status_code=303)
    cid = next(_ids)
    customers[cid] = {"id": cid, **body.model_dump()}
    return RedirectResponse("/customers?created=1", status_code=303)
