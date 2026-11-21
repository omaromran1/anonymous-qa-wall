# Deviations from the frozen delivery (Vercel compatibility revision)

November 21, 2026. This revision adapts the frozen, fully tested source for
Vercel deployment. The user approved the one material design change after the
compatibility question and privacy disclosure were put to them. Everything
else in the original specification is preserved.

## 1. Rate limiting: in-memory SlowAPI -> transactional PostgreSQL counters
(approved change)

- Why: Vercel automatically scales one deployment into separate function
  instances. SlowAPI's memory:// counters are per-process, so the required
  5 questions/hour, 20 answers/hour, 60 vote actions/hour, 30 reports/hour,
  60 acceptance changes/hour and 5 admin sign-ins/minute limits would have
  been silently weakened on Vercel.
- How: new `rate_limits` table (action, identity_hash, window_start, count;
  unique key on the first three). Each check is an atomic INSERT ... ON
  CONFLICT DO UPDATE ... RETURNING in its own committed transaction, so all
  instances share one authoritative count. Fixed clock windows, same limits,
  same key (HMAC-SHA256 of SECRET_KEY + IP + user-agent; no raw IP stored).
- Ordering and failure semantics preserved: CSRF is still validated first;
  a rejected form still consumes a slot ("failed endpoint validation can
  consume a limit"). HTTP 429 responses now carry a Retry-After matching the
  window (3600s hourly, 60s for admin sign-in; previously always 3600).
- Schema grows from four tables to five. `slowapi` and `limits` dependencies
  removed. Expired windows are deleted during each increment, scoped to the same action so short (1-minute) windows can never erase active hourly counters.

## 2. Database-free cold starts on Vercel (required for serverless)

- Original: lifespan startup always ran `initialize_database()`, so a cold
  `/health` request would wake/query Neon before responding.
- Now: when the VERCEL environment variable is set (Vercel sets it
  automatically), startup performs no database I/O at all; `/health` stays
  truly database-free across cold starts. Schema initialization is a
  controlled one-time step: `python scripts/init_db.py` with production
  environment variables set. Local and Render behavior is unchanged
  (DB_INIT_ON_STARTUP=true default; startup retry logic intact).

## 3. Trusted client-IP header on Vercel

- Vercel's edge overwrites X-Forwarded-For and sets the identical
  X-Vercel-Forwarded-For/X-Real-IP, so client-spoofed forwarding headers
  cannot reach the app (vercel.com/docs/headers/request-headers). With
  TRUST_PROXY=true on Vercel the pseudonymous identity uses
  X-Vercel-Forwarded-For (falling back to X-Real-IP). Render
  (CF-Connecting-IP) and generic-proxy behavior unchanged.

## 4. Runtime qualification

- Vercel's current default is Python 3.12 (3.13/3.14 also supported).
  `.python-version` updated to 3.12. Full suite (54 tests) passes on
  Python 3.12 with SQLite and a real PostgreSQL 16.2 database, and on
  Python 3.11 with SQLite. New tests cover exact concurrent rate-limit
  enforcement, cross-instance shared counters, Vercel trusted-header spoof
  resistance, and database-free Vercel cold starts.

## What did not change

Stack (FastAPI/Jinja2/HTMX/psycopg), all limits and thresholds, HMAC
pseudonymous identity with no raw-IP persistence, CSRF model, ownership
cookies, admin auth, moderation flows, templates, static assets, profanity
filter, Neon as the only production database, zero-cost/no-card constraint.
The original frozen ZIP is preserved separately.

## Known limits carried forward

IP+agent identity is still a heuristic; fixed windows reset at the boundary;
hosting-provider logs (Vercel keeps runtime logs with request IP/user-agent
for 1 hour on Hobby) are outside the application's control; an MVP test pass
does not prove production readiness. No live Vercel deployment was performed
in this code task.

## Deployed configuration

The deployed revision adds vercel.json with the FastAPI preset, fra1 region and a 60-second function duration, plus .vercelignore excluding secrets, local databases, test files and caches. The public app uses Neon Free PostgreSQL. Production schema was initialized separately, and live behavior smoke tests passed. No keep-alive job is configured.
