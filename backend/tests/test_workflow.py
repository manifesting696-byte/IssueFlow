import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from app import classifier, service
from app.classifier import Result
from app.db import Session, engine
from app.errors import BusinessError
from app.main import app
from app.models import Event, Revision, Ticket, User, utcnow
from app.schemas import CategoryUpdate, Clarification, ContentUpdate, StatusUpdate
from conftest import logged_in


def count(model, **filters):
    with Session() as db:
        return db.scalar(select(func.count()).select_from(model).filter_by(**filters))


def new(client, request_id='TEST', content='登录失败'):
    result = client.post('/api/tickets', json={'request_id': request_id, 'content': content})
    assert result.status_code == 201, result.text
    return result.json()


@pytest.mark.parametrize('content', ['', ' ', '\n\t\r', '\u3000', 'x' * 5001, 123])
def test_T01_invalid_no_side_effect(employee, monkeypatch, content):
    async def forbidden(text):
        raise AssertionError('LLM must not be invoked')
    monkeypatch.setattr(classifier, 'classify', forbidden)
    assert employee.post('/api/tickets', json={'request_id': 'INVALID', 'content': content}).status_code == 422
    assert count(Ticket) == count(Event) == 0


@pytest.mark.parametrize('identifier', ['contains space', '../escape', '', 'X' * 65, '中文'])
def test_invalid_identifier(employee, identifier):
    assert employee.post('/api/tickets', json={'request_id': identifier, 'content': '登录失败'}).status_code == 422
    assert count(Ticket) == 0


def test_T02_idempotency_uses_original_after_edit(employee, support):
    original = '  登录失败\n'
    t = new(employee, content=original)
    support.post('/api/tickets/TEST/clarification-request', json={'expected_version': t['version'], 'message': '请提供错误码'})
    t = employee.get('/api/tickets/TEST').json()
    changed = employee.patch('/api/tickets/TEST/content', json={'expected_version': t['version'], 'content': '系统登录提示403错误'}).json()
    retry = employee.post('/api/tickets', json={'request_id': 'TEST', 'content': original})
    assert retry.status_code == 200
    assert retry.json()['original_text'] == original
    assert retry.json()['current_text'] == changed['current_text']
    assert count(Ticket) == 1 and count(Event, event_type='ticket_created') == 1


def test_T03_conflicting_id(employee):
    new(employee)
    other = logged_in('other')
    for client, content in [(employee, '不同原文'), (other, '登录失败')]:
        r = client.post('/api/tickets', json={'request_id': 'TEST', 'content': content})
        assert r.status_code == 409 and r.json()['code'] == 'REQUEST_ID_CONFLICT'
        assert 'submitter' not in r.text and '登录失败' not in r.text
    assert employee.get('/api/tickets/TEST').json()['original_text'] == '登录失败'


def race(functions):
    barrier = threading.Barrier(len(functions))
    def run(function):
        barrier.wait()
        try:
            return ('ok', function())
        except BusinessError as error:
            return (error.status, error.code)
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return list(pool.map(run, functions))


def test_T04_real_concurrent_insert(principals):
    employee, _, _ = principals
    results = race([lambda: service.create(employee, 'RACE', '登录失败') for _ in range(2)])
    assert all(r[0] == 'ok' for r in results)
    assert sorted(r[1][1] for r in results) == [False, True]
    assert count(Ticket) == 1 and count(Event) == 1


def test_T05_concurrent_status(employee, principals):
    t = new(employee)
    _, a, b = principals
    data = StatusUpdate(expected_version=t['version'], status='in_progress')
    results = race([lambda: service.mutate(a, 'TEST', 'status', data), lambda: service.mutate(b, 'TEST', 'status', data)])
    assert sorted(str(r[0]) for r in results) == ['409', 'ok']
    assert count(Event, event_type='status_changed') == 1


def test_T06_audit_failure_rolls_back(employee, principals):
    t = new(employee)
    def fail(mapper, connection, target):
        if target.event_type == 'status_changed':
            raise RuntimeError('fault injection')
    sql_event.listen(Event, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError):
            service.mutate(principals[1], 'TEST', 'status', StatusUpdate(expected_version=t['version'], status='in_progress'))
    finally:
        sql_event.remove(Event, 'before_insert', fail)
    after = employee.get('/api/tickets/TEST').json()
    assert (after['status'], after['version']) == (t['status'], t['version'])
    assert count(Event, event_type='status_changed') == 0


def test_T07_no_direct_edit(employee):
    t = new(employee)
    response = employee.patch('/api/tickets/TEST/content', json={'content': '修改', 'expected_version': t['version']})
    assert response.status_code == 409 and response.json()['code'] == 'EDIT_NOT_ALLOWED'
    assert count(Revision) == 0


def test_T08_concurrent_clarification(employee, principals):
    t = new(employee)
    data = Clarification(expected_version=t['version'], message='请补充错误码')
    results = race([lambda: service.mutate(p, 'TEST', 'clarification', data) for p in principals[1:]])
    assert sorted(str(r[0]) for r in results) == ['409', 'ok']
    assert count(Event, event_type='clarification_requested') == 1 and count(Revision) == 0


def test_T09_concurrent_response(employee, principals):
    t = new(employee)
    t = service.mutate(principals[1], 'TEST', 'clarification', Clarification(expected_version=t['version'], message='请补充'))
    data = ContentUpdate(expected_version=t['version'], content='系统登录提示403错误')
    results = race([lambda: service.mutate(principals[0], 'TEST', 'content', data) for _ in range(2)])
    assert sorted(str(r[0]) for r in results) == ['409', 'ok']
    assert count(Revision) == 1 and count(Event, event_type='content_updated') == 1
    assert service.detail(principals[0], 'TEST')['original_text'] == '登录失败'


def test_T10_complete_races_response(employee, principals):
    t = new(employee)
    t = service.mutate(principals[1], 'TEST', 'clarification', Clarification(expected_version=t['version'], message='请补充'))
    results = race([
        lambda: service.mutate(principals[1], 'TEST', 'status', StatusUpdate(expected_version=t['version'], status='completed')),
        lambda: service.mutate(principals[0], 'TEST', 'content', ContentUpdate(expected_version=t['version'], content='系统登录提示403错误')),
    ])
    assert sorted(str(r[0]) for r in results) == ['409', 'ok']
    current = service.detail(principals[0], 'TEST')
    if current['status'] == 'completed':
        assert current['current_text'] == '登录失败' and count(Revision) == 0
        assert count(Event, event_type='clarification_closed') == 1
    else:
        assert count(Revision) == 1 and current['classification_source'] == 'pending'


def test_T11_completed_read_only(employee, support):
    t = new(employee)
    t = support.patch('/api/tickets/TEST/status', json={'expected_version': t['version'], 'status': 'completed'}).json()
    for method, path, data in [
        ('patch', '/status', {'status': 'pending'}), ('patch', '/category', {'category': 'uncertain', 'reason': '复核'}),
        ('post', '/clarification-request', {'message': '请补充'}), ('patch', '/content', {'content': '修改'})]:
        client = employee if path == '/content' else support
        r = getattr(client, method)('/api/tickets/TEST' + path, json={'expected_version': t['version'], **data})
        assert r.status_code == 409 and r.json()['code'] == 'TICKET_COMPLETED'
    assert employee.get('/api/tickets/TEST').status_code == 200


def test_T13_late_result_cannot_override_manual(employee, principals):
    t = new(employee)
    with Session.begin() as db:
        db.execute(update(Ticket).where(Ticket.id == t['id']).values(classification_source='pending'))
    manual = service.mutate(principals[1], 'TEST', 'category', CategoryUpdate(expected_version=t['version'], category='usage_consultation', reason='人工确认'))
    assert not service.apply_classification(t, Result('system_fault', 'llm'))
    current = service.detail(principals[0], 'TEST')
    assert current['classification_source'] == 'manual' and current['version'] == manual['version']


def test_T12_fallback_still_commits_ticket_and_event(employee):
    t = new(employee, content='那个先不用了。')
    assert (t['category'], t['classification_source']) == ('uncertain', 'fallback')
    assert count(Ticket) == 1
    assert count(Event, event_type='classification_failed') == 1


@pytest.mark.parametrize('statement', [
    "UPDATE tickets SET version=0", "UPDATE tickets SET category='invalid'",
    "UPDATE tickets SET current_text='   '", "UPDATE tickets SET submitter_id=999999",
])
def test_database_constraints(employee, statement):
    new(employee)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text(statement))


def test_T14_out_of_order_content_classification(employee, principals):
    t = new(employee)
    t = service.mutate(principals[1], 'TEST', 'clarification', Clarification(expected_version=t['version'], message='补充'))
    revised = service.mutate(principals[0], 'TEST', 'content', ContentUpdate(expected_version=t['version'], content='请问怎么重置密码'))
    assert not service.apply_classification(t, Result('system_fault', 'llm'))
    assert service.apply_classification(revised, Result('usage_consultation', 'rule'))
    assert service.detail(principals[0], 'TEST')['category'] == 'usage_consultation'


def test_T15_data_and_role_boundary(employee):
    t = new(employee)
    other = logged_in('other')
    assert other.get('/api/tickets/TEST').status_code == 404
    assert other.get('/api/tickets/TEST/history').status_code == 404
    assert other.get('/api/tickets').json()['total'] == 0
    assert employee.patch('/api/tickets/TEST/status', json={'status': 'completed', 'expected_version': t['version']}).status_code == 403
    assert employee.post('/api/tickets', json={'request_id': 'SPOOF', 'content': '登录失败', 'submitter_id': 2}).status_code == 422


def test_T16_pending_recovery_idempotent(principals):
    t, _ = service.create(principals[0], 'PENDING', '含糊信息')
    with Session.begin() as db:
        db.execute(update(Ticket).where(Ticket.id == t['id']).values(updated_at=utcnow() - timedelta(minutes=2)))
    assert service.recover_pending() == 1
    assert service.recover_pending() == 0
    assert count(Event, event_type='classification_failed') == 1


def test_recovery_does_not_interrupt_one_minute_classification(principals):
    t, _ = service.create(principals[0], 'STILL-RUNNING', '含糊信息')
    with Session.begin() as db:
        db.execute(update(Ticket).where(Ticket.id == t['id']).values(updated_at=utcnow() - timedelta(seconds=45)))
    assert service.recover_pending() == 0
    assert service.detail(principals[0], 'STILL-RUNNING')['classification_source'] == 'pending'
    with pytest.raises(ValueError):
        service.recover_pending(age_seconds=60)


def test_T17_persist_after_connection_restart(employee):
    t = new(employee)
    engine.dispose()
    fresh = TestClient(app)
    fresh.cookies.update(employee.cookies)
    assert fresh.get('/api/tickets/TEST').json()['original_text'] == t['original_text']
    assert len(fresh.get('/api/tickets/TEST/history').json()['events']) == 2


def test_database_immutable_and_append_only(employee):
    t = new(employee)
    for statement in ["UPDATE tickets SET original_text='tamper'", 'DELETE FROM tickets', 'DELETE FROM ticket_events', "UPDATE ticket_events SET detail='{}'::jsonb"]:
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(text(statement))
    assert employee.get('/api/tickets/TEST').json()['original_text'] == t['original_text']


def test_csrf_and_disabled_user(employee):
    employee.headers.pop('x-csrf-token')
    assert employee.post('/api/tickets', json={'request_id': 'CSRF', 'content': '登录失败'}).status_code == 403
    with Session.begin() as db:
        db.execute(update(User).where(User.id == 1).values(is_active=False))
    assert employee.get('/api/tickets').status_code == 401


def test_noop_and_stale_version(employee, support):
    t = new(employee)
    before = count(Event)
    result = support.patch('/api/tickets/TEST/status', json={'status': 'pending', 'expected_version': t['version']})
    assert result.status_code == 200 and result.json()['version'] == t['version']
    assert count(Event) == before
    assert support.patch('/api/tickets/TEST/status', json={'status': 'pending', 'expected_version': 1}).status_code == 409


def test_body_limit_and_unauthenticated():
    client = TestClient(app)
    assert client.get('/api/tickets').status_code == 401
    assert client.post('/api/tickets', content='x' * 33000).status_code == 413


def test_login_rate_limit():
    client = TestClient(app)
    client.headers['x-csrf-token'] = client.get('/api/auth/csrf').json()['csrf_token']
    for _ in range(10):
        assert client.post('/api/auth/login', json={'username': 'employee', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'employee', 'password': 'wrong'}).status_code == 429
