from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text('true'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text('now()'))
    __table_args__ = (CheckConstraint("role IN ('employee','support')", name='ck_users_role'),)


class Ticket(Base):
    __tablename__ = 'tickets'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)
    submitter_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    submitter: Mapped[User] = relationship(lazy='selectin')
    original_text: Mapped[str] = mapped_column(Text)
    current_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default='uncertain', server_default='uncertain')
    classification_source: Mapped[str] = mapped_column(String(20), default='pending', server_default='pending')
    status: Mapped[str] = mapped_column(String(20), default='pending', server_default='pending')
    edit_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text('false'))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text('now()'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text('now()'))
    __table_args__ = (
        CheckConstraint("status IN ('pending','in_progress','completed')", name='ck_tickets_status'),
        CheckConstraint("category IN ('system_fault','permission_request','feature_suggestion','usage_consultation','uncertain')", name='ck_tickets_category'),
        CheckConstraint("classification_source IN ('pending','rule','llm','fallback','manual')", name='ck_tickets_source'),
        CheckConstraint('version > 0', name='ck_tickets_version'),
        CheckConstraint("length(btrim(original_text, E' \\t\\n\\r\\f\\v')) > 0 AND length(btrim(current_text, E' \\t\\n\\r\\f\\v')) > 0", name='ck_tickets_text_basic'),
        Index('ix_tickets_submitter_created', 'submitter_id', text('created_at DESC')),
        Index('ix_tickets_status_created', 'status', text('created_at DESC')),
    )


class Revision(Base):
    __tablename__ = 'ticket_revisions'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    editor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    old_text: Mapped[str] = mapped_column(Text)
    new_text: Mapped[str] = mapped_column(Text)
    edit_type: Mapped[str] = mapped_column(String(20), default='clarification')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text('now()'))
    __table_args__ = (Index('ix_revisions_ticket_time', 'ticket_id', 'created_at', 'id'),)


class Event(Base):
    __tablename__ = 'ticket_events'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=text('now()'))
    __table_args__ = (Index('ix_events_ticket_time', 'ticket_id', 'created_at', 'id'),)
