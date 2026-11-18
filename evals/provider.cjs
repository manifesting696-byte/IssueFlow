const { spawnSync } = require('node:child_process');
const path = require('node:path');
module.exports = class IssueFlowClassifier {
  id() { return 'issueflow-classifier'; }
  async callApi(prompt) {
    const root = path.resolve(__dirname, '..');
    const python = process.env.EVAL_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    const result = spawnSync(python, [path.join(root, 'evals/classify.py')], {
      input: prompt, encoding: 'utf8', cwd: path.join(root, 'backend'),
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1', LLM_ENABLED: process.env.EVAL_LIVE === 'true' ? 'true' : 'false' }, timeout: 150000,
    });
    if (result.status !== 0) return { error: 'Classifier process failed; inspect local environment.' };
    return { output: result.stdout.trim() };
  }
};
