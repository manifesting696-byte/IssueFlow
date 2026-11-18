from dataclasses import dataclass
from datetime import timedelta
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from .db import Session
from .models import Ticket, Event, Revision, utcnow
from .errors import BusinessError
from .classifier import Result
from .config import settings


@dataclass(frozen=True)
class Principal:
    id: int
    role: str


def ticket_dict(ticket):
    data = {c.name: getattr(ticket, c.name) for c in Ticket.__table__.columns}
    data.update(submitter_name=ticket.submitter.display_name,
                submitter_username=ticket.submitter.username)
    return data


def event(db, ticket_id, actor_id, event_type, **detail):
    db.add(Event(ticket_id=ticket_id, actor_id=actor_id, event_type=event_type, detail=detail))


def visible_query(principal, request_id=None):
    query = select(Ticket)
    if principal.role != 'support':
        query = query.where(Ticket.submitter_id == principal.id)
    if request_id is not None:
        query = query.where(Ticket.request_id == request_id)
    return query


def get_visible(db, principal, request_id):
    ticket = db.scalar(visible_query(principal, request_id))
    if ticket is None:
        raise BusinessError(404, 'TICKET_NOT_FOUND', '工单不存在')
    return ticket


def detail(principal, request_id):
    with Session() as db:
        return ticket_dict(get_visible(db, principal, request_id))


def create(principal, request_id, content):
    with Session.begin() as db:
        ticket_id = db.scalar(insert(Ticket).values(request_id=request_id, submitter_id=principal.id,
            original_text=content, current_text=content).on_conflict_do_nothing(index_elements=['request_id']).returning(Ticket.id))
        if ticket_id is None:
            existing = db.scalar(select(Ticket).where(Ticket.request_id == request_id))
            if existing is None:
                # A conflicting row was not visible after INSERT. Roll back and
                # let the client retry the same idempotency key; never dereference None.
                raise BusinessError(503, 'DATABASE_UNAVAILABLE', '数据库暂不可用，请稍后重试')
            if existing.submitter_id != principal.id or existing.original_text != content:
                raise BusinessError(409, 'REQUEST_ID_CONFLICT', '该提交编号已使用，请使用新的编号')
            return ticket_dict(existing), False
        event(db, ticket_id, principal.id, 'ticket_created')
        ticket = db.get(Ticket, ticket_id)
        return ticket_dict(ticket), True


def apply_classification(snapshot, result: Result):
    with Session.begin() as db:
        ticket = db.scalar(update(Ticket).where(Ticket.id == snapshot['id'], Ticket.version == snapshot['version'],
            Ticket.classification_source == 'pending', Ticket.status != 'completed').values(
                category=result.category, classification_source=result.source, version=Ticket.version + 1,
                updated_at=utcnow()).returning(Ticket))
        if ticket is None:
            return False
        event(db, ticket.id, None, 'classification_failed' if result.source == 'fallback' else 'ticket_classified',
              category=result.category, source=result.source, **result.detail)
        return True


def require_support(principal):
    if principal.role != 'support':
        raise BusinessError(403, 'FORBIDDEN', '该操作需要技术支持权限')


def validate_write(ticket, expected_version):
    if ticket.status == 'completed':
        raise BusinessError(409, 'TICKET_COMPLETED', '工单已完成，不能再修改')
    if ticket.version != expected_version:
        raise BusinessError(409, 'TICKET_VERSION_CONFLICT', '工单已更新，请刷新后重试')


def mutate(principal, request_id, action, data):
    if action != 'content':
        require_support(principal)
    with Session.begin() as db:
        ticket = get_visible(db, principal, request_id)
        if action == 'content' and ticket.submitter_id != principal.id:
            raise BusinessError(403, 'FORBIDDEN', '只有提交者本人可以补充内容')
        validate_write(ticket, data.expected_version)
        values = {'version': Ticket.version + 1, 'updated_at': utcnow()}
        conditions = [Ticket.id == ticket.id, Ticket.version == data.expected_version, Ticket.status != 'completed']
        old = ticket_dict(ticket)
        if action == 'status':
            if data.status == ticket.status:
                return old
            allowed = {'pending': {'in_progress', 'completed'}, 'in_progress': {'pending', 'completed'}}
            if data.status not in allowed[ticket.status]:
                raise BusinessError(409, 'INVALID_STATUS_TRANSITION', '不允许此状态流转')
            if data.status == 'completed' and ticket.classification_source == 'pending':
                raise BusinessError(409, 'CLASSIFICATION_PENDING', '请等待分类完成或先人工确认分类')
            values['status'] = data.status.value
            if data.status == 'completed':
                values['edit_requested'] = False
        elif action == 'clarification':
            if ticket.edit_requested:
                raise BusinessError(409, 'CLARIFICATION_ALREADY_REQUESTED', '已有待响应的补充请求')
            conditions.append(Ticket.edit_requested.is_(False))
            values['edit_requested'] = True
        elif action == 'content':
            if not ticket.edit_requested:
                raise BusinessError(409, 'EDIT_NOT_ALLOWED', '当前没有开放的补充请求')
            if data.content == ticket.current_text:
                raise BusinessError(409, 'CONTENT_UNCHANGED', '补充内容与当前内容相同')
            conditions.extend([Ticket.edit_requested.is_(True), Ticket.submitter_id == principal.id])
            values.update(current_text=data.content, edit_requested=False, category='uncertain', classification_source='pending')
        elif action == 'category':
            if data.category == ticket.category:
                return old
            values.update(category=data.category.value, classification_source='manual')
        else:
            raise ValueError('Unknown action')
        changed = db.scalar(update(Ticket).where(*conditions).values(**values).returning(Ticket).execution_options(populate_existing=True))
        if changed is None:
            # Refresh under READ COMMITTED after losing CAS; never blindly overwrite.
            db.expire_all()
            current = get_visible(db, principal, request_id)
            validate_write(current, data.expected_version)
            raise BusinessError(409, 'TICKET_VERSION_CONFLICT', '工单已更新，请刷新后重试')
        if action == 'status':
            event(db, ticket.id, principal.id, 'status_changed', old_status=old['status'], new_status=data.status.value)
            if data.status == 'completed' and old['edit_requested']:
                event(db, ticket.id, principal.id, 'clarification_closed', reason='ticket_completed')
        elif action == 'clarification':
            event(db, ticket.id, principal.id, 'clarification_requested', message=data.message)
        elif action == 'content':
            revision = Revision(ticket_id=ticket.id, editor_id=principal.id, old_text=old['current_text'], new_text=data.content, edit_type='clarification')
            db.add(revision)
            db.flush()
            event(db, ticket.id, principal.id, 'content_updated', revision_id=revision.id)
        elif action == 'category':
            event(db, ticket.id, principal.id, 'category_corrected', old_category=old['category'], new_category=data.category.value, reason=data.reason)
        return ticket_dict(changed)


def listing(principal, status=None, category=None, q='', page=1, page_size=20):
    query = visible_query(principal)
    if status:
        query = query.where(Ticket.status == status)
    if category:
        query = query.where(Ticket.category == category)
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.where(or_(Ticket.request_id.ilike('%' + escaped + '%', escape='\\'), Ticket.current_text.ilike('%' + escaped + '%', escape='\\')))
    with Session() as db:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(query.order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset((page-1)*page_size).limit(page_size))
        return {'items': [ticket_dict(row) for row in rows], 'total': total, 'page': page, 'page_size': page_size}


def history(principal, request_id):
    with Session() as db:
        ticket = get_visible(db, principal, request_id)
        events = db.scalars(select(Event).where(Event.ticket_id == ticket.id).order_by(Event.created_at, Event.id))
        revisions = db.scalars(select(Revision).where(Revision.ticket_id == ticket.id).order_by(Revision.created_at, Revision.id))
        return {'events': [{c.name: getattr(row, c.name) for c in Event.__table__.columns} for row in events],
                'revisions': [{c.name: getattr(row, c.name) for c in Revision.__table__.columns} for row in revisions]}


def recover_pending(age_seconds=None):
    budget = settings().llm_timeout_seconds
    if age_seconds is None:
        age_seconds = budget + 60
    if age_seconds < budget + 10:
        raise ValueError('Recovery threshold must exceed the classification budget')
    cutoff = utcnow() - timedelta(seconds=age_seconds)
    with Session() as db:
        snapshots = [ticket_dict(row) for row in db.scalars(select(Ticket).where(
            Ticket.classification_source == 'pending', Ticket.status != 'completed', Ticket.updated_at < cutoff).limit(500))]
    return sum(apply_classification(row, Result(detail={'reason_code': 'PENDING_RECOVERED'})) for row in snapshots)
