from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, create_engine, select

from app.db import get_engine, init_db, override_engine_for_tests
from app.domain.models import User
from app.infrastructure.rbac import Role, has_permission, has_role
from app.infrastructure.security import create_access_token
from app.main import app
from app.models import ConversationEvent, EssaySubmission, PublicVocabEntry, UserVocabQuery
from app.settings import Settings


def _register_and_login(client: TestClient, username: str) -> dict:
    """Register a user and return auth data (accessToken + user dict)."""
    client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "Admin1234"},
    )
    resp = client.post("/api/auth/login", json={"username": username, "password": "Admin1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    return body["data"]


# ---------------------------------------------------------------------------
# Test 1: Unauthenticated vocab lookup MUST ignore body user_id
# ---------------------------------------------------------------------------
def test_vocab_lookup_ignores_body_user_id_when_anonymous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    # Pre-populate a public vocab entry so the lookup succeeds without LLM.
    with Session(engine) as session:
        session.add(
            PublicVocabEntry(
                term="test",
                definition="释义：测试\n例句：This is a test.",
                lang="en",
            )
        )
        session.commit()

    async def _fake_build_recommendations(**kwargs):
        return []

    monkeypatch.setattr(
        "app.routers.vocab._build_recommendations",
        _fake_build_recommendations,
    )

    client = TestClient(app)
    resp = client.post(
        "/v1/vocab/lookup",
        json={"term": "test", "source": "manual", "user_id": 999},
    )
    assert resp.status_code == 200

    # The recorded UserVocabQuery MUST have user_id=None, NOT 999.
    with Session(engine) as session:
        queries = list(session.exec(select(UserVocabQuery)).all())
        assert len(queries) >= 1
        for q in queries:
            assert q.user_id is None, (
                f"Expected user_id=None (anonymous) but got {q.user_id}"
            )


# ---------------------------------------------------------------------------
# Test 2: Unauthenticated essay grade MUST ignore body user_id
# ---------------------------------------------------------------------------
def test_essay_grade_ignores_body_user_id_when_anonymous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def _fake_run_grading_pipeline(*, ocr_text: str, language: str):
        return {
            "dimensions": {},
            "total_score": 7.0,
            "grade": "B",
            "feedback": "ok",
            "suggestions": [],
            "corrected_text": ocr_text,
            "llm_raw": {
                "score": 70,
                "feedback": "ok",
                "errors": [],
                "suggestions": [],
                "rewritten": ocr_text,
                "scores": {},
            },
        }

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    resp = client.post(
        "/v1/essays/grade",
        json={
            "text": "I has a pen.",
            "language": "en",
            "user_id": 999,
        },
    )
    assert resp.status_code == 200

    submission_id = resp.json()["submission_id"]
    with Session(engine) as session:
        submission = session.get(EssaySubmission, submission_id)
        assert submission is not None
        assert submission.user_id is None, (
            f"Expected user_id=None (anonymous) but got {submission.user_id}"
        )


# ---------------------------------------------------------------------------
# Test 3: Authenticated operations store the token-derived user_id
# ---------------------------------------------------------------------------
def test_vocab_lookup_uses_token_user_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    with Session(engine) as session:
        session.add(
            PublicVocabEntry(
                term="agenda",
                definition="释义：议程\n例句：Let's review the agenda.",
                lang="en",
            )
        )
        session.commit()

    async def _fake_build_recommendations(**kwargs):
        return []

    monkeypatch.setattr(
        "app.routers.vocab._build_recommendations",
        _fake_build_recommendations,
    )

    client = TestClient(app)
    auth = _register_and_login(client, "student_boundary")
    token = auth["accessToken"]
    expected_user_id = auth["user"]["id"]

    # Send with user_id=777 in body — it MUST be ignored.
    resp = client.post(
        "/v1/vocab/lookup",
        json={"term": "agenda", "source": "manual", "user_id": 777},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    with Session(engine) as session:
        queries = list(session.exec(select(UserVocabQuery)).all())
        assert len(queries) >= 1
        for q in queries:
            assert q.user_id == expected_user_id, (
                f"Expected user_id={expected_user_id} (from token) but got {q.user_id}"
            )


def test_essay_grade_uses_token_user_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    async def _fake_run_grading_pipeline(*, ocr_text: str, language: str):
        return {
            "dimensions": {},
            "total_score": 7.0,
            "grade": "B",
            "feedback": "ok",
            "suggestions": [],
            "corrected_text": ocr_text,
            "llm_raw": {
                "score": 70,
                "feedback": "ok",
                "errors": [],
                "suggestions": [],
                "rewritten": ocr_text,
                "scores": {},
            },
        }

    monkeypatch.setattr("app.routers.essays.run_grading_pipeline", _fake_run_grading_pipeline)

    client = TestClient(app)
    auth = _register_and_login(client, "essay_boundary")
    token = auth["accessToken"]
    expected_user_id = auth["user"]["id"]

    resp = client.post(
        "/v1/essays/grade",
        json={
            "text": "I has a pen.",
            "language": "en",
            "user_id": 888,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    submission_id = resp.json()["submission_id"]
    with Session(engine) as session:
        submission = session.get(EssaySubmission, submission_id)
        assert submission is not None
        assert submission.user_id == expected_user_id, (
            f"Expected user_id={expected_user_id} (from token) but got {submission.user_id}"
        )


# ---------------------------------------------------------------------------
# Test 4: WebSocket with valid token MUST use token-derived user_id
# ---------------------------------------------------------------------------
def test_ws_uses_token_not_query_param_user_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    auth = _register_and_login(client, "ws_boundary")
    token = auth["accessToken"]
    expected_user_id = auth["user"]["id"]

    conv_id = "conv_test_ws_auth"

    # Connect with ?token=<jwt>&user_id=999 — user_id=999 MUST be ignored.
    with client.websocket_connect(
        f"/ws/v1?token={token}&user_id=999&session_id=test&conversation_id={conv_id}"
    ) as ws:
        # Consume the initial TASK_STARTED event.
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        # Send CONTEXT_SET to trigger a DB-persisted event (without user_id in payload).
        ws.send_json({
            "type": "CONTEXT_SET",
            "payload": {"system_prompt": "You are a helpful assistant."},
        })
        resp = ws.receive_json()
        assert resp["type"] == "CONTEXT_SET"

    # Verify the persisted ConversationEvent has the token-derived user_id.
    with Session(engine) as session:
        events = list(
            session.exec(
                select(ConversationEvent)
                .where(ConversationEvent.conversation_id == conv_id)
                .where(ConversationEvent.type == "CONTEXT_SET")
            ).all()
        )
        assert len(events) >= 1
        for evt in events:
            assert evt.user_id == expected_user_id, (
                f"Expected user_id={expected_user_id} (from token) but got {evt.user_id}"
            )


# ---------------------------------------------------------------------------
# Test 5: WebSocket without token or user_id — anonymous connection
# ---------------------------------------------------------------------------
def test_ws_anonymous_connection_ok(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()

    client = TestClient(app)
    conv_id = "conv_test_ws_anon"

    with client.websocket_connect(
        f"/ws/v1?session_id=test&conversation_id={conv_id}"
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "TASK_STARTED"

        # Send a CONTEXT_SET to persist an event with anonymous user_id.
        ws.send_json({
            "type": "CONTEXT_SET",
            "payload": {"system_prompt": "Hello anonymous."},
        })
        resp = ws.receive_json()
        assert resp["type"] == "CONTEXT_SET"

    with Session(engine) as session:
        events = list(
            session.exec(
                select(ConversationEvent)
                .where(ConversationEvent.conversation_id == conv_id)
                .where(ConversationEvent.type == "CONTEXT_SET")
            ).all()
        )
        assert len(events) >= 1
        for evt in events:
            assert evt.user_id is None, (
                f"Expected user_id=None (anonymous) but got {evt.user_id}"
            )


def _auth_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "auth-boundary.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    override_engine_for_tests(engine)
    init_db()
    return TestClient(app)


def test_access_and_refresh_tokens_cannot_be_interchanged(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    auth = _register_and_login(client, "token_types")

    me_with_refresh = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {auth['refreshToken']}"},
    )
    assert me_with_refresh.status_code == 401

    refresh_with_access = client.post(
        "/api/auth/refresh",
        json={"refreshToken": auth["accessToken"]},
    )
    assert refresh_with_access.status_code == 200
    assert refresh_with_access.json() == {
        "success": False,
        "data": None,
        "error": "Invalid or expired session",
    }

    refresh_with_refresh = client.post(
        "/api/auth/refresh",
        json={"refreshToken": auth["refreshToken"]},
    )
    assert refresh_with_refresh.status_code == 200
    assert refresh_with_refresh.json()["success"] is True


def test_access_token_user_id_claim_must_match_database_account(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    auth = _register_and_login(client, "claim_subject")
    mismatched = create_access_token(
        {"sub": "claim_subject", "userId": auth["user"]["id"] + 1}
    )

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {mismatched}"},
    )
    assert response.status_code == 401


def test_claimed_role_must_match_database_role(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    auth = _register_and_login(client, "claim_role")
    forged_role = create_access_token(
        {
            "sub": "claim_role",
            "userId": auth["user"]["id"],
            "role": "teacher",
        }
    )

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {forged_role}"},
    )
    assert response.status_code == 401


def test_deleted_account_invalidates_existing_access_token(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    auth = _register_and_login(client, "deleted_account")
    engine = get_engine()
    with Session(engine) as session:
        user = session.get(User, auth["user"]["id"])
        assert user is not None
        session.delete(user)
        session.commit()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {auth['accessToken']}"},
    )
    assert response.status_code == 401


def test_invalid_database_role_fails_closed(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    _register_and_login(client, "invalid_role")
    engine = get_engine()
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == "invalid_role")).one()
        user.role = "unexpected"
        session.add(user)
        session.commit()

        assert has_role(user, Role.STUDENT) is False
        assert has_permission(user, "read:own_profile") is False

    response = client.post(
        "/api/auth/login",
        json={"username": "invalid_role", "password": "Admin1234"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == "Invalid username or password"

def test_registration_conflicts_do_not_reveal_which_field_exists(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    _register_and_login(client, "existing_account")

    username_conflict = client.post(
        "/api/auth/register",
        json={
            "username": "existing_account",
            "email": "different@example.com",
            "password": "Admin1234",
        },
    ).json()
    email_conflict = client.post(
        "/api/auth/register",
        json={
            "username": "different_account",
            "email": "existing_account@example.com",
            "password": "Admin1234",
        },
    ).json()

    assert username_conflict["success"] is False
    assert email_conflict["success"] is False
    assert username_conflict["error"] == email_conflict["error"]
    assert username_conflict["error"] == "Unable to register with provided credentials"


def test_login_failures_do_not_reveal_account_existence(tmp_path: Path) -> None:
    client = _auth_client(tmp_path)
    _register_and_login(client, "known_login")

    wrong_password = client.post(
        "/api/auth/login",
        json={"username": "known_login", "password": "WrongPassword123"},
    ).json()
    unknown_account = client.post(
        "/api/auth/login",
        json={"username": "unknown_login", "password": "WrongPassword123"},
    ).json()

    assert wrong_password == unknown_account
    assert wrong_password == {
        "success": False,
        "data": None,
        "error": "Invalid username or password",
    }


def test_non_development_settings_reject_default_auth_secrets() -> None:
    with pytest.raises(ValidationError, match="AIFL_JWT_SECRET"):
        Settings(
            _env_file=None,
            AIFL_APP_ENV="production",
            AIFL_SEED_ADMIN_ENABLED=False,
        )

    with pytest.raises(ValidationError, match="AIFL_SEED_ADMIN_PASSWORD"):
        Settings(
            _env_file=None,
            AIFL_APP_ENV="production",
            AIFL_JWT_SECRET="production-secret-that-is-not-the-default",
            AIFL_SEED_ADMIN_ENABLED=True,
        )

    production = Settings(
        _env_file=None,
        AIFL_APP_ENV="production",
        AIFL_JWT_SECRET="production-secret-that-is-not-the-default",
        AIFL_SEED_ADMIN_ENABLED=True,
        AIFL_SEED_ADMIN_PASSWORD="ChangedAdmin1234!",
    )
    assert production.app_env == "production"
