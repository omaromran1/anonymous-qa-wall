from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_mock_engine, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import Settings, settings
from app.database import Base
from app.main import app
from app.models import Answer, Question, RateLimit, Report, Vote
from app.security import token_hash
from tests.conftest import answer, post, question


def test_create_question_and_ownership_storage(client):
    qid = question(client)
    raw = client.cookies.get(f"owner_{qid}")
    with client.db_factory() as db:
        q = db.get(Question, qid)
        assert q.edit_token_hash == token_hash(raw)
        assert q.edit_token_hash != raw
        assert q.vote_count == q.report_count == 0
    response = client.get(f"/questions/{qid}")
    assert "You're the asker" in response.text


@pytest.mark.parametrize("text", ["short", "x" * 1001, " " * 12])
def test_question_limits(client, text):
    assert post(client, "/questions", text=text, category="Study").status_code == 422


def test_question_min_max(client):
    question(client, "x" * 10)
    question(client, "x" * 1000)


def test_category_validation(client):
    assert post(client, "/questions", text="A valid long question", category="Fake").status_code == 422


@pytest.mark.parametrize("word", ["fuck", "FUCK", "كسم", "كـسم", "كُسم"])
def test_profanity(client, word):
    assert post(client, "/questions", text=f"My question {word} here?", category="Study").status_code == 422


def test_answers_validation(client):
    qid = question(client)
    for text in ["x", "x" * 2001, "shit"]:
        assert post(client, f"/questions/{qid}/answers", text=text).status_code == 422
    answer(client, qid, "ok")
    answer(client, qid, "x" * 2000)


def test_vote_toggle_and_identity(client):
    qid = question(client)
    post(client, f"/vote/question/{qid}")
    with client.db_factory() as db:
        assert db.get(Question, qid).vote_count == 1
        assert db.scalar(select(func.count()).select_from(Vote)) == 1
    post(client, f"/vote/question/{qid}")
    with client.db_factory() as db:
        assert db.get(Question, qid).vote_count == 0
        assert db.scalar(select(func.count()).select_from(Vote)) == 0
    client.headers["user-agent"] = "another browser"
    post(client, f"/vote/question/{qid}")
    client.headers["user-agent"] = "third browser"
    post(client, f"/vote/question/{qid}")
    with client.db_factory() as db:
        assert db.get(Question, qid).vote_count == 2


def test_database_unique_constraints(client):
    for model in [Vote, Report]:
        with client.db_factory() as db:
            db.add_all([model(target_type="question", target_id=1, voter_hash="a" * 64),
                        model(target_type="question", target_id=1, voter_hash="a" * 64)])
            with pytest.raises(IntegrityError):
                db.commit()


def test_reports_unique_and_autohide(client):
    qid = question(client)
    for _ in range(2):
        assert post(client, f"/report/question/{qid}").status_code == 303
    with client.db_factory() as db:
        assert db.get(Question, qid).report_count == 1
    for agent in ["second", "third"]:
        client.headers["user-agent"] = agent
        post(client, f"/report/question/{qid}")
    assert client.get(f"/questions/{qid}").status_code == 404
    assert post(client, f"/questions/{qid}/answers", text="A hidden answer").status_code == 404
    assert post(client, f"/vote/question/{qid}").status_code == 404
    assert "How can I study" not in client.get("/").text


def test_accept_ownership_and_toggle(client):
    qid = question(client)
    a1 = answer(client, qid)
    a2 = answer(client, qid, "A different helpful answer.")
    raw = client.cookies.get(f"owner_{qid}")
    client.cookies.set(f"owner_{qid}", "wrong", domain="testserver.local", path="/")
    assert post(client, f"/answers/{a1}/accept").status_code == 403
    client.cookies.set(f"owner_{qid}", raw, domain="testserver.local", path="/")
    assert post(client, f"/answers/{a1}/accept").status_code == 303
    assert post(client, f"/answers/{a2}/accept").status_code == 303
    with client.db_factory() as db:
        assert not db.get(Answer, a1).is_accepted
        assert db.get(Answer, a2).is_accepted
    page = client.get(f"/questions/{qid}").text
    assert page.index(f'id="answer-{a2}"') < page.index(f'id="answer-{a1}"')
    post(client, f"/answers/{a2}/accept")
    with client.db_factory() as db:
        assert not db.get(Answer, a2).is_accepted


def test_hidden_accepted_answer(client):
    qid = question(client)
    aid = answer(client, qid)
    post(client, f"/answers/{aid}/accept")
    for agent in ["a", "b", "c"]:
        client.headers["user-agent"] = agent
        post(client, f"/report/answer/{aid}")
    with client.db_factory() as db:
        assert db.get(Answer, aid).is_hidden
        assert not db.get(Answer, aid).is_accepted


def test_question_rate_limit(client):
    for _ in range(5):
        question(client)
    response = post(client, "/questions", text="A sixth valid question", category="Study")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"


def test_rate_counters_are_database_backed_and_shared(client):
    question(client)
    with client.db_factory() as db:
        row = db.scalar(select(RateLimit).where(RateLimit.action == "questions"))
        assert row is not None and row.count == 1
        # Pseudonymous HMAC identity, never a raw IP.
        assert len(row.identity_hash) == 64
    for _ in range(4):
        question(client)
    csrf = client.cookies.get("csrf")
    # A second app client against the same database is a stand-in for a
    # separate Vercel instance: it must see the same authoritative count.
    with TestClient(app) as other:
        other.cookies.set("csrf", csrf)
        response = other.post("/questions", data={"csrf_token": csrf,
            "text": "A sixth valid question", "category": "Study"}, follow_redirects=False)
        assert response.status_code == 429


def test_short_window_cleanup_preserves_active_hourly_counters(client):
    # Regression: window starts are period-aligned, so an unscoped cleanup
    # from the 1-minute admin window would erase the current hour's counters.
    question(client)
    for _ in range(3):
        assert post(client, "/admin", token="wrong").status_code == 403
    with client.db_factory() as db:
        row = db.scalar(select(RateLimit).where(RateLimit.action == "questions"))
        assert row is not None and row.count == 1
    # The surviving counter still counts toward the hourly limit.
    for _ in range(4):
        question(client)
    assert post(client, "/questions", text="A sixth valid question", category="Study").status_code == 429


def test_expired_windows_of_same_action_are_cleaned(client):
    import time
    stale_start = (int(time.time()) - 7200) // 3600 * 3600
    with client.db_factory() as db:
        db.add(RateLimit(action="questions", identity_hash="s" * 64,
                         window_start=stale_start, count=3))
        db.commit()
    question(client)
    with client.db_factory() as db:
        assert db.scalar(select(func.count()).select_from(RateLimit).where(
            RateLimit.action == "questions",
            RateLimit.window_start == stale_start)) == 0


def test_concurrent_question_rate_limit_is_exact(client):
    csrf = client.cookies.get("csrf")
    def send(n):
        return client.post("/questions", data={"csrf_token": csrf,
            "text": f"A valid concurrent question {n}", "category": "Study"},
            follow_redirects=False).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(send, range(8)))
    assert results.count(303) == 5
    assert results.count(429) == 3


def test_answer_and_vote_rate_limits(client):
    qid = question(client)
    for _ in range(20):
        answer(client, qid)
    assert post(client, f"/questions/{qid}/answers", text="No more").status_code == 429
    for _ in range(60):
        assert post(client, f"/vote/question/{qid}").status_code == 303
    assert post(client, f"/vote/question/{qid}").status_code == 429


@pytest.mark.parametrize("route", ["/questions", "/questions/1/answers", "/vote/question/1", "/report/question/1", "/answers/1/accept", "/admin", "/admin/logout", "/admin/question/1/unhide", "/admin/question/1/delete"])
def test_all_post_routes_csrf(client, route):
    assert client.post(route, data={}).status_code == 403


def test_forged_csrf(client):
    client.cookies.set("csrf", "forged", domain="testserver.local", path="/")
    assert client.post("/questions", data={"csrf_token": "forged"}).status_code == 403


def test_admin_auth_unhide_delete_cascade(client):
    qid = question(client)
    aid = answer(client, qid)
    post(client, f"/vote/answer/{aid}")
    post(client, f"/report/question/{qid}")
    post(client, f"/report/answer/{aid}")
    assert "Admin token" in client.get("/admin").text
    assert post(client, f"/admin/question/{qid}/delete").status_code == 403
    assert post(client, "/admin", token="wrong").status_code == 403
    assert post(client, "/admin", token=settings.admin_token).status_code == 303
    assert "Moderation queue" in client.get("/admin").text
    assert post(client, f"/admin/question/{qid}/unhide").status_code == 303
    with client.db_factory() as db:
        assert db.get(Question, qid).report_count == 0
        assert db.scalar(select(func.count()).select_from(Report).where(Report.target_type == "question")) == 0
    assert post(client, f"/admin/question/{qid}/delete").status_code == 303
    with client.db_factory() as db:
        assert db.get(Question, qid) is None
        assert db.get(Answer, aid) is None
        assert db.scalar(select(func.count()).select_from(Report)) == 0
        assert db.scalar(select(func.count()).select_from(Vote)) == 0
    post(client, "/admin/logout")
    assert "Admin token" in client.get("/admin").text


def test_health_never_touches_database(client):
    with patch("sqlalchemy.orm.Session.execute", side_effect=AssertionError("Database touched")), patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Database touched")):
        response = client.get("/health")
        assert response.json() == {"status": "ok"}
    assert "set-cookie" not in response.headers


def test_security_headers_and_xss(client):
    qid = question(client, '<script>alert("xss")</script>')
    response = client.get(f"/questions/{qid}")
    assert '&lt;script&gt;' in response.text
    assert '<script>alert(' not in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    for origin in ["https://cdn.jsdelivr.net", "https://fonts.googleapis.com", "https://fonts.gstatic.com"]:
        assert origin in csp
    assert "unsafe-inline" not in csp


def test_htmx_partials(client):
    qid = question(client)
    client.headers["HX-Request"] = "true"
    response = post(client, f"/questions/{qid}/answers", text="A partial answer")
    assert response.status_code == 200
    assert 'id="answers-section"' in response.text
    assert "<!doctype" not in response.text
    response = post(client, f"/vote/question/{qid}")
    assert f'id="question-{qid}"' in response.text
    assert "<!doctype" not in response.text
    response = post(client, f"/questions/{qid}/answers", text="x")
    assert response.status_code == 422
    assert 'role="alert"' in response.text


def test_sort_filter_and_unanswered(client):
    q1 = question(client, "First useful long question", "Study")
    q2 = question(client, "Second useful long question", "General")
    answer(client, q1)
    post(client, f"/vote/question/{q1}")
    newest = client.get("/").text
    assert newest.index(f'id="question-{q2}"') < newest.index(f'id="question-{q1}"')
    voted = client.get("/?sort=votes").text
    assert voted.index(f'id="question-{q1}"') < voted.index(f'id="question-{q2}"')
    unanswered = client.get("/?sort=unanswered").text
    assert f'id="question-{q1}"' not in unanswered
    assert f'id="question-{q2}"' in unanswered
    filtered = client.get("/?category=Study").text
    assert f'id="question-{q2}"' not in filtered
    assert client.get("/?sort=invalid").status_code == 400
    assert client.get("/?page=0").status_code == 422


def test_pagination(client):
    with client.db_factory() as db:
        db.add_all([Question(text=f"A valid question number {n}", category="Study", edit_token_hash="x" * 64) for n in range(21)])
        db.commit()
    assert client.get("/").text.count('class="card post"') == 20
    assert client.get("/?page=2").text.count('class="card post"') == 1


def test_proxy_trust(client, monkeypatch):
    from app.security import voter_hash
    from starlette.requests import Request
    def request(address):
        return Request({"type": "http", "client": ("127.0.0.1", 10),
            "headers": [(b"x-forwarded-for", address.encode()), (b"user-agent", b"same")]})
    assert voter_hash(request("1.2.3.4")) == voter_hash(request("1.2.3.5"))
    monkeypatch.setattr(settings, "trust_proxy", True)
    assert voter_hash(request("1.2.3.4")) != voter_hash(request("1.2.3.5"))


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://", "postgresql+psycopg://"])
def test_postgres_configuration(prefix):
    cfg = Settings(_env_file=None, database_url=prefix + "u:p@host/db?sslmode=disable&application_name=wall")
    assert cfg.database_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in cfg.database_url
    assert "application_name=wall" in cfg.database_url


def test_production_rejects_sqlite():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production", database_url="sqlite:///bad.db")


def test_postgresql_schema_compiles():
    statements = []
    engine = create_mock_engine("postgresql+psycopg://", lambda sql, *a, **kw: statements.append(str(sql.compile(dialect=engine.dialect))))
    Base.metadata.create_all(engine)
    assert any("ON DELETE CASCADE" in statement for statement in statements)
    assert sum("CREATE TABLE" in statement for statement in statements) == 5


def test_database_startup_retries_once():
    from app.database import initialize_database
    with patch("app.database.engine") as engine, patch("app.database.Base.metadata.create_all"), patch("app.database.time.sleep"):
        engine.connect.side_effect = [OperationalError("connect", {}, Exception()), engine.connect.return_value]
        initialize_database()
        assert engine.connect.call_count == 2
        engine.dispose.assert_called_once()


def test_ownership_cookie_security(client):
    response = post(client, "/questions", text="A question with secure cookie flags", category="Study")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_concurrent_votes_and_reports(client):
    qid = question(client)
    csrf = client.cookies.get("csrf")
    def send(action):
        return client.post(f"/{action}/question/{qid}", data={"csrf_token": csrf}, follow_redirects=False).status_code
    with ThreadPoolExecutor(max_workers=5) as pool:
        assert set(pool.map(send, ["vote"] * 10)) == {303}
        assert set(pool.map(send, ["report"] * 5)) == {303}
    with client.db_factory() as db:
        q = db.get(Question, qid)
        assert q.vote_count == 0
        assert q.report_count == 1


def test_concurrent_acceptance(client):
    qid = question(client)
    ids = [answer(client, qid, text=f"A helpful answer {n}") for n in range(2)]
    csrf = client.cookies.get("csrf")
    def send(aid):
        return client.post(f"/answers/{aid}/accept", data={"csrf_token": csrf}, follow_redirects=False).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(send, ids)) == {303}
    with client.db_factory() as db:
        assert db.scalar(select(func.count()).select_from(Answer).where(Answer.question_id == qid, Answer.is_accepted.is_(True))) == 1


def test_only_one_accepted_database_constraint(client):
    qid = question(client)
    with client.db_factory() as db:
        db.add_all([Answer(question_id=qid, text="Answer one", is_accepted=True),
                    Answer(question_id=qid, text="Answer two", is_accepted=True)])
        with pytest.raises(IntegrityError):
            db.commit()


def test_vercel_trusted_header_ignores_spoofed_xff(client, monkeypatch):
    from app.security import voter_hash
    from starlette.requests import Request
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "vercel", True)
    def request(spoof, trusted=b"203.0.113.7"):
        return Request({"type": "http", "client": ("127.0.0.1", 10), "headers": [
            (b"x-vercel-forwarded-for", trusted),
            (b"x-forwarded-for", spoof), (b"user-agent", b"same")]})
    # Client-supplied XFF is discarded; the Vercel edge header decides.
    assert voter_hash(request(b"1.2.3.4")) == voter_hash(request(b"9.8.7.6"))
    assert voter_hash(request(b"1.2.3.4", trusted=b"203.0.113.8")) != voter_hash(request(b"1.2.3.4"))


def test_vercel_cold_start_never_touches_database(client, monkeypatch):
    monkeypatch.setattr(settings, "vercel", True)
    with patch("app.main.initialize_database", side_effect=AssertionError("Database touched at startup")):
        with TestClient(app) as cold_client:
            assert cold_client.get("/health").json() == {"status": "ok"}


def test_render_ignores_spoofable_xff(client, monkeypatch):
    from app.security import voter_hash
    from starlette.requests import Request
    monkeypatch.setattr(settings, "trust_proxy", True)
    monkeypatch.setattr(settings, "render", True)
    def request(spoof):
        return Request({"type": "http", "client": ("127.0.0.1", 10), "headers": [
            (b"cf-connecting-ip", b"203.0.113.5"),
            (b"x-forwarded-for", spoof.encode()), (b"user-agent", b"same")]})
    assert voter_hash(request("1.2.3.4")) == voter_hash(request("9.8.7.6"))


def test_arabic_content_and_relative_time(client):
    from datetime import datetime, timedelta, timezone
    from app.filters import relative_time
    qid = question(client, "كيف يمكن تنظيم وقت الدراسة بشكل أفضل؟")
    page = client.get(f"/questions/{qid}").text
    assert "كيف يمكن" in page and 'dir="auto"' in page
    assert relative_time(datetime.now(timezone.utc) - timedelta(minutes=5)) == "5 minutes ago"


def test_null_and_file_content_rejected(client):
    assert post(client, "/questions", text="A question with \x00 null", category="Study").status_code == 422
    response = client.post("/questions", data={"category": "Study", "csrf_token": client.cookies.get("csrf")}, files={"text": ("a.txt", b"not a question")})
    assert response.status_code == 422


def test_non_ascii_invalid_secrets_return_errors(client):
    assert client.post("/questions", data={"csrf_token": "غير صالح"}).status_code == 403
    assert post(client, "/admin", token="رمز غير صالح").status_code == 403
