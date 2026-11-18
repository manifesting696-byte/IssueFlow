import hashlib
import logging
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Request
from sqlalchemy import select
from .config import settings
from .db import Session
from .errors import BusinessError
from .models import User
from .service import Principal

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))
logger = logging.getLogger('issueflow.security')
_attempts = OrderedDict()
_lock = threading.Lock()


def check_origin(request: Request):
    origin = request.headers.get('origin')
    allowed = {value.strip() for value in settings().allowed_origins.split(',') if value.strip()}
    if origin and origin not in allowed:
        raise BusinessError(403, 'INVALID_ORIGIN', '请求来源不受信任')


def check_csrf(request: Request, expected=None):
    check_origin(request)
    cookie = request.cookies.get('issueflow_csrf', '')
    header = request.headers.get('x-csrf-token', '')
    if not cookie or not secrets.compare_digest(cookie, header) or (expected is not None and not secrets.compare_digest(cookie, expected)):
        raise BusinessError(403, 'CSRF_FAILED', '安全校验失败，请刷新页面')


def authenticate(request: Request) -> Principal:
    try:
        claims = jwt.decode(request.cookies.get('issueflow_session', ''), settings().jwt_secret.get_secret_value(),
                            algorithms=['HS256'], issuer='issueflow', audience='issueflow-web',
                            options={'require': ['sub', 'exp', 'iat', 'csrf']})
        user_id = int(claims['sub'])
    except (jwt.PyJWTError, ValueError, TypeError):
        raise BusinessError(401, 'UNAUTHORIZED', '请先登录')
    with Session() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise BusinessError(401, 'UNAUTHORIZED', '账户不可用，请重新登录')
        principal = Principal(user.id, user.role)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        check_csrf(request, claims['csrf'])
    return principal


def login(request, response, username, password):
    check_csrf(request)
    # Single-process local deployment; use an ingress-wide limiter before scaling workers.
    key = hashlib.sha256(((request.client.host if request.client else 'unknown') + ':' + username).encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        hits = [t for t in _attempts.get(key, []) if now - t < 60]
        if len(hits) >= 10:
            raise BusinessError(429, 'LOGIN_RATE_LIMITED', '登录尝试过多，请稍后再试')
        _attempts[key] = hits + [now]
        _attempts.move_to_end(key)
        if len(_attempts) > 10000:
            _attempts.popitem(last=False)
    with Session() as db:
        user = db.scalar(select(User).where(User.username == username))
        try:
            valid = hasher.verify(user.password_hash if user else DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not user or not valid or not user.is_active:
            logger.warning('login_failed actor=anonymous')
            raise BusinessError(401, 'INVALID_CREDENTIALS', '用户名或密码错误')
        csrf = secrets.token_urlsafe(32)
        current = datetime.now(timezone.utc)
        token = jwt.encode({'sub': str(user.id), 'iat': current, 'exp': current + timedelta(minutes=30),
                            'iss': 'issueflow', 'aud': 'issueflow-web', 'csrf': csrf},
                           settings().jwt_secret.get_secret_value(), algorithm='HS256')
        response.set_cookie('issueflow_session', token, httponly=True, secure=settings().cookie_secure, samesite='strict', max_age=1800, path='/')
        response.set_cookie('issueflow_csrf', csrf, httponly=False, secure=settings().cookie_secure, samesite='strict', max_age=1800, path='/')
        logger.info('login_success actor_id=%s', user.id)
        return {'id': user.id, 'username': user.username, 'display_name': user.display_name, 'role': user.role}
