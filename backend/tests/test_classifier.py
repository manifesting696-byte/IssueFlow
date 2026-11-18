import asyncio
import json
import pytest
import httpx
from app import classifier
from app.classifier import classify, redact, rule_classify
from app.config import settings


@pytest.mark.parametrize('text,category', [
    ('今天系统登录页面一直转圈，我进不去。', 'system_fault'),
    ('帮我申请一下项目资料的查看权限，现在提示无权限。', 'permission_request'),
    ('希望查询页面能保存上次的筛选条件，每次都得重新选。', 'feature_suggestion'),
    ('点击导出后没有文件，试了两次都不行。', 'system_fault'),
    ('请问怎么重置自己的登录密码？', 'usage_consultation'),
    ('系统特别慢，今天工作都受影响了。', 'system_fault'),
    ('想加个报表功能，最好下周能用。', 'feature_suggestion'),
])
def test_sample_rules(text, category):
    result = rule_classify(text)
    assert result.category == category and result.detail['evidence'] in text


@pytest.mark.parametrize('text', ['那个先不用了。', '不是登录失败，只是问怎么使用', '申请权限，同时登录失败', '我不想申请权限', '已经有权限，但是系统仍然提示无权限'])
def test_conservative_rules(text):
    assert rule_classify(text) is None


async def test_T12_no_key():
    result = await classify('那个先不用了。')
    assert (result.category, result.source) == ('uncertain', 'fallback')


@pytest.mark.parametrize('mode', ['timeout', 'invalid_json', 'bad_category', 'fake_evidence', 'missing_evidence', 'http_error'])
async def test_T12_provider_failure(monkeypatch, mode):
    monkeypatch.setenv('LLM_ENABLED', 'true')
    monkeypatch.setenv('LLM_API_KEY', 'test-only-not-a-real-key')
    monkeypatch.setenv('LLM_TIMEOUT_SECONDS', '0.05')
    settings.cache_clear()
    real_client = httpx.AsyncClient
    async def handler(request):
        if mode == 'timeout':
            await asyncio.sleep(3)
        if mode == 'http_error':
            return httpx.Response(503)
        output = {'category': 'system_fault', 'evidence': '登录一直出错', 'reason': '存在异常'}
        if mode == 'bad_category': output['category'] = 'invented'
        if mode == 'fake_evidence': output['evidence'] = '原文没有这句话'
        if mode == 'missing_evidence': output['evidence'] = ''
        return httpx.Response(200, json={'choices': [{'message': {'content': 'not json' if mode == 'invalid_json' else json.dumps(output)}}]})
    monkeypatch.setattr(classifier.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        result = await classify('登录一直出错')
        assert (result.category, result.source) == ('uncertain', 'fallback')
    finally:
        settings.cache_clear()


async def test_model_can_respond_after_old_two_second_deadline(monkeypatch):
    monkeypatch.setenv('LLM_ENABLED', 'true')
    monkeypatch.setenv('LLM_API_KEY', 'test-only')
    monkeypatch.setenv('LLM_TIMEOUT_SECONDS', '60')
    settings.cache_clear()
    real_client = httpx.AsyncClient
    async def handler(request):
        await asyncio.sleep(2.1)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'category': 'system_fault', 'evidence': '登录一直出错', 'reason': '登录行为异常'})}}]})
    def client(**kwargs):
        assert kwargs['timeout'].read == 60
        assert kwargs['timeout'].connect == 10
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(classifier.httpx, 'AsyncClient', client)
    try:
        result = await classify('登录一直出错')
        assert result.source == 'llm' and result.category == 'system_fault'
    finally:
        settings.cache_clear()


async def test_valid_model_output_and_redaction(monkeypatch):
    monkeypatch.setenv('LLM_ENABLED', 'true')
    monkeypatch.setenv('LLM_API_KEY', 'test-only')
    settings.cache_clear()
    real_client = httpx.AsyncClient
    async def handler(request):
        body = json.loads(request.content)
        sent = body['messages'][1]['content']
        assert '13912345678' not in sent and 'a@company.com' not in sent and 'abcsecret' not in sent
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'category': 'system_fault', 'evidence': '登录一直出错', 'reason': '登录行为异常'})}}]})
    monkeypatch.setattr(classifier.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    try:
        result = await classify('登录一直出错 13912345678 a@company.com 密码:abcsecret')
        assert result.source == 'llm' and result.category == 'system_fault'
    finally:
        settings.cache_clear()
