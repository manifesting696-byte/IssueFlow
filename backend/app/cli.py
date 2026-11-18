import argparse
import asyncio
from sqlalchemy import select
from .auth import hasher
from .classifier import classify
from .config import settings
from .db import Session
from .models import User, Ticket
from .service import Principal, create, apply_classification, recover_pending

DEMO_USERS = [
    ('xiaoli', '小李', 'employee'),
    ('xiaozhou', '小周', 'employee'),
    ('xiaochen', '小陈', 'employee'),
    ('support', '小林', 'support'),
    ('support2', '小吴', 'support'),
]

SAMPLES = [
    ('R001', 'xiaoli', '今天系统登录页面一直转圈，我进不去。'),
    ('R002', 'xiaozhou', '帮我申请一下项目资料的查看权限，现在提示无权限。'),
    ('R003', 'xiaochen', '希望查询页面能保存上次的筛选条件，每次都得重新选。'),
    ('R004', 'xiaoli', '点击导出后没有文件，试了两次都不行。'),
    ('R005', 'xiaozhou', '请问怎么重置自己的登录密码？'),
    ('R006', 'xiaochen', '系统特别慢，今天工作都受影响了。'),
    ('R007', 'xiaozhou', '想加个报表功能，最好下周能用。'),
    ('R008', 'xiaochen', '那个先不用了。'),
    ('DEMO-ZHOU-01', 'xiaozhou', '请开通项目资料库的查看权限。'),
    ('DEMO-ZHOU-02', 'xiaozhou', '导出失败，页面提示生成文件异常。'),
    ('DEMO-ZHOU-03', 'xiaozhou', '希望查询页面能保存常用筛选条件。'),
    ('DEMO-CHEN-01', 'xiaochen', '页面卡死，刷新后仍无法查看报表。'),
    ('DEMO-CHEN-02', 'xiaochen', '请问怎么重置系统登录密码？'),
    ('DEMO-CHEN-03', 'xiaochen', '建议增加报表导出的进度提示。'),
    ('DEMO-SUPPORT-01', 'support', '系统卡顿，打开工单详情需要等待很久。'),
    ('DEMO-SUPPORT-02', 'support', '希望支持按工单分类导出统计结果。'),
    ('DEMO-SUPPORT2-01', 'support2', '申请项目资料库的查看权限，用于排查反馈问题。'),
    ('DEMO-SUPPORT2-02', 'support2', '如何操作才能查看历史工单？'),
]


def ensure_demo_users(db):
    for username, display, role in DEMO_USERS:
        if not db.scalar(select(User).where(User.username == username)):
            db.add(User(username=username, display_name=display,
                        password_hash=hasher.hash(settings().demo_password.get_secret_value()), role=role))


def configure_demo():
    """Explicit local demo reset; preserve user IDs, ticket ownership and audit."""
    roles = {username: role for username, _, role in DEMO_USERS}
    with Session.begin() as db:
        ensure_demo_users(db)
        db.flush()
        for user in db.scalars(select(User)):
            user.password_hash = hasher.hash(settings().demo_password.get_secret_value())
            user.is_active = user.username in roles
            if user.is_active:
                user.role = roles[user.username]
    print('Demo accounts configured: 3 active employees and 2 active support users; history preserved.')


async def seed():
    with Session.begin() as db:
        ensure_demo_users(db)
    for request_id, username, content in SAMPLES:
        with Session() as db:
            # Existing demo tickets keep their original submitter, even when the
            # set of active demo accounts changes between versions.
            if db.scalar(select(Ticket.id).where(Ticket.request_id == request_id)) is not None:
                continue
            user = db.scalar(select(User).where(User.username == username))
        snapshot, created = create(Principal(user.id, user.role), request_id, content)
        if created:
            apply_classification(snapshot, await classify(content))
    print('Demo users and sample tickets are ready (existing data preserved).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['seed', 'recover', 'configure-demo'])
    args = parser.parse_args()
    if args.command == 'seed':
        asyncio.run(seed())
    elif args.command == 'configure-demo':
        configure_demo()
    else:
        print('Recovered:', recover_pending())
