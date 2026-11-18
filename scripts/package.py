"""Package source and reviewable evidence; exclude credentials and local runtimes."""
from pathlib import Path
import hashlib
import os
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {'.venv', 'node_modules', '.next', '.git', '__pycache__', '.pytest_cache', 'backups', 'browser', 'test-results'}
EVIDENCE = {'pytest.xml', 'playwright.json', 'promptfoo.json', 'backup-drill.json', 'persistence.json',
            'workspace-desktop.png', 'workspace-mobile.png', 'detail-desktop.png', 'video-check.json', 'model-check.json', 'timeout-update.json', 'creators-desktop.png', 'creators-mobile.png', 'consistency-demo.json'}


def include(path):
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in relative.parts):
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if path.suffix in {'.pyc', '.tsbuildinfo', '.zip', '.dump', '.log'}:
        return False
    if relative.parts[0] == 'artifacts' and path.name not in EVIDENCE:
        return False
    return True


if __name__ == '__main__':
    destination = ROOT / 'deliverables' / 'IssueFlow-source.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for directory, folders, files in os.walk(ROOT):
            folders[:] = sorted(folder for folder in folders if folder not in EXCLUDE_DIRS)
            for filename in sorted(files):
                path = Path(directory) / filename
                if include(path):
                    archive.write(path, 'IssueFlow/' + path.relative_to(ROOT).as_posix())
    # Check exact locally configured secrets, without printing them.
    from dotenv import dotenv_values
    config = dotenv_values(ROOT / '.env')
    secrets = [config.get('LLM_API_KEY'), config.get('JWT_SECRET')]
    with zipfile.ZipFile(destination) as archive:
        for item in archive.infolist():
            data = archive.read(item)
            assert all(not secret or secret.encode() not in data for secret in secrets), 'Secret found in package'
    print('Package ready; secret scan passed; SHA256:', hashlib.sha256(destination.read_bytes()).hexdigest())
