"""厂商模型目录探测：设置页「获取模型列表」的后端代理。

只做一次只读 GET，不落库、不写日志（避免泄露 api_key）。
支持的 provider 与 ModelProvider 一致：openai_compatible / gemini / anthropic。
"""

import requests

GEMINI_MODELS_URL = 'https://generativelanguage.googleapis.com/v1beta/models'
ANTHROPIC_DEFAULT_BASE_URL = 'https://api.anthropic.com'
ANTHROPIC_API_VERSION = '2023-06-01'
OPENAI_DEFAULT_BASE_URL = 'https://api.openai.com/v1'

PROBE_TIMEOUT_SECONDS = 15
MAX_MODELS = 300


def _normalize_openai_base_url(base_url):
    normalized = (base_url or OPENAI_DEFAULT_BASE_URL).strip().rstrip('/')
    if normalized.endswith('/chat/completions'):
        normalized = normalized[: -len('/chat/completions')]
    return normalized


def _normalize_anthropic_base_url(base_url):
    normalized = (base_url or ANTHROPIC_DEFAULT_BASE_URL).strip().rstrip('/')
    if normalized.endswith('/v1'):
        normalized = normalized[:-3]
    return normalized


def _probe_openai_compatible(base_url, api_key):
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    response = requests.get(
        f"{_normalize_openai_base_url(base_url)}/models",
        headers=headers,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    models = []
    for item in response.json().get('data') or []:
        model_id = item.get('id') if isinstance(item, dict) else None
        if model_id:
            models.append(model_id)
    return sorted(set(models))[:MAX_MODELS]


def _probe_gemini(api_key):
    if not api_key:
        raise ValueError('A Gemini API key is required to list models')

    response = requests.get(
        GEMINI_MODELS_URL,
        params={'key': api_key, 'pageSize': MAX_MODELS},
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    models = []
    for item in response.json().get('models') or []:
        name = (item.get('name') or '').removeprefix('models/')
        methods = item.get('supportedGenerationMethods') or []
        if name and 'generateContent' in methods:
            models.append(name)
    return sorted(set(models))[:MAX_MODELS]


def _probe_anthropic(base_url, api_key):
    if not api_key:
        raise ValueError('An Anthropic API key is required to list models')

    response = requests.get(
        f"{_normalize_anthropic_base_url(base_url)}/v1/models",
        headers={
            'x-api-key': api_key,
            'anthropic-version': ANTHROPIC_API_VERSION,
        },
        params={'limit': MAX_MODELS},
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    models = []
    for item in response.json().get('data') or []:
        model_id = item.get('id') if isinstance(item, dict) else None
        if model_id:
            models.append(model_id)
    return sorted(set(models))[:MAX_MODELS]


def probe_provider_models(provider, base_url='', api_key=''):
    provider = (provider or '').strip().lower()

    if provider == 'openai_compatible':
        return _probe_openai_compatible(base_url, api_key)
    if provider == 'gemini':
        return _probe_gemini(api_key)
    if provider == 'anthropic':
        return _probe_anthropic(base_url, api_key)

    raise ValueError(f'Unsupported provider for model probing: {provider or "(empty)"}')
