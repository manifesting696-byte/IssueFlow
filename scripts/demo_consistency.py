"""Recording-friendly live concurrency and transaction demo, using real PostgreSQL.

Run through demo-consistency.ps1. Fault injection exists only in this process;
the running API receives no fault switches and no database triggers are changed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime
import json
import threading
import time
import uuid
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import event as sqlalchemy_event

from app import service
from app.config import settings
from app.models import Event
from app.schemas import StatusUpdate

RESULT_MARKER = '@@ISSUEFLOW_DEMO_RESULT@@'
BASE_URL = 'http://127.0.0.1:8000'
ORIGIN = 'http://localhost:3000'
STATUS_NAMES = {'pending': '待处理', 'in_progress': '处理中', 'completed': '已完成'}


class DemoFailure(Exception):
    pass


class AuditFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise DemoFailure(message)


def api(client, method, path, *, expected=200, body=None):
    headers = {'Origin': ORIGIN}
    if method not in ('GET', 'HEAD'):
        headers['X-CSRF-Token'] = client.cookies.get('issueflow_csrf', '')
    response = client.request(method, '/api' + path, headers=headers, json=body)
    require(response.status_code == expected,
            f'{method} {path} 返回 HTTP {response.status_code}，预期为 {expected}')
    return response.json()


def login(stack, username):
    client = stack.enter_context(httpx.Client(base_url=BASE_URL, timeout=20))
    api(client, 'GET', '/auth/csrf')
    user = api(client, 'POST', '/auth/login', body={
        'username': username, 'password': settings().demo_password.get_secret_value()})
    return client, user


def stage(title, pace):
    print('\n' + '=' * 64, flush=True)
    print(title, flush=True)
    print('=' * 64, flush=True)
    if pace:
        time.sleep(pace)


def brief(ticket):
    return {'status': ticket['status'], 'version': ticket['version'],
            'updated_at': ticket['updated_at']}


def describe(ticket):
    return f"状态={STATUS_NAMES[ticket['status']]}，version={ticket['version']}"


def show_history(history, names):
    labels = {'ticket_created': '创建工单', 'ticket_classified': '自动分类',
              'status_changed': '状态变更'}
    for item in history['events']:
        actor = '系统' if item['actor_id'] is None else names.get(item['actor_id'], f"用户 #{item['actor_id']}")
        timestamp = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai'))
        description = labels.get(item['event_type'], item['event_type'])
        if item['event_type'] == 'status_changed':
            description += '：' + STATUS_NAMES[item['detail']['old_status']] + ' → ' + STATUS_NAMES[item['detail']['new_status']]
        print(f"  {timestamp:%H:%M:%S} | {actor} | {description}", flush=True)


def run(pace):
    run_id = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    race_id, rollback_id = 'DEMO-RACE-' + run_id, 'DEMO-TX-' + run_id
    print('IssueFlow：操作历史与并发控制 · 一键演示', flush=True)
    print('真实 API + 真实 PostgreSQL；每轮新建两张虚构工单。', flush=True)
    with ExitStack() as stack:
        employee, employee_user = login(stack, 'xiaozhou')
        operator_a, user_a = login(stack, 'support')
        operator_b, user_b = login(stack, 'support2')
        names = {u['id']: f"{u['display_name']}（{u['username']}）"
                 for u in (employee_user, user_a, user_b)}
        content = '登录失败，刷新后仍然无法进入工作台。'

        stage('场景一：两位操作员基于同一版本，同时修改一张工单', pace)
        created = api(employee, 'POST', '/tickets', expected=201,
                      body={'request_id': race_id, 'content': content})
        require(created['classification_source'] == 'rule', '演示反馈未按规则完成分类')
        first = api(operator_a, 'GET', '/tickets/' + race_id)
        second = api(operator_b, 'GET', '/tickets/' + race_id)
        require(first['version'] == second['version'], '两位操作员读取到的版本不一致')
        version = first['version']
        print(f'工单：{race_id}\n创建者：{names[employee_user["id"]]}', flush=True)
        print(f'操作前：{describe(first)}', flush=True)
        print(f'A = {names[user_a["id"]]}，读取 version={version}', flush=True)
        print(f'B = {names[user_b["id"]]}，读取 version={version}', flush=True)
        print('两人均提交：status=in_progress，expected_version=' + str(version), flush=True)
        barrier = threading.Barrier(2)

        def change(client, user):
            barrier.wait(timeout=10)
            response = client.patch('/api/tickets/' + race_id + '/status', headers={
                'Origin': ORIGIN, 'X-CSRF-Token': client.cookies['issueflow_csrf']},
                json={'status': 'in_progress', 'expected_version': version})
            data = response.json()
            return {'username': user['username'], 'actor_id': user['id'],
                    'http_status': response.status_code, 'code': data.get('code'),
                    'version': data.get('version')}

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(change, operator_a, user_a), pool.submit(change, operator_b, user_b)]
            results = [future.result(timeout=30) for future in futures]
        for result in results:
            suffix = f"新版本={result['version']}" if result['http_status'] == 200 else str(result['code'])
            print(f"  {result['username']:<9} → HTTP {result['http_status']} | {suffix}", flush=True)
        require(sorted(row['http_status'] for row in results) == [200, 409], '未得到一方成功、一方冲突的结果')
        loser = next(row for row in results if row['http_status'] == 409)
        winner = next(row for row in results if row['http_status'] == 200)
        require(loser['code'] == 'TICKET_VERSION_CONFLICT', '失败原因不是版本冲突')
        after = api(operator_a, 'GET', '/tickets/' + race_id)
        history = api(operator_a, 'GET', '/tickets/' + race_id + '/history')
        changes = [e for e in history['events'] if e['event_type'] == 'status_changed']
        require(after['status'] == 'in_progress' and after['version'] == version + 1,
                '最终状态或版本不符合预期')
        require(len(changes) == 1 and changes[0]['actor_id'] == winner['actor_id'],
                '成功操作与历史记录不一致')
        print(f'操作后：{describe(after)}；状态变更事件仅 {len(changes)} 条。', flush=True)
        print('[PASS] 只有成功操作写入状态与历史，冲突请求没有覆盖数据。', flush=True)
        show_history(history, names)

        stage('场景二：模拟历史写入失败，检查状态与版本是否一起回滚', pace)
        tx = api(employee, 'POST', '/tickets', expected=201,
                 body={'request_id': rollback_id, 'content': content})
        before_history = api(operator_a, 'GET', '/tickets/' + rollback_id + '/history')
        print(f'工单：{rollback_id}', flush=True)
        print(f'故障前：{describe(tx)}；历史记录 {len(before_history["events"])} 条。', flush=True)
        print('在独立演示进程中调用同一个业务服务，模拟 status_changed 写入异常。', flush=True)
        print('故障注入只作用于本次进程，不修改运行中 API 或数据库触发器。', flush=True)

        def fail_audit(mapper, connection, target):
            if target.ticket_id == tx['id'] and target.event_type == 'status_changed':
                raise AuditFailure('controlled demo audit failure')

        failed_as_expected = False
        sqlalchemy_event.listen(Event, 'before_insert', fail_audit)
        try:
            service.mutate(service.Principal(user_a['id'], user_a['role']), rollback_id, 'status',
                           StatusUpdate(status='in_progress', expected_version=tx['version']))
        except AuditFailure:
            failed_as_expected = True
            print('已触发预设的历史写入异常；业务事务正在回滚。', flush=True)
        finally:
            sqlalchemy_event.remove(Event, 'before_insert', fail_audit)
        require(failed_as_expected, '预设审计故障未触发')
        rolled_back = api(operator_a, 'GET', '/tickets/' + rollback_id)
        rolled_history = api(operator_a, 'GET', '/tickets/' + rollback_id + '/history')
        require(brief(rolled_back) == brief(tx), '状态、版本或更新时间没有完整回滚')
        require(rolled_history == before_history, '失败操作意外留下了业务事件或修订')
        print(f'故障后：{describe(rolled_back)}；历史记录仍为 {len(rolled_history["events"])} 条。', flush=True)
        print('[PASS] 状态未改变，版本未增加，更新时间未改变，也没有新增状态事件。', flush=True)

        stage('场景三：故障解除后正常重试，同时保存状态与历史', pace)
        retried = api(operator_a, 'PATCH', '/tickets/' + rollback_id + '/status', body={
            'status': 'in_progress', 'expected_version': rolled_back['version']})
        retry_history = api(operator_a, 'GET', '/tickets/' + rollback_id + '/history')
        retry_changes = [e for e in retry_history['events'] if e['event_type'] == 'status_changed']
        require(retried['status'] == 'in_progress' and retried['version'] == tx['version'] + 1,
                '正常重试的状态或版本错误')
        require(len(retry_changes) == 1 and retry_changes[0]['actor_id'] == user_a['id'],
                '正常重试没有对应且唯一的历史记录')
        print(f'正常重试：HTTP 200；{describe(retried)}；状态事件 {len(retry_changes)} 条。', flush=True)
        show_history(retry_history, names)
        print('[PASS] 状态与操作历史一起提交，故障注入已移除。', flush=True)
        report = {
            'timestamp': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'passed': True,
            'concurrency': {'request_id': race_id, 'before': brief(first), 'results': results,
                            'after': brief(after), 'status_events': len(changes)},
            'rollback': {'request_id': rollback_id, 'before': brief(tx),
                         'after_injected_failure': brief(rolled_back),
                         'history_unchanged': rolled_history == before_history,
                         'retry_http_status': 200, 'after_retry': brief(retried),
                         'status_events_after_retry': len(retry_changes)},
        }
        stage('演示完成：3 个场景全部通过', pace)
        print('录屏讲解：同版本竞争只成功一次；历史失败则一起回滚；正常重试状态与历史一起保存。', flush=True)
        print('打开 http://localhost:3000，用 support 登录，搜索以下编号查看真实时间线：', flush=True)
        print('  ' + race_id + '\n  ' + rollback_id, flush=True)
        print('这两张演示工单保留，可再次运行生成新编号，不清空已有数据。', flush=True)
        print(RESULT_MARKER + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pace', type=float, default=2)
    args = parser.parse_args()
    if not 0 <= args.pace <= 10:
        parser.error('--pace must be between 0 and 10')
    try:
        run(args.pace)
    except DemoFailure as error:
        print('\n[FAIL] ' + str(error), flush=True)
        raise SystemExit(1)
    except Exception as error:
        print('\n[FAIL] 演示未完成，错误类型：' + type(error).__name__ + '；请确认服务和演示账号可用。', flush=True)
        raise SystemExit(1)
