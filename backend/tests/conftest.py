"""Tests use an isolated PostgreSQL database, never the application's data."""
import os
import secrets
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATABASE_URL'] = os.environ.get('TEST_DATABASE_URL', 'postgresql+psycopg://issueflow:issueflow_local@127.0.0.1:5432/issueflow_test')
os.environ['JWT_SECRET'] = 'test-only-' + secrets.token_urlsafe(40)
os.environ['LLM_ENABLED'] = 'false'
os.environ['LLM_TIMEOUT_SECONDS'] = '60'

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.db import engine, Session
from app.models import User
from app.auth import hasher, _attempts
from app.main import app
from app.service import Principal


@pytest.fixture(scope='session', autouse=True)
def migrate():
    if not engine.url.database.endswith('_test'):
        raise RuntimeError('Refusing to clear a non-test database')
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'migrations'))
    command.upgrade(config, 'head')
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def reset(migrate):
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE ticket_events, ticket_revisions, tickets, users RESTART IDENTITY CASCADE'))
    password_hash = hasher.hash('Test-password-2026!')
    with Session.begin() as db:
        db.add_all([User(username='employee', display_name='员工甲', password_hash=password_hash, role='employee'),
                    User(username='other', display_name='员工乙', password_hash=password_hash, role='employee'),
                    User(username='support', display_name='技支甲', password_hash=password_hash, role='support'),
                    User(username='support2', display_name='技支乙', password_hash=password_hash, role='support')])
    _attempts.clear()


def logged_in(username):
    client = TestClient(app)
    token = client.get('/api/auth/csrf').json()['csrf_token']
    client.headers['x-csrf-token'] = token
    response = client.post('/api/auth/login', json={'username': username, 'password': 'Test-password-2026!'})
    assert response.status_code == 200, response.text
    client.headers['x-csrf-token'] = client.cookies['issueflow_csrf']
    return client


@pytest.fixture
def employee():
    with logged_in('employee') as client:
        yield client


@pytest.fixture
def support():
    with logged_in('support') as client:
        yield client


@pytest.fixture
def principals():
    return Principal(1, 'employee'), Principal(3, 'support'), Principal(4, 'support')
