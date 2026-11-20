"""Exercise the real HTTP serializer against a controlled transport, without keys."""
import asyncio
import json

import httpx
import pytest

from app.workbench.ai import OpenAIDesigner, OpenAICompatibleDesigner, configured_designer


def transport(monkeypatch, payload):
    requests = []
    real_client = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs))
    return requests


def test_responses_sends_images_and_parses_message_after_reasoning(monkeypatch):
    requests = transport(monkeypatch, {'status': 'completed', 'output': [
        {'type': 'reasoning', 'summary': []}, {'type': 'message', 'content': [
            {'type': 'output_text', 'text': '{"summary":"A candidate","patch":{}}'}]}]})
    provider = OpenAIDesigner('https://api.openai.com/v1', 'test-only', 'test-model', name='openai')
    result = asyncio.run(provider.generate([
        {'type': 'text', 'text': 'Read this chair'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]))
    body = json.loads(requests[0].content)
    assert str(requests[0].url).endswith('/v1/responses')
    assert body['store'] is False
    assert body['text']['format']['type'] == 'json_object'
    assert body['input'][1]['content'][1]['type'] == 'input_image'
    assert body['input'][1]['content'][1]['image_url'].startswith('data:image/')
    assert result == {'summary': 'A candidate', 'patch': {}}


@pytest.mark.parametrize('payload', [
    {'status': 'incomplete', 'output': []},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]},
    {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '[]'}]}]},
])
def test_incomplete_refused_or_non_object_responses_cannot_be_candidates(monkeypatch, payload):
    transport(monkeypatch, payload)
    with pytest.raises(ValueError):
        asyncio.run(OpenAIDesigner('https://api.openai.com/v1', 'test-only', 'test').generate([]))


def test_provider_configuration_selects_vendor_transport(monkeypatch):
    for name, value in {'BASE_URL': 'https://api.openai.com/v1', 'MODEL': 'test', 'API_KEY': 'test-only', 'PROVIDER': 'openai'}.items():
        monkeypatch.setenv('CREATE_JUNIOR_AI_' + name, value)
    assert isinstance(configured_designer(), OpenAIDesigner)
    monkeypatch.setenv('CREATE_JUNIOR_AI_PROVIDER', 'openai_compatible')
    assert type(configured_designer()) is OpenAICompatibleDesigner
