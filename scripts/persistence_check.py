"""Record/verify API-visible data across actual API and database restarts."""
import argparse
import hashlib
import json
from pathlib import Path
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def snapshot():
    config = dotenv_values(ROOT / '.env')
    with httpx.Client(base_url='http://127.0.0.1:8010', timeout=15) as client:
        csrf = client.get('/api/auth/csrf').json()['csrf_token']
        response = client.post('/api/auth/login', headers={'X-CSRF-Token': csrf},
                               json={'username': 'support', 'password': config.get('DEMO_PASSWORD', '123456123456zm')})
        response.raise_for_status()
        records = []
        page = 1
        while True:
            response = client.get('/api/tickets', params={'page': page, 'page_size': 100})
            response.raise_for_status()
            batch = response.json()
            for ticket in batch['items']:
                history = client.get('/api/tickets/' + ticket['request_id'] + '/history')
                history.raise_for_status()
                records.append({'ticket': ticket, 'history': history.json()})
            if len(records) >= batch['total']:
                break
            page += 1
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'tickets': len(records), 'events': sum(len(row['history']['events']) for row in records),
            'revisions': sum(len(row['history']['revisions']) for row in records), 'sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['capture', 'verify'])
    args = parser.parse_args()
    path = ROOT / 'artifacts' / 'persistence.json'
    current = snapshot()
    if args.mode == 'capture':
        report = {'before': current}
    else:
        report = json.loads(path.read_text(encoding='utf-8'))
        assert report['before'] == current, 'Data changed across restart'
        report.update(after=current, identical=True, method='actual API process replacement and PostgreSQL container restart')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'mode': args.mode, **current}, ensure_ascii=False))
