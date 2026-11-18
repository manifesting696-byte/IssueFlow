"""Regression cases for review findings D2–D8."""
import asyncio
import secrets
from unittest.mock import MagicMock
from pathlib import Path
import ast
import re

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app import main, service
from app.config import Settings
from app.db import Session
from app.errors import BusinessError
from app.models import Event
from app.schemas import CategoryUpdate
from conftest import logged_in


def test_D2_same_category_is_noop_even_from_rule(employee, principals):
    t = employee.post('/api/tickets', json={'request_id': 'SAME', 'content': '登录失败'}).json()
    with Session() as db:
        before = db.scalar(select(func.count()).select_from(Event))
    result = service.mutate(principals[1], 'SAME', 'category', CategoryUpdate(
        expected_version=t['version'], category='system_fault', reason='再次确认'))
    assert result['version'] == t['version']
    assert result['classification_source'] == 'rule'
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Event)) == before
    with pytest.raises(BusinessError) as error:
        service.mutate(principals[1], 'SAME', 'category', CategoryUpdate(
            expected_version=t['version'] - 1, category='system_fault', reason='过期重试'))
    assert error.value.code == 'TICKET_VERSION_CONFLICT'


@pytest.mark.parametrize('page', ['0', '10001', '999999999999999999999999999999'])
def test_D4_page_bounds(employee, page):
    assert employee.get('/api/tickets', params={'page': page}).status_code == 422


def test_D4_max_page_is_valid(employee):
    assert employee.get('/api/tickets?page=10000').status_code == 200


def test_D1_search_finds_ticket_outside_first_page(principals):
    employee = principals[0]
    service.create(employee, 'OLDEST', '登录失败')
    for index in range(22):
        service.create(employee, 'NEW-' + str(index), '登录失败')
    first_page = service.listing(employee)
    assert first_page['total'] == 23
    assert 'OLDEST' not in {row['request_id'] for row in first_page['items']}
    searched = service.listing(employee, q='OLDEST')
    assert searched['total'] == 1 and searched['items'][0]['request_id'] == 'OLDEST'


async def test_D5_recovery_survives_unexpected_exception(monkeypatch, caplog):
    calls = 0
    recovered = asyncio.Event()
    def recover():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('private-content-must-not-be-logged')
        return 0
    async def fast_pause(seconds):
        if calls >= 2:
            recovered.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(main.service, 'recover_pending', recover)
    monkeypatch.setattr(main, 'recovery_pause', fast_pause, raising=False)
    task = asyncio.create_task(main.recovery_loop())
    try:
        await asyncio.wait_for(recovered.wait(), timeout=0.3)
        assert calls >= 2 and not task.done()
        assert 'pending_recovery_failed' in caplog.text
        assert 'private-content-must-not-be-logged' not in caplog.text
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_D6_missing_conflict_row_is_retryable(monkeypatch, principals):
    session = MagicMock()
    session.scalar.side_effect = [None, None]
    transaction = MagicMock()
    transaction.__enter__.return_value = session
    factory = MagicMock()
    factory.begin.return_value = transaction
    monkeypatch.setattr(service, 'Session', factory)
    with pytest.raises(BusinessError) as error:
        service.create(principals[0], 'INVISIBLE', '登录失败')
    assert error.value.status == 503
    assert error.value.code == 'DATABASE_UNAVAILABLE'
    session.add.assert_not_called()


@pytest.mark.parametrize('secret', [
    'replace-with-a-random-secret-at-least-32-characters',
    'changeme-' * 8, 'x' * 48, ' ' * 48,
])
def test_D7_placeholder_secret_rejected(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=secret)


def test_D7_random_secret_accepted():
    secret = secrets.token_urlsafe(48)
    assert Settings(_env_file=None, jwt_secret=secret).jwt_secret.get_secret_value() == secret


def test_D7_example_configuration_cannot_start_without_secret(monkeypatch):
    monkeypatch.delenv('JWT_SECRET')
    example = Path(__file__).resolve().parents[2] / '.env.example'
    with pytest.raises(ValidationError):
        Settings(_env_file=example)


def test_D3_every_defined_http_error_is_documented():
    root = Path(__file__).resolve().parents[2]
    codes = set()
    for path in (root / 'backend' / 'app').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'BusinessError':
                codes.add(node.args[1].value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == 'code' and isinstance(value, ast.Constant):
                        codes.add(value.value)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'code' for t in node.targets):
                codes.update(n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant)
                             and isinstance(n.value, str) and re.fullmatch('[A-Z_]+', n.value))
    documented = (root / 'README.md').read_text(encoding='utf-8')
    assert codes and all('`' + code + '`' in documented for code in codes), codes


def test_D8_visibility_and_role_priority(employee):
    t = employee.post('/api/tickets', json={'request_id': 'PRIVATE', 'content': '登录失败'}).json()
    other = logged_in('other')
    assert other.patch('/api/tickets/PRIVATE/content', json={
        'expected_version': t['version'], 'content': '补充信息'}).status_code == 404
    assert other.patch('/api/tickets/PRIVATE/status', json={
        'expected_version': t['version'], 'status': 'completed'}).status_code == 403
