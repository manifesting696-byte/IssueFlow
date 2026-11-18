from sqlalchemy import event, select
from app.cli import SAMPLES, seed
from app.db import engine, Session
from app.models import User, Ticket
from app.service import create, listing
from conftest import logged_in


def test_creator_name_and_username_follow_authenticated_user(employee, support):
    response = employee.post('/api/tickets', json={'request_id': 'CREATOR', 'content': '登录失败'})
    assert response.status_code == 201
    ticket = response.json()
    assert ticket['submitter_name'] == '员工甲'
    assert ticket['submitter_username'] == 'employee'
    for result in [support.get('/api/tickets/CREATOR'), employee.get('/api/tickets/CREATOR')]:
        assert result.json()['submitter_name'] == '员工甲'
        assert 'password_hash' not in result.text
    other = logged_in('other')
    assert other.get('/api/tickets/CREATOR').status_code == 404
    assert other.get('/api/tickets').json()['total'] == 0
    updated = support.patch('/api/tickets/CREATOR/status', json={
        'status': 'in_progress', 'expected_version': ticket['version']})
    assert updated.json()['submitter_username'] == 'employee'


def test_creator_listing_is_batched_not_per_ticket(principals):
    for index in range(12):
        create(principals[0], 'CREATOR-' + str(index), '登录失败')
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        data = listing(principals[1])
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert len(data['items']) == 12
    assert all(row['submitter_username'] == 'employee' for row in data['items'])
    assert len(statements) <= 3


async def test_seed_provides_other_users_samples_without_duplicates():
    await seed()
    with Session() as db:
        ids = {u.username: u.id for u in db.scalars(select(User))}
        for username, expected_count in [('xiaozhou', 3), ('xiaochen', 3), ('support', 2), ('support2', 2)]:
            sample_ids = [key for key, owner, _ in SAMPLES if key.startswith('DEMO-') and owner == username]
            rows = db.scalars(select(Ticket).where(Ticket.request_id.in_(sample_ids))).all()
            assert len(rows) == expected_count
            assert all(row.submitter_id == ids[username] for row in rows)
        before = {t.request_id: t.id for t in db.scalars(select(Ticket))}
    await seed()
    with Session() as db:
        assert {t.request_id: t.id for t in db.scalars(select(Ticket))} == before
