import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

# Never touch a developer's .env database or admin credentials.
_bootstrap = tempfile.TemporaryDirectory()
os.environ.update(DATABASE_URL=f"sqlite:///{_bootstrap.name}/bootstrap.db",
    SECRET_KEY="test-secret-key-not-for-production-0123456789",
    ADMIN_TOKEN="test-admin-token-not-for-production-0123456789",
    ENVIRONMENT="development", RENDER="false", TRUST_PROXY="false",
    SECURE_COOKIES="false", REPORT_THRESHOLD="3")

from app.database import Base, get_db, make_engine
from app.main import app


@pytest.fixture
def client(tmp_path):
    url = os.environ.get("WALL_TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    if not url.startswith("sqlite"):
        from sqlalchemy.engine import make_url
        if not (make_url(url).database or "").startswith("test_wall_"):
            raise ValueError("Use a dedicated test_wall_ database; tests erase its tables")
    engine = make_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        test_client.db_factory = factory
        test_client.get("/")
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.cookies.get("csrf"), **data}, follow_redirects=False)


def question(client, text="How can I study more effectively?", category="Study"):
    response = post(client, "/questions", text=text, category=category)
    assert response.status_code == 303, response.text
    return int(response.headers["location"].split("/")[-1])


def answer(client, qid, text="Try short focused study sessions."):
    response = post(client, f"/questions/{qid}/answers", text=text)
    assert response.status_code == 303, response.text
    with client.db_factory() as db:
        from app.models import Answer
        from sqlalchemy import select
        return db.scalar(select(Answer.id).order_by(Answer.id.desc()))
