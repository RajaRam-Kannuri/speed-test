# Progress, verification and known limitations

Last updated: 2026-10-08. "Verified" means exercised by an automated test or a recorded run in this repository, not just implemented.

## Acceptance workflows

| Workflow | Status | Evidence |
|---|---|---|
| A. Website: project → URL → discover → generate → review → run → real results | **Verified** | `backend/tests/test_integration_workflows.py::test_workflow_a_website` (API level) and `e2e/tests/workflows.spec.ts` "Workflow A" (UI). On the sample app: 7 pages discovered with login, 21 tests generated, 21/21 passed in ~10–25 s with 2 workers; HTML and PDF reports, screenshots |
| B. API: import OpenAPI → endpoints → generate → run → validate responses → report | **Verified** | `test_workflow_b_api` and e2e "Workflow B": 5 endpoints, 24 tests (positive, auth, validation, boundary, malformed JSON, duplicate, 404, schema), 24/24 passed |
| C. Natural language: instructions → steps → review/edit → code → validate → run → results | **Verified (rule engine)** | `test_workflow_c_natural_language` and e2e "Workflow C": the spec's example sentence becomes 14 steps that log in, create a customer and assert it is listed; the code compiles; the run passes |
| Visual builder: build, reorder, save, validate, run without code | **Verified** | e2e "Visual builder" |
| Docker Compose deployment | **Verified with one substitution** | All six UI e2e tests passed against `docker compose up` (non-root worker, S3 artifact storage, SSRF guard checked inside the network). MinIO's image could not be pulled in this sandbox (Docker Hub rate limit, quay.io blocked), so an S3-compatible stand-in (moto) replaced it for that run; the compose file itself uses MinIO |
| CI/CD trigger | **Verified (script)** | `docs/ci/lorvenlax_run.py` ran against the Docker stack with a project token: 24/24 passed, exit 0, 24 Allure result files. The GitHub/GitLab/Jenkins/Azure wrappers only call this script; they were not run on those CI systems |

## Test suites

| Suite | Count | Result |
|---|---|---|
| Backend unit + integration (`cd backend && pytest`) | 60 | 60 passed (~70 s, real Postgres, real Playwright runs) |
| UI end-to-end (`cd e2e && npx playwright test`) | 6 | 6 passed against the local stack and against Docker Compose |
| Frontend type check + production build | – | `tsc --noEmit` clean, `next build` succeeds |

Defects found and fixed by these tests during development included: a sample-app seed that broke its own response schema (found by generated API tests), generated navigation tests that assumed a logged-in menu, a stale result panel, reports racing the final run status, a test timeout masking locator errors, shared header dictionaries between generated API tests, and credential chat messages treated as instructions.

## Phase status

### Phase 1 – Functional SaaS foundation: **complete**
Registration and sign-in (session cookie + CSRF), organizations, roles, invitations (share link), projects, environments with encrypted secrets, test cases and steps, suites, asynchronous Playwright execution (Celery worker), execution history, artifacts, basic reports, audit log, rate limits, quotas, Docker Compose.

### Phase 2 – AI test generation: **complete with an AI caveat**
Website discovery (with login, page limits and destructive-link skipping), scenario generation, Playwright code generation, validation (static + compile), natural-language tests, the assistant conversation.
*Caveat:* the Claude path (`agents/llm.py`, `ai_plan` functions, `plan_with_ai`) is implemented and unit-tested with a stub provider, but **has not been run against the live Claude API** because no API key was available here. Every workflow was verified with the deterministic agents, which run whenever no key is configured, and the UI labels which engine planned each test.

### Phase 3 – API testing: **complete**
OpenAPI 3.x (JSON/YAML), Swagger 2.0 and Postman v2.1 import; import from URL or file; single manual requests; endpoint discovery; generation of positive, negative, boundary, auth, schema, duplicate and not-found tests; chained requests with stored variables; response schema validation (Ajv); request/response evidence. Swagger and Postman parsing are unit-tested; only OpenAPI 3.1 (FastAPI) was run end to end.

### Phase 4 – No-code testing: **partially complete**
- Done: visual builder (drag-and-drop and keyboard reordering, add/edit/remove/duplicate steps, all actions including API requests, extract and variables), duplicate tests, execution history.
- **Pending: browser recorder.** A recorder for third-party sites needs a browser extension (an ordinary web page cannot observe another site's tab). Not started.
- **Pending: reusable step components / page objects** shared across tests.

### Phase 5 – Advanced intelligence: **partially complete**
- Done: self-healing suggestions with confidence, accept/reject, audit trail (integration-tested); failure classification into all required categories, with verified evidence kept apart from hypotheses; flaky-test detection; recommendations.
- **Pending:** regression test selection from code changes, GitHub repository integration, Jira import, test optimisation (deduplication and minimisation).

### Phase 6 – Commercial SaaS: **not started** beyond the basics
Organization quotas and usage counting exist. Pending: subscription plans and billing (Stripe), an admin console, OpenTelemetry/Prometheus/Grafana, production IaC (AWS), and email delivery for invitations.

## Known limitations

- **Browsers:** Chromium was verified. Firefox and WebKit are selectable and included in the Docker image, but no run used them during verification (the local sandbox had only Chromium).
- **Headed mode:** the API accepts `headless: false`, but cloud workers have no display, so it is useful only on self-hosted workers. The UI does not offer it.
- **Workspaces:** tenancy is organization → project. The intermediate "workspace" level from the brief is not implemented.
- **Test data:** environments and variables (plain or secret), unique-data helpers (`{{timestamp}}`, `{{random}}`) and chained API variables are supported. Data-driven datasets and data cleanup actions are not.
- **Website planner scope:** it plans tests for what it can observe (pages, forms, links, tables). Business rules that leave no trace in the UI need the assistant, the builder or an AI provider. Expectations it infers are labelled "Inferred" for review.
- **Discovery** is same-origin, capped at 50 pages and depth 5, and does not execute flows that need data the platform cannot see.
- **Execution isolation:** each run gets its own process group, work directory, scrubbed environment and time limit, inside a capability-free, non-root container with CPU/memory/PID limits. Network egress is enforced by the in-engine guard. A production deployment should add a network policy as well (see SETUP.md).
- **Videos and traces** are kept for failed tests only by default (configurable per run via the API); screenshots are always kept.
- **Invitations** return a link to share; no email is sent.
