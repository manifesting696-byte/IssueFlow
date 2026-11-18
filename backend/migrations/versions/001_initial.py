"""Four business tables, constraints, indexes and immutable audit guards."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def time_column(name):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)


def upgrade():
    op.create_table('users', sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False), time_column('created_at'),
        sa.CheckConstraint("role IN ('employee','support')", name='ck_users_role'))
    op.create_table('tickets', sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('request_id', sa.String(64), nullable=False, unique=True),
        sa.Column('submitter_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=False), sa.Column('current_text', sa.Text(), nullable=False),
        sa.Column('category', sa.String(30), server_default='uncertain', nullable=False),
        sa.Column('classification_source', sa.String(20), server_default='pending', nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('edit_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('version', sa.Integer(), server_default='1', nullable=False), time_column('created_at'), time_column('updated_at'),
        sa.CheckConstraint("status IN ('pending','in_progress','completed')", name='ck_tickets_status'),
        sa.CheckConstraint("category IN ('system_fault','permission_request','feature_suggestion','usage_consultation','uncertain')", name='ck_tickets_category'),
        sa.CheckConstraint("classification_source IN ('pending','rule','llm','fallback','manual')", name='ck_tickets_source'),
        sa.CheckConstraint('version > 0', name='ck_tickets_version'),
        sa.CheckConstraint("length(btrim(original_text, E' \\t\\n\\r\\f\\v')) > 0 AND length(btrim(current_text, E' \\t\\n\\r\\f\\v')) > 0", name='ck_tickets_text_basic'))
    op.create_table('ticket_revisions', sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('ticket_id', sa.BigInteger(), sa.ForeignKey('tickets.id'), nullable=False),
        sa.Column('editor_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('old_text', sa.Text(), nullable=False), sa.Column('new_text', sa.Text(), nullable=False),
        sa.Column('edit_type', sa.String(20), nullable=False), time_column('created_at'))
    op.create_table('ticket_events', sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('ticket_id', sa.BigInteger(), sa.ForeignKey('tickets.id'), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('detail', JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False), time_column('created_at'))
    op.create_index('ix_tickets_submitter_created', 'tickets', ['submitter_id', sa.text('created_at DESC')])
    op.create_index('ix_tickets_status_created', 'tickets', ['status', sa.text('created_at DESC')])
    op.create_index('ix_events_ticket_time', 'ticket_events', ['ticket_id', 'created_at', 'id'])
    op.create_index('ix_revisions_ticket_time', 'ticket_revisions', ['ticket_id', 'created_at', 'id'])
    op.execute('''CREATE FUNCTION issueflow_protect_ticket() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'ticket deletion prohibited'; END IF;
      IF OLD.original_text IS DISTINCT FROM NEW.original_text OR OLD.request_id IS DISTINCT FROM NEW.request_id
         OR OLD.submitter_id IS DISTINCT FROM NEW.submitter_id THEN RAISE EXCEPTION 'immutable ticket identity or original'; END IF;
      IF OLD.status = 'completed' THEN RAISE EXCEPTION 'completed ticket is read only'; END IF;
      RETURN NEW;
    END; $$''')
    op.execute('CREATE TRIGGER protect_ticket BEFORE UPDATE OR DELETE ON tickets FOR EACH ROW EXECUTE FUNCTION issueflow_protect_ticket()')
    op.execute('''CREATE FUNCTION issueflow_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'audit records are append only'; END; $$''')
    for table in ('ticket_revisions', 'ticket_events'):
        op.execute(f'CREATE TRIGGER protect_audit BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION issueflow_append_only()')


def downgrade():
    for table in ('ticket_events', 'ticket_revisions', 'tickets', 'users'):
        op.drop_table(table)
    op.execute('DROP FUNCTION issueflow_append_only()')
    op.execute('DROP FUNCTION issueflow_protect_ticket()')
