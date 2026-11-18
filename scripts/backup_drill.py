"""Create a real dump; restore into a newly created isolated DB; compare all rows."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'backups'
TABLES = ('users', 'tickets', 'ticket_revisions', 'ticket_events')


def docker(*args, input=None):
    return subprocess.run(['docker', 'compose', 'exec', '-T', 'db', *args], cwd=ROOT,
                          input=input, capture_output=True, check=True).stdout


def snapshot(database):
    result = {}
    for table in TABLES:
        raw = docker('psql', '-U', 'issueflow', '-d', database, '-At', '-c',
                     f"SELECT coalesce(json_agg(t ORDER BY id),'[]'::json) FROM {table} t")
        rows = json.loads(raw)
        result[table] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}
    return result


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    database = 'issueflow_restore_' + stamp
    before = snapshot('issueflow')
    dump = docker('pg_dump', '-U', 'issueflow', '-d', 'issueflow', '--format=custom')
    path = OUT / (stamp + '.dump')
    path.write_bytes(dump)
    # createdb fails if the name exists; never overwrite any existing database.
    docker('createdb', '-U', 'issueflow', database)
    docker('pg_restore', '-U', 'issueflow', '-d', database, '--exit-on-error', input=dump)
    after = snapshot(database)
    assert before == after, 'Backup/restore row comparison failed'
    report = {'timestamp_local': datetime.now().astimezone().isoformat(), 'dump': str(path),
              'restored_database': database, 'tables': after, 'identical': True}
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    (ROOT / 'artifacts' / 'backup-drill.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'identical': True, 'row_counts': {t: after[t]['count'] for t in TABLES}, 'restored_database': database}))
