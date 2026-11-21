# The Wall: anonymous student Q&A

A complete FastAPI MVP with Jinja2 pages, HTMX enhancements, plain CSS, anonymous questions/answers, toggle upvotes, accepted answers and report-driven moderation. English and Arabic posts use `dir="auto"`. The interface is English; this is bilingual content support, not a translated interface.

## Local install, run and test

Use Python 3.12 (also tested on 3.11). Run these from the project root on Linux/macOS:

    python3.12 -m venv .venv
    . .venv/bin/activate
    python -m pip install -r requirements.txt
    python scripts/init_env.py
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000 . Stop with Ctrl+C. In the same activated environment:

    python -m pytest -q

Windows PowerShell equivalents for the first two commands:

    py -3.12 -m venv .venv
    .venv\Scripts\Activate.ps1

Then use the same `python` and `uvicorn` commands above. `init_env.py` creates a private local `.env`, generates both secrets, and refuses to overwrite an existing file. Do not copy blank secrets from `.env.example` and start a shared server. For local `/admin`, open your own `.env` privately and use its ADMIN_TOKEN. Never commit it or paste it into a URL. SQLite's local `wall.db` is created automatically; tests use separate temporary databases.

## Architecture

- `config.py`: validated environment settings and PostgreSQL URL/TLS normalization.
- `database.py`: synchronous SQLAlchemy engine, sessions and startup initialization.
- `models.py`: five tables, indexes, unique votes/reports, accepted-answer constraint and shared rate counters.
- `schemas.py`, `filters.py`: Pydantic validation, profanity checks and relative time.
- `security.py`: pseudonymous HMAC identity, CSRF, cookies and admin auth.
- `ratelimit.py`: transactional PostgreSQL/SQLite rate counters shared across instances.
- `routers/`: question, answer, vote/report and admin HTTP workflows.
- `web.py`, `templates/`, `static/`: escaped HTML, reusable HTMX partials and responsive UI.
- `tests/`: behavioral, security, concurrency and schema tests.

## Configuration

Environment variables override `.env`. Settings are read once at process start; restart after editing.

| Variable | Local default / meaning |
| --- | --- |
| DATABASE_URL | `sqlite:///./wall.db`; production must use Neon PostgreSQL |
| SECRET_KEY | Random 32+ characters in production; generated locally by setup |
| ADMIN_TOKEN | Random 32+ characters in production; empty disables admin login locally |
| ENVIRONMENT | `development`; set `production` for shared deployment |
| TRUST_PROXY | `false`; set `true` only behind a trusted, non-bypassable proxy |
| VERCEL | Set automatically by Vercel; never set it yourself elsewhere |
| DB_INIT_ON_STARTUP | `true`; automatically skipped on Vercel, where `scripts/init_db.py` runs once instead |
| SECURE_COOKIES | `false` locally; forced `true` in production/Render |
| REPORT_THRESHOLD | `3`, integer 1–100 |
| CATEGORIES | JSON array, default `["General","Study","Campus","Technology"]` |
| OPTIONAL_GOOGLE_FONT | `false`; `true` loads Cairo with `display=swap` |

Render sets `RENDER=true` itself; Vercel sets `VERCEL=1` itself. Either one also enforces PostgreSQL, strong configured secrets and secure cookies. `postgres://` and `postgresql://` become `postgresql+psycopg://`. Existing query parameters are retained, and `sslmode=require` overrides weaker SSL modes. Do not URL-escape an entire connection string; copy Neon's provided string exactly.

The engine uses `pool_pre_ping=True`, `pool_recycle=300`, `pool_size=3`, `max_overflow=2`. Startup retries database errors once after one second. `create_all` initializes tables: there is no Alembic or automatic migration of existing schemas. Back up and plan a reviewed schema migration before changing deployed models.

## Security and product semantics

- No accounts, names, analytics, raw IP or raw user-agent database columns. Raw connection information exists transiently to compute exactly HMAC-SHA256(SECRET_KEY, IP + user_agent). Votes and reports store only that digest. It is a pseudonymous identifier, not irreversible anonymity from the server operator. IP+agent is a heuristic: shared networks/browsers can collide, and changing IP or agent can evade limits. One real human cannot be proven without identity.
- The application disables Uvicorn access logs and hides SQL bind parameters. Hosting providers/CDNs can still see connection metadata; this app cannot control their logs. Users can type personal data into free text, so the UI asks them not to. There are no uploads.
- Proxy headers are ignored when TRUST_PROXY=false. On Vercel, the edge overwrites `X-Forwarded-For` and sets the identical `X-Vercel-Forwarded-For`/`X-Real-IP`, so client-spoofed forwarding headers are discarded and the Vercel header is used. On public Render, use Cloudflare's overwritten `CF-Connecting-IP`, not the spoofable leftmost X-Forwarded-For. Without the trusted header, fall back to the peer address. For a non-Render/non-Vercel single trusted proxy, use the last X-Forwarded-For entry. That proxy must sanitize/append the actual client address and direct origin access must be blocked. Additional proxy chains need an explicitly reviewed trust configuration before launch.
- Creation returns a fresh random question-specific edit token in an HttpOnly, SameSite=Lax cookie. Only SHA-256(token) is stored. Cookies expire after one year; clearing cookies, switching browsers or browser eviction loses acceptance rights. There is deliberately no recovery email or ownership lookup. Multiple questions have separate cookies.
- Only the owner can accept a visible answer on a visible question. Acceptance toggles; selecting another answer clears the previous acceptance. A partial unique index and per-question transaction locks enforce at most one accepted answer, including concurrent requests. Hidden accepted answers lose their accepted state.
- All defined POST actions require a valid signed double-submit CSRF token, including admin login/logout and header-authenticated moderation. Tokens expire after 24 hours; reload to obtain a fresh token. All mutations use POST. Admin cookies expire after one hour and are invalidated when ADMIN_TOKEN changes. The optional `X-Admin-Token` header still requires CSRF.
- Unique database constraints enforce one vote/report per pseudonymous identity and target. A repeated vote removes it; a repeated report does nothing. Question/answer target rows are locked during counter changes. SQLite uses BEGIN IMMEDIATE; PostgreSQL uses row locks.
- Questions: 10–1,000 trimmed characters; answers: 2–2,000. Profanity is an editable whole-word English/Arabic starter list in `app/profanity.txt`. Case, Arabic marks, tatweel and formatting characters are normalized for detection, but displayed content is preserved. This is a basic filter, not complete abuse detection. Null characters and file values are rejected.
- At the report threshold, the item disappears publicly. Hidden questions make all their answers inaccessible. Admin unhide clears that item's reports and counter, allowing a fresh review cycle. Deletion is permanent; deleting a question cascades answers and explicitly removes their polymorphic votes/reports. The moderation queue shows the newest 100 items of each type; resolve them to reveal older entries.
- Limits: 5 questions/hour, 20 answers/hour, 60 vote actions/hour; also 30 reports/hour, 60 acceptance changes/hour and 5 admin sign-in attempts/minute. Failed endpoint validation can consume a limit. Counters are fixed-window rows in the `rate_limits` table, incremented by an atomic upsert in their own committed transaction, so the limits hold across any number of concurrent Vercel instances, workers and restarts. Only the HMAC identity hash is stored, never a raw IP. Expired windows of the same action are deleted with each of its increments. Fixed windows reset at the hour/minute boundary rather than sliding. This remains unsuitable for determined distributed abuse without further defenses.
- Content is escaped. CSP forbids inline scripts/eval and allows pinned HTMX from jsDelivr, optional Google Fonts CSS and font assets. HTMX eval and injected indicator styles are disabled. Without JavaScript or if the CDN is unavailable, normal forms and redirects still work. External CDNs receive normal browser connection metadata. Google Fonts is off by default and system fonts are first.
- `/health` returns only `{"status":"ok"}` and never opens a database session. It is a liveness probe, not a database readiness check. Warm health pings don't wake idle Neon compute. On Vercel, cold-startup never touches the database either, so a cold `/health` probe stays database-free; initialize the schema once with `scripts/init_db.py` as the Vercel section describes. On Render and locally, application startup initializes/checks the database once.
- Newest/most-voted/unanswered filters exclude hidden questions. Unanswered means no visible answers. Pages contain 20 questions. Accepted answers sort first, then votes and oldest first. Relative times are rendered at request time, not updated by a timer.

## Free-only deployment: qualifications first

Checked November 21, 2026. All runtime libraries are open-source; no paid APIs, Redis, email provider, paid assets, Node tooling or Dockerfile is needed. HTMX uses a pinned free jsDelivr URL. Google Fonts Cairo is optional and free.

Neon's regular Free plan currently has no card requirement or time limit. Sign up for a normal account/project, NOT an unclaimed/temporary database. It currently includes 100 CU-hours and 5 GB network transfer per project/month; compute can suspend when quotas are exhausted and resume next billing period. Idle compute scales to zero. Provider terms and quotas can change; nobody can promise free hosting forever.

Render has a non-trial Free web-service tier, but its own staff confirms some accounts must add a card for verification. Therefore the combination cannot be guaranteed to satisfy a universal no-card rule. **If Render requests a payment card, paid plan or authorization hold, stop. Do not add one.** Local use remains free; do not substitute an expiring trial. This guide is conditional on your account offering a genuinely no-card Free service. Render itself says Free instances are not for production applications. Treat the hosted app as a low-traffic MVP/demo, not a production availability guarantee.

Render Free has 750 instance hours shared per workspace/month, sleeps after 15 idle minutes, may restart, and has bandwidth/build limits. With no payment method, exceeding applicable usage limits suspends services/builds rather than authorizing a charge. Don't add a card or enable paid extras. Never store production data in SQLite, a local file or Render's expiring Free Postgres. All persistent application state belongs in Neon, including the shared rate-limit counters.

### 1. Create a regular Neon Free project

1. Open https://neon.com and sign up for a normal free account. Verify the account if requested. No paid upgrade or card.
2. In the Neon console, choose **New project**. Name it `anonymous-wall`, keep the offered supported PostgreSQL version, and select a free region near your Render region. Create it on **Free**.
3. Open the project dashboard and click **Connect**. Select the main/production branch, the default database and its role. Enable **Connection pooling** when offered.
4. Choose the connection-string view and copy the complete PostgreSQL URL. It includes a database password: put it only in Render's secret DATABASE_URL field, never source code, chat, commits or screenshots. Keep any `sslmode` and `channel_binding` parameters Neon supplies.
5. Keep the database on the Free plan. Check the Usage page periodically. No additional Neon AI, storage or other service is used by this application.

### 2. Deploy a Render Free Python Web Service

1. Put this clean project in a repository you control. Private is fine; choose the visibility yourself. Do not commit `.env`, databases or credentials. Authorize Render to access only this repository if connecting GitHub.
2. Open https://dashboard.render.com and create/sign into a free account. Stop if a card is required.
3. Select **New > Web Service**, connect that repository, and choose its branch. Set runtime/language to **Python**, not Docker. Root Directory is the directory containing `requirements.txt` (leave empty if repository root).
4. Select a region close to Neon and instance type **Free ($0)**. Do not select Starter, a paid workspace, disk, database or paid cron service.
5. Build command, exactly:

    pip install -r requirements.txt

6. Start command, exactly:

    uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1

7. Set **Health Check Path** to `/health`. The included `.python-version` selects Python 3.11.18. If the provider no longer offers that patch release, select a supported Python 3.11+ patch and rerun tests before deployment.
8. In Environment, add DATABASE_URL (Neon's full secret URL), SECRET_KEY, ADMIN_TOKEN, TRUST_PROXY=`true`, REPORT_THRESHOLD=`3`, ENVIRONMENT=`production`. Generate separate random secrets of at least 32 characters with a password manager; do not reuse any previous project's secrets. Locally generated `.env` values are also random, but prefer distinct deployment secrets. Never paste them in the repository.
9. Leave OPTIONAL_GOOGLE_FONT=`false` unless you want the optional external font. SECURE_COOKIES is forced on by the app in production. Render supplies PORT and RENDER; don't override them.
10. Recheck the total is $0 with no card or paid add-on, then choose **Deploy Web Service**. Startup creates empty tables in Neon. If startup fails, check variable names and the connection string privately; never share logs containing credentials.
11. Open Render's assigned HTTPS URL. `/health` should return the small JSON object. Create a non-sensitive test question, answer and vote. Check owner-only acceptance in the original browser, rejected acceptance in another browser, and `/admin` login. Do not enable public traffic until proxy identity behavior and all these smoke tests are verified on your deployment.

### 3. Optional cron-job.org HTTP health job, every ten minutes

This section documents the requested job, not a promise of always-on service or proof that evading idle policies is allowed. Render documents idle spin-down; the reviewed official sources do not explicitly authorize synthetic keep-alive traffic. Prefer natural sleep for a free demo. Enable repeated pings only if your provider's current terms permit your use, and disable them if challenged. Do not use rotating accounts or other quota workarounds.

1. Open https://cron-job.org/en/ and choose free sign-up. Verify your email. Ordinary cron jobs are free; no sustaining membership, trial or card is needed.
2. In the dashboard select **Create cronjob**. Give it the title `Wall HTTP health`.
3. For URL, paste the actual HTTPS base URL shown by Render and append `/health`. Do not paste the homepage or any database/admin URL. Do not attach cookies, secrets, tokens, custom authorization or request bodies.
4. Set request method **GET**. Under execution schedule, select **Every 10 minutes**. If using the custom selector, select minutes `0,10,20,30,40,50` and every hour/day/month/weekday. The equivalent five-field expression is `*/10 * * * *`.
5. Enable the job and save/create. Use **Test run** if offered; verify HTTP 200 and `{"status":"ok"}` in the result, then check execution history after the next run.
6. An already sleeping Render process can take about a minute to start, while cron-job.org's normal request timeout is 30 seconds. The first run can time out even if Render wakes afterward. Repeated failures can disable a job. Neither provider guarantees exact timing or uninterrupted service; review failures rather than assuming success.
7. These probes consume Render instance time and a small amount of transfer. They don't call Neon on warm requests. They don't prevent provider restarts, quota suspensions, account verification or billing-policy changes. Delete/disable the job when no longer needed.

### 4. Alternative: deploy on Vercel Hobby (free)

Checked November 21, 2026. Vercel supports FastAPI directly, including this `app/main.py` entrypoint, static files and lifespan startup. The Hobby plan is free and pauses features at usage limits rather than charging overages; keep no card on the account and no paid add-ons. If Vercel requests a payment card, paid plan or authorization hold, stop. Do not add one.

Vercel automatically scales the application into separate function instances. That is why rate counters live in PostgreSQL (see Security and product semantics): in-memory counters would not be shared. No keep-alive cron is needed on Vercel; cold starts never touch the database.

Provider privacy note: the application stores no raw IP, but Vercel's own runtime logs can include request IP and user-agent, retained for 1 hour on Hobby. Anonymity is toward site users, not toward the hosting company.

1. Create the Neon Free project from section 1 first; the Vercel deployment uses the same database.
2. Put this clean project in a repository you control (private is fine). Do not commit `.env`, databases or credentials.
3. Open https://vercel.com, sign into the free Hobby account, and **Add New > Project** from that repository. Keep the Free/Hobby plan; select no paid extras, and do not add a card if asked.
4. In the project Environment Variables, add DATABASE_URL (Neon's full secret URL), SECRET_KEY, ADMIN_TOKEN, TRUST_PROXY=`true`, ENVIRONMENT=`production`. Generate fresh random 32+ character secrets; never paste them into the repository, chat or screenshots. Vercel sets VERCEL itself; the app then skips startup database access automatically.
5. Deploy, rechecking the cost is $0. The first deploy's cold start does not create tables.
6. Initialize the schema once, from your own machine, with the production values in the environment (never in a file or command history you share):

    python scripts/init_db.py

   Rerun it after any future schema change. It creates missing tables only.
7. Open the assigned HTTPS URL. `/health` returns the small JSON object even on a cold start. Create a non-sensitive test question, answer and vote; check owner-only acceptance, rejected acceptance in another browser, `/admin` login, and that the sixth question within an hour returns 429. Do not enable public traffic until these smoke tests pass on your deployment.

## Verification and limitations

The Vercel-compatible revision was installed and run with Python 3.12 (3.11 also supported). The full test suite passes on temporary SQLite databases and again on an isolated PostgreSQL database. Tests include validation/profanity, cookies and CSRF, uniqueness, toggle votes, reports, owner acceptance, concurrent mutations, exact concurrent rate-limit enforcement, cross-instance shared counters, admin authentication/unhide/delete cascade, pagination, Vercel/Render/proxy trusted-header behavior, URL normalization, PostgreSQL DDL, startup retry and database-free Vercel cold starts. Tests default to SQLite and never use DATABASE_URL from your `.env`.

For an optional PostgreSQL test run, set WALL_TEST_DATABASE_URL to a dedicated SQLAlchemy psycopg URL whose database name starts with `test_wall_`, then run the same pytest command. **Tests delete and recreate all application tables there. Never point this at a real wall database.** No extra PostgreSQL server package is needed by the deployed app.

Real Chromium checks covered desktop, 390px mobile, dark mode, Arabic posts, actual HTMX posting/voting/reporting, visible server-validation errors without losing form text, admin login and no-JavaScript forms. No horizontal overflow was observed. A deliberately rejected profanity submission correctly returns HTTP 422, which appears in the browser network console. There are no expected script/CSP errors.

A dependency audit found no known vulnerabilities at the time of delivery; this is not a future guarantee. Current Starlette emits a deprecation warning for its httpx-based TestClient. It is non-failing; httpx remains intentionally included to match the requested stack. Review dependencies and rerun tests before upgrades.

No actual Vercel/Render/Neon account, live deployment, backup restore or production load test was performed for this code delivery. An MVP test pass does not prove flawless operation or production readiness. Before real student use, review privacy/retention, moderation coverage, database backups and restore, abuse response, provider logs and operational ownership. Protect or remove sensitive submissions. There is intentionally no paid infrastructure workaround.

## Official service references

- Neon Free plan and limits: https://neon.com/pricing
- Neon console/project connection: https://neon.com/docs/get-started/signing-up
- Neon application connection strings: https://neon.com/docs/connect/connect-from-any-app
- Render Free limits and production warning: https://render.com/docs/free
- Render FastAPI deployment: https://render.com/docs/deploy-fastapi
- Render staff on possible card verification: https://community.render.com/t/the-deployement-of-a-web-service-fails/36005
- Render's current client-IP guidance: https://render.com/articles/host-pocketbase-on-render.md
- Render terms: https://render.com/terms
- cron-job.org free-service terms: https://cron-job.org/en/tos/
- cron-job.org schedules, timeout and failures: https://cron-job.org/en/faq/
- Vercel FastAPI deployment: https://vercel.com/docs/frameworks/backend/fastapi
- Vercel Hobby plan and limits: https://vercel.com/docs/plans/hobby
- Vercel request headers (edge-overwritten client IP): https://vercel.com/docs/headers/request-headers
- Vercel runtime logs retention: https://vercel.com/docs/observability/runtime-logs
