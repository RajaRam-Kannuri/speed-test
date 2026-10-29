# Setup and deployment

## Option 1: Docker Compose (recommended)

Requirements: Docker 24+ with Compose v2, about 6 GB of disk for the images.

```bash
python3 scripts/setup-env.py  # creates .env with generated secret keys and passwords
docker compose up -d --build
docker compose ps        # api should be "healthy"
```

Open http://localhost:3000 and register; the first account owns a new organization. Services:

| Service | Port | Notes |
|---|---|---|
| web | 3000 | Next.js app; proxies `/api` to `api` |
| api | 8000 | FastAPI. Interactive API docs at http://localhost:8000/docs |
| worker | – | Runs discovery, generation and test executions (Chromium, Firefox and WebKit included) |
| migrate | – | Runs `alembic upgrade head` once, then exits |
| postgres, redis | internal | Data and queue. Artifacts are kept in the `artifacts` volume (or S3, see below) |
| sample | 8100 | Acme CRM sample app (`http://sample:8100` from inside the stack) |

**Builds behind a TLS-intercepting proxy:** set `EXTRA_CA_FILE=/path/to/ca.pem` before `docker compose build`. The CA is mounted only while dependencies install and is not stored in any image.

## Option 2: Local development

Requirements: Python 3.12+, Node.js 22, PostgreSQL 16, Redis 7, and Playwright browsers (`npx playwright install` in `engine/`, or set `PLAYWRIGHT_BROWSERS_PATH` to an existing install).

```bash
# Database
createuser -s lorvenlax; createdb -O lorvenlax lorvenlax   # password: lorvenlax (see LLX_DATABASE_URL)

# Engine
cd engine && npm ci && npm run build && cd ..

# Backend
pip install -r backend/requirements-dev.txt && pip install -e .
echo "LLX_ALLOWED_PRIVATE_HOSTS=127.0.0.1,localhost" > backend/.env   # lets tests reach the local sample app
(cd backend && alembic upgrade head)

# Frontend
cd frontend && npm ci && npm run build && cd ..

# Start API, worker, sample app and web (logs in .dev/)
scripts/dev-services.sh start api worker sample web
```

### Running the tests

```bash
cd backend && pytest                    # uses database lorvenlax_test (created automatically) and starts the sample app on :8101
cd e2e && npm ci && npx playwright test # needs the stack from dev-services.sh; E2E_SAMPLE_URL defaults to http://127.0.0.1:8100
```

Against the Docker stack: `E2E_SAMPLE_URL=http://sample:8100 npx playwright test`.

**Storing artifacts in S3:** by default screenshots, videos and reports go to the `artifacts` Docker volume. To use AWS S3 or any S3-compatible service, uncomment the `LLX_STORAGE_BACKEND=s3` and `LLX_S3_*` lines in `.env`.

## Email and password resets

With email set up, people reset their own password from **Forgot password?** on the sign-in page. They get a
link that works once and expires after 60 minutes (`LLX_PASSWORD_RESET_MINUTES`). Invitations are emailed too.
After any password change the user is signed out on every device, gets a "your password was changed" email, and
the change is written to the audit log.

Add these to `.env`, then run `docker compose up -d`:

```bash
LLX_PUBLIC_URL=https://testing.yourcompany.com     # where people open LorvenLax; email links point here
LLX_SMTP_HOST=smtp.sendgrid.net
LLX_SMTP_PORT=587
LLX_SMTP_SECURITY=starttls                          # starttls (port 587), ssl (port 465) or none
LLX_SMTP_USERNAME=apikey
LLX_SMTP_PASSWORD=...
LLX_MAIL_FROM=LorvenLax <no-reply@yourcompany.com>
```

Check the settings with `docker compose exec api python -m app.manage send-test-email you@yourcompany.com`.
For Gmail, use `smtp.gmail.com` with an [App Password](https://support.google.com/accounts/answer/185833), not
your normal password. For production, use a provider such as Amazon SES, SendGrid, Postmark or Mailgun, and set up
SPF and DKIM for the sending domain so messages are not marked as spam.

**Trying it out without a mail provider:** set `LLX_SMTP_HOST=mailpit`, `LLX_SMTP_PORT=1025` and
`LLX_SMTP_SECURITY=none`, run `docker compose --profile mail up -d`, and open http://localhost:8025 to see
every email the platform sends.

**Without email:** an owner or admin opens **Settings → Team**, clicks the key icon next to a member, and shares
the one-time link it creates (valid for 24 hours, `LLX_ADMIN_RESET_LINK_HOURS`). Admins can reset members and
viewers; owners can reset anyone. A person who also belongs to another workspace must use **Forgot password?**,
so that an admin of one workspace cannot take over an account used elsewhere. Signed-in users change their own
password under **Settings → Account**.

**Last resort** (for example, the only owner is locked out and email is not set up), run on the server:

```bash
docker compose exec api python -m app.manage reset-password you@example.com             # type the new password twice
docker compose exec api python -m app.manage reset-password you@example.com --generate  # print a random one
```

## Configuration

All settings are environment variables with the `LLX_` prefix (`backend/app/config.py`).

| Variable | Default | Purpose |
|---|---|---|
| `LLX_DATABASE_URL` | local postgres | SQLAlchemy URL |
| `LLX_REDIS_URL` | `redis://localhost:6379/0` | Celery broker, results and rate limits |
| `LLX_SECRET_KEY` | dev value | Server secret (required in production) |
| `LLX_ENCRYPTION_KEY` | derived in dev | Fernet key for secrets at rest (**required** when `LLX_ENV=production`) |
| `LLX_ANTHROPIC_API_KEY` | empty | Enables Claude; otherwise deterministic agents are used |
| `LLX_AI_MODEL` / `LLX_AI_EFFORT` | `claude-opus-5-5` / `medium` | Model and effort for AI agents |
| `LLX_ALLOWED_PRIVATE_HOSTS` | empty | Comma-separated hosts on private networks that tests may reach |
| `LLX_STORAGE_BACKEND` | `local` | `local` or `s3` (with `LLX_S3_*`) |
| `LLX_MAX_RUN_SECONDS` | 900 | Hard limit per execution |
| `LLX_COOKIE_SECURE` | false | Set true behind HTTPS |
| `LLX_DEFAULT_MONTHLY_TEST_RUNS` | 5000 | Quota for new organizations |

## CI/CD

Create a project API token in **Settings → API & CI/CD**, then use `docs/ci/lorvenlax_run.py`, a standard-library Python script that starts a run, waits for it, prints failures, writes Allure results, and exits non-zero on failures. Pipeline adapters: `docs/ci/github-actions.yml`, `gitlab-ci.yml`, `Jenkinsfile`, `azure-pipelines.yml`.

## Production deployment recommendations

- **TLS and cookies:** terminate HTTPS at a load balancer, set `LLX_COOKIE_SECURE=true`, and set `LLX_CORS_ORIGINS` to your domain.
- **Managed services:** use managed PostgreSQL (with backups and point-in-time recovery), managed Redis, and S3 with server-side encryption and a lifecycle rule for old artifacts.
- **Secrets:** inject `LLX_ENCRYPTION_KEY` and `LLX_SECRET_KEY` from a secrets manager (AWS Secrets Manager, Vault). Rotating the encryption key means re-encrypting `environment_variables`, so plan a migration.
- **Worker isolation:** run workers on separate nodes, for example an ECS or Kubernetes node pool with one test run per pod, a read-only root filesystem except for `/tmp`, and an egress-only network policy that denies RFC1918 and metadata ranges. The in-engine guard is defence in depth, not a replacement for network policy.
- **Scaling:** scale `worker` replicas on queue depth. The API is stateless and scales horizontally. Use Celery queues per region or tenant tier when needed.
- **Observability:** the API emits JSON logs with request ids. Add OpenTelemetry instrumentation for FastAPI, Celery and SQLAlchemy, and export to Prometheus and Grafana (not yet included).
- **Email:** invitations currently return a share link; connect an email provider before inviting external users.
