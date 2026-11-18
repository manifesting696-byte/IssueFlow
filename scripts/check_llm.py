"""Optional live DeepSeek smoke through the actual web proxy and persisted audit."""
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import uuid

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def check():
    config = dotenv_values(ROOT / '.env')
    content = '业务窗口打开后显示 E403，无法继续操作。'
    request_id = 'LIVE-' + uuid.uuid4().hex
    with httpx.Client(base_url='http://localhost:3000', timeout=75) as client:
        csrf = client.get('/api/auth/csrf').json()['csrf_token']
        response = client.post('/api/auth/login', headers={'X-CSRF-Token': csrf}, json={
            'username': 'support', 'password': config.get('DEMO_PASSWORD', '123456123456zm')})
        response.raise_for_status()
        before = client.get('/api/tickets').json()['total']
        start = time.monotonic()
        response = client.post('/api/tickets', headers={'X-CSRF-Token': client.cookies['issueflow_csrf']},
                               json={'request_id': request_id, 'content': content})
        response.raise_for_status()
        elapsed = round(time.monotonic() - start, 2)
        ticket = response.json()
        history = client.get('/api/tickets/' + request_id + '/history')
        history.raise_for_status()
    classified = [row for row in history.json()['events']
                  if row['event_type'] == 'ticket_classified' and row['detail'].get('source') == 'llm']
    valid = (response.status_code == 201 and ticket['classification_source'] == 'llm' and
             bool(classified) and classified[-1]['detail'].get('evidence', '') in content and
             classified[-1]['detail'].get('model') == config.get('LLM_MODEL', 'deepseek-flash'))
    report = {'timestamp_local': datetime.now().astimezone().isoformat(), 'provider': 'DeepSeek',
              'configured_model': config.get('LLM_MODEL', 'deepseek-flash'), 'request_id': request_id,
              'budget_seconds': float(config.get('LLM_TIMEOUT_SECONDS', 60)), 'elapsed_seconds': elapsed,
              'http_status': response.status_code, 'classification_source': ticket['classification_source'],
              'category': ticket['category'], 'through_frontend_proxy': True,
              'persisted_llm_event_verified': valid, 'total_ticket_count_before': before,
              'note': 'Real provider request; this single case is not an accuracy evaluation.'}
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    (ROOT / 'artifacts' / 'model-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return valid


if __name__ == '__main__':
    sys.exit(0 if check() else 1)
