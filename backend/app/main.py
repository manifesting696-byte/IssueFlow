import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from typing import Annotated
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text, select
from sqlalchemy.exc import SQLAlchemyError
from . import auth, classifier, schemas, service
from .config import settings
from .db import Session
from .errors import BusinessError
from .models import User

recovery_pause = asyncio.sleep


async def recovery_loop():
    while True:
        try:
            await asyncio.to_thread(service.recover_pending)
        except SQLAlchemyError:
            logging.getLogger('issueflow').warning('pending_recovery_database_unavailable')
        except Exception as error:
            # Keep the worker alive without leaking exception payloads or feedback.
            # CancelledError derives from BaseException and still propagates.
            logging.getLogger('issueflow').error('pending_recovery_failed error_type=%s', type(error).__name__)
        await recovery_pause(30)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(recovery_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title='IssueFlow', version='1.0.0', lifespan=lifespan)
Principal = Annotated[service.Principal, Depends(auth.authenticate)]


@app.middleware('http')
async def request_limits(request: Request, call_next):
    # Bound streamed bodies too, rather than trusting Content-Length.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            return JSONResponse({'code': 'REQUEST_TOO_LARGE', 'message': '请求内容过大'}, status_code=413)
    request._body = bytes(body)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.exception_handler(BusinessError)
async def business_error(request, error):
    return JSONResponse({'code': error.code, 'message': error.message}, status_code=error.status)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    code = 'INVALID_INPUT'
    for item in error.errors():
        if 'content' in item['loc']:
            code = 'CONTENT_TOO_LONG' if 'CONTENT_TOO_LONG' in item['msg'] else 'INVALID_CONTENT'
        elif 'request_id' in item['loc']:
            code = 'INVALID_REQUEST_ID'
    return JSONResponse({'code': code, 'message': '输入不符合要求，请检查内容、编号和字段类型'}, status_code=422)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    # No SQL text, bind values or full exception in client response/log.
    return JSONResponse({'code': 'DATABASE_UNAVAILABLE', 'message': '数据库暂不可用，请稍后重试'}, status_code=503)


@app.get('/api/health')
def health():
    with Session() as db:
        db.execute(text('SELECT 1'))
    return {'status': 'ok'}


@app.get('/api/auth/csrf')
def csrf(request: Request, response: Response):
    # Preserve an authenticated session's CSRF binding across page reloads.
    token = request.cookies.get('issueflow_csrf') or secrets.token_urlsafe(32)
    response.set_cookie('issueflow_csrf', token, httponly=False, secure=settings().cookie_secure, samesite='strict', path='/')
    return {'csrf_token': token}


@app.post('/api/auth/login')
def login(data: schemas.Login, request: Request, response: Response):
    return auth.login(request, response, data.username, data.password)


@app.get('/api/auth/me')
def me(principal: Principal):
    with Session() as db:
        user = db.get(User, principal.id)
        return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role}


@app.post('/api/auth/logout')
def logout(response: Response, principal: Principal):
    response.delete_cookie('issueflow_session', path='/')
    response.delete_cookie('issueflow_csrf', path='/')
    return {'ok': True}


async def classify_snapshot(snapshot):
    result = await classifier.classify(snapshot['current_text'])
    await asyncio.to_thread(service.apply_classification, snapshot, result)


@app.post('/api/tickets')
async def create_ticket(data: schemas.TicketCreate, response: Response, principal: Principal):
    ticket, created = await asyncio.to_thread(service.create, principal, data.request_id, data.content)
    if created:
        await classify_snapshot(ticket)
    response.status_code = 201 if created else 200
    return await asyncio.to_thread(service.detail, principal, data.request_id)


@app.get('/api/tickets')
def tickets(principal: Principal, status: schemas.Status | None = None, category: schemas.Category | None = None,
            q: Annotated[str, Query(max_length=200)] = '', page: Annotated[int, Query(ge=1, le=10000)] = 1,
            page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return service.listing(principal, status, category, q, page, page_size)


@app.get('/api/tickets/{request_id}')
def ticket_detail(request_id: str, principal: Principal):
    return service.detail(principal, request_id)


@app.get('/api/tickets/{request_id}/history')
def ticket_history(request_id: str, principal: Principal):
    return service.history(principal, request_id)


@app.post('/api/tickets/{request_id}/clarification-request')
def request_clarification(request_id: str, data: schemas.Clarification, principal: Principal):
    return service.mutate(principal, request_id, 'clarification', data)


@app.patch('/api/tickets/{request_id}/content')
async def update_content(request_id: str, data: schemas.ContentUpdate, principal: Principal):
    ticket = await asyncio.to_thread(service.mutate, principal, request_id, 'content', data)
    await classify_snapshot(ticket)
    return await asyncio.to_thread(service.detail, principal, request_id)


@app.patch('/api/tickets/{request_id}/category')
def update_category(request_id: str, data: schemas.CategoryUpdate, principal: Principal):
    return service.mutate(principal, request_id, 'category', data)


@app.patch('/api/tickets/{request_id}/status')
def update_status(request_id: str, data: schemas.StatusUpdate, principal: Principal):
    return service.mutate(principal, request_id, 'status', data)
