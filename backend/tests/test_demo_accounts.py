from sqlalchemy import select
from app.auth import hasher
from app.cli import DEMO_USERS, configure_demo, seed
from app.config import settings
from app.db import Session
from app.models import User, Ticket
from app.service import Principal, create


def test_demo_reset_sets_five_active_accounts_and_preserves_history():
    ticket, _ = create(Principal(1, 'employee'), 'R005', '旧样例原文')
    configure_demo()
    with Session() as db:
        users = db.scalars(select(User)).all()
        active = [u for u in users if u.is_active]
        assert {u.username for u in active} == {name for name, _, _ in DEMO_USERS}
        assert sum(u.role == 'employee' for u in active) == 3
        assert sum(u.role == 'support' for u in active) == 2
        assert all(hasher.verify(u.password_hash, settings().demo_password.get_secret_value()) for u in users)
        old = db.get(Ticket, ticket['id'])
        assert old.submitter_id == 1 and old.original_text == '旧样例原文'
        ids = {u.username: u.id for u in users}
    configure_demo()
    with Session() as db:
        assert {u.username: u.id for u in db.scalars(select(User))} == ids


async def test_seed_preserves_existing_sample_owner_and_password():
    old, _ = create(Principal(1, 'employee'), 'R005', '旧样例原文')
    configure_demo()
    with Session() as db:
        before = db.scalar(select(User).where(User.username == 'xiaoli')).password_hash
    await seed()
    with Session() as db:
        assert db.get(Ticket, old['id']).submitter_id == 1
        assert db.get(Ticket, old['id']).original_text == '旧样例原文'
        assert db.scalar(select(User).where(User.username == 'xiaoli')).password_hash == before
