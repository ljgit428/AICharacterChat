import base64
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import google.generativeai as genai
import requests
from celery import shared_task

from django.db import transaction

from .attachments import describe_attachment_for_prompt, get_message_attachments
from .memory.manager import MemoryManager
from .memory.prompts import build_memory_extraction_prompt, get_memory_crud_tool_specs
from .models import AttachmentKind, Character, CharacterMemoryItem, ChatSession, Message, ModelConfiguration, UserProfile
from .search import search_web
from .soul import (
    build_character_prompt_context,
    build_memory_explorer_manifest,
    list_memory_explorer_path,
    read_memory_explorer_file,
)

logger = logging.getLogger(__name__)

OPENAI_IMAGE_VIDEO_MODEL_FAMILIES = (
    'qwen3.6-plus',
    'qwen3.5-plus',
    'qwen3.5-flash',
    'qwen3-vl',
    'qwen2.5-vl',
    'qwen-vl-max',
    'qwen-vl-plus',
)

OPENAI_IMAGE_ONLY_MODEL_FAMILIES = (
    'gpt-4o',
    'gpt-4.1',
    'o4-mini',
    'o3',
    'qwen-vl-ocr',
)

OPENAI_IMAGE_ONLY_MODEL_HINTS = (
    'vision',
    'llava',
    'minicpm-v',
    'internvl',
)

OPENAI_VIDEO_FRAME_FPS = 2.0
CHARACTER_REFERENCE_IMAGE_LIMIT = 4
OPENAI_LOCAL_TOOL_CALL_LIMIT = 6
MEMORY_TOOL_DEFAULT_MAX_CHARS = 6000
STREAM_MEMORY_SECTION_LIMIT = 900
LONG_TERM_MEMORY_DESC_LIMIT = 200
LONG_TERM_MEMORY_SECTION_LIMIT = 64
LONG_TERM_MEMORY_TOOL_ROUND_TRIP_LIMIT = 8


LOCAL_SEARCH_KEYWORDS = (
    'nearby',
    'local',
    'around me',
    'weather',
    'forecast',
    'temperature',
    'restaurant',
    'cafe',
    'coffee',
    'park',
    'museum',
    'bar',
    'store',
    'shop',
    '附近',
    '周边',
    '本地',
    '当地',
    '天气',
    '气温',
    '温度',
    '餐厅',
    '咖啡',
    '咖啡馆',
    '公园',
    '博物馆',
    '商店',
)

WEATHER_QUERY_KEYWORDS = (
    'weather',
    'forecast',
    'temperature',
    'rain',
    'snow',
    'sunny',
    'cloudy',
    'storm',
    'humidity',
    'weather like',
    '天气',
    '气温',
    '温度',
    '下雨',
    '下雪',
    '晴',
    '阴',
    '暴雨',
    '湿度',
)

TODAY_QUERY_KEYWORDS = (
    'today',
    'tonight',
    'this morning',
    'this afternoon',
    'this evening',
    '今天',
    '今晚',
    '今早',
    '今天早上',
    '今天下午',
    '今天晚上',
)

TOMORROW_QUERY_KEYWORDS = (
    'tomorrow',
    'tomorrow morning',
    'tomorrow night',
    '明天',
    '明早',
    '明天早上',
    '明晚',
    '明天晚上',
)

YESTERDAY_QUERY_KEYWORDS = (
    'yesterday',
    '昨晚',
    '昨天',
)


def _get_runtime_model_config(chat_session):
    model_config = ModelConfiguration.get_default_for_user(chat_session.user)
    if not model_config:
        raise ValueError('No user model configuration is available for this chat session')

    return {
        'provider': model_config.provider,
        'model_name': model_config.model_name,
        'api_key': model_config.api_key,
        'base_url': model_config.base_url,
    }


def _build_openai_endpoint(base_url):
    normalized_base_url = (base_url or 'https://api.openai.com/v1').rstrip('/')
    if normalized_base_url.endswith('/chat/completions'):
        return normalized_base_url
    return f"{normalized_base_url}/chat/completions"


def _normalize_model_name(value):
    return (value or '').strip().lower()


def _matches_model_family(model_name, families):
    normalized = _normalize_model_name(model_name)
    return any(
        normalized == family or normalized.startswith(f'{family}-')
        for family in families
    )


def _get_model_capabilities(runtime_config):
    provider = runtime_config['provider']
    model_name = runtime_config['model_name']

    capabilities = {
        'text': True,
        'image': False,
        'video': False,
    }

    if provider == 'gemini':
        capabilities['image'] = True
        capabilities['video'] = True
    elif provider == 'openai_compatible':
        normalized_model_name = _normalize_model_name(model_name)
        if _matches_model_family(normalized_model_name, OPENAI_IMAGE_VIDEO_MODEL_FAMILIES):
            capabilities['image'] = True
            capabilities['video'] = True
        elif (
            _matches_model_family(normalized_model_name, OPENAI_IMAGE_ONLY_MODEL_FAMILIES)
            or any(hint in normalized_model_name for hint in OPENAI_IMAGE_ONLY_MODEL_HINTS)
        ):
            capabilities['image'] = True

    return capabilities


def _supports_memory_tool_mode(runtime_config):
    return runtime_config['provider'] == 'openai_compatible'


def _build_memory_tool_specs():
    return [
        {
            'type': 'function',
            'function': {
                'name': 'list_memory_files',
                'description': (
                    'Browse the character memory filesystem. Use it like a folder explorer '
                    'before reading any specific long-term memory file.'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path_prefix': {
                            'type': 'string',
                            'description': 'Optional directory path such as schema, wiki, raw, raw/chat_sessions, or raw/character_setup.',
                        },
                        'recursive': {
                            'type': 'boolean',
                            'description': 'Set true to list all descendants under the selected path.',
                        },
                        'max_entries': {
                            'type': 'integer',
                            'description': 'Maximum number of entries to return, between 1 and 200.',
                        },
                    },
                    'required': [],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'read_memory_file',
                'description': (
                    'Read one file from the character memory filesystem after locating it. '
                    'Use the exact path returned by list_memory_files or shown in MEMORY FILESYSTEM.'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {
                            'type': 'string',
                            'description': 'Exact memory file path, for example schema/soul.md or raw/chat_sessions/session_12/transcript.md.',
                        },
                        'max_chars': {
                            'type': 'integer',
                            'description': 'Optional character limit between 200 and 12000.',
                        },
                    },
                    'required': ['path'],
                },
            },
        },
    ]


def _extract_text_from_content(content):
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text_parts.append(item.get('text', ''))
        return ''.join(text_parts).strip()

    return ''


def _extract_openai_content(response_json):
    choices = response_json.get('choices') or []
    if not choices:
        raise ValueError('OpenAI compatible API returned no choices')

    message = choices[0].get('message') or {}
    content = _extract_text_from_content(message.get('content'))
    if not content:
        raise ValueError('OpenAI compatible API returned an unsupported message format')
    return content


def _extract_openai_assistant_message(response_json):
    choices = response_json.get('choices') or []
    if not choices:
        raise ValueError('OpenAI compatible API returned no choices')
    return choices[0].get('message') or {}


def _should_retry_without_tools(exc):
    text = str(exc or '').lower()
    if not text:
        return False
    tool_markers = (
        'tool',
        'tools',
        'tool_choice',
        'tool_calls',
        'function calling',
        'function call',
    )
    retry_markers = (
        'unsupported',
        'unknown',
        'invalid',
        'not support',
        'unexpected',
        'extra inputs',
        'unrecognized',
    )
    return any(marker in text for marker in tool_markers) and any(marker in text for marker in retry_markers)


def _build_data_url(path, mime_type):
    with open(path, 'rb') as file_handle:
        encoded = base64.b64encode(file_handle.read()).decode('ascii')
    return f"data:{mime_type or 'application/octet-stream'};base64,{encoded}"


def _upload_generativeai_file(path, display_name, api_key):
    if not api_key:
        raise ValueError('API key is required for the selected model configuration')

    genai.configure(api_key=api_key)
    uploaded_file = genai.upload_file(path=path, display_name=display_name)
    state = getattr(getattr(uploaded_file, 'state', None), 'name', '') or ''

    deadline = time.time() + 120
    while state == 'PROCESSING' and time.time() < deadline:
        time.sleep(2)
        uploaded_file = genai.get_file(uploaded_file.name)
        state = getattr(getattr(uploaded_file, 'state', None), 'name', '') or ''

    if state and state not in {'ACTIVE', 'SUCCEEDED'}:
        raise ValueError(f"Uploaded media is not ready: {state}")

    return uploaded_file


def _build_attachment_prompt_text(message, capabilities, include_text_body=True, include_native_media_summary=True):
    parts = []

    for attachment in get_message_attachments(message):
        attachment_summary = describe_attachment_for_prompt(attachment, allow_text_body=include_text_body)
        if not attachment_summary:
            continue

        attachment_kind = getattr(attachment, 'attachment_kind', '') or ''
        if attachment_kind == AttachmentKind.IMAGE and not capabilities.get('image'):
            parts.append(
                f"{attachment_summary}\n"
                "The current model cannot directly inspect images. Acknowledge the limitation briefly, "
                "then ask the user to describe what matters in the image or switch to an image-capable model."
            )
            continue

        if attachment_kind == AttachmentKind.VIDEO and not capabilities.get('video'):
            parts.append(
                f"{attachment_summary}\n"
                "The current model cannot directly inspect videos. Acknowledge the limitation briefly, "
                "then ask the user for key frames, a summary, or a vision/video-capable model."
            )
            continue

        if attachment_kind in {AttachmentKind.IMAGE, AttachmentKind.VIDEO} and capabilities.get(attachment_kind):
            if include_native_media_summary:
                parts.append(f"{attachment_summary}\nAnalyze the attached media directly before replying.")
            continue

        parts.append(attachment_summary)

    return '\n\n'.join(parts).strip()


def _build_message_text_content(message, capabilities, include_text_body=True, include_native_media_summary=True):
    parts = []
    content = (getattr(message, 'content', '') or '').strip()
    if content:
        parts.append(content)

    attachment_text = _build_attachment_prompt_text(
        message,
        capabilities=capabilities,
        include_text_body=include_text_body,
        include_native_media_summary=include_native_media_summary,
    )
    if attachment_text:
        parts.append(attachment_text)

    return '\n\n'.join(parts).strip()


def _build_openai_compatible_multimodal_content(message, capabilities):
    content_blocks = []
    text_content = _build_message_text_content(
        message,
        capabilities=capabilities,
        include_text_body=False,
        include_native_media_summary=False,
    )
    if text_content:
        content_blocks.append({'type': 'text', 'text': text_content})

    for attachment in get_message_attachments(message):
        attachment_kind = getattr(attachment, 'attachment_kind', '') or ''
        file_obj = getattr(attachment, 'file', None)
        if not file_obj:
            continue

        if attachment_kind == AttachmentKind.IMAGE and capabilities.get('image'):
            content_blocks.append({
                'type': 'image_url',
                'image_url': {
                    'url': _build_data_url(file_obj.path, getattr(attachment, 'attachment_mime_type', '')),
                },
            })
        elif attachment_kind == AttachmentKind.VIDEO and capabilities.get('video'):
            content_blocks.append({
                'type': 'video_url',
                'video_url': {
                    'url': _build_data_url(file_obj.path, getattr(attachment, 'attachment_mime_type', '')),
                },
                'fps': OPENAI_VIDEO_FRAME_FPS,
            })

    return content_blocks


def _get_character_reference_image_assets(character):
    return list(
        character.knowledge_assets.filter(attachment_kind=AttachmentKind.IMAGE)[:CHARACTER_REFERENCE_IMAGE_LIMIT]
    )


def _build_character_reference_message(character, runtime_config, capabilities, prompt_context, use_memory_tools=False):
    reference_sections = [] if use_memory_tools else [
        prompt_context.get("uploaded_index", ""),
        prompt_context.get("uploaded_background", ""),
        prompt_context.get("uploaded_visual_refs", ""),
    ]
    reference_text = "\n\n".join(
        section.strip()
        for section in reference_sections
        if section and section.strip()
    ).strip()

    image_assets = _get_character_reference_image_assets(character)
    if not image_assets or not capabilities.get('image'):
        return None

    if runtime_config['provider'] == 'gemini':
        parts = []
        if reference_text:
            parts.append(reference_text)
        for asset in image_assets:
            parts.append(
                _upload_generativeai_file(
                    asset.file.path,
                    asset.attachment_name or os.path.basename(asset.file.name),
                    runtime_config['api_key'],
                )
            )
        return {'role': 'user', 'parts': parts or ['']}

    if runtime_config['provider'] == 'openai_compatible':
        content = []
        if reference_text:
            content.append({'type': 'text', 'text': reference_text})
        for asset in image_assets:
            content.append({
                'type': 'image_url',
                'image_url': {
                    'url': _build_data_url(asset.file.path, asset.attachment_mime_type),
                },
        })
        return {'role': 'user', 'content': content}

    return None


def _build_provider_message_entry(message, runtime_config, capabilities):
    role = 'assistant' if message.role == 'assistant' else 'user'
    provider = runtime_config['provider']
    attachments = get_message_attachments(message)
    native_media_attachments = [
        attachment
        for attachment in attachments
        if (
            getattr(attachment, 'attachment_kind', '') == AttachmentKind.IMAGE
            and capabilities.get('image')
        ) or (
            getattr(attachment, 'attachment_kind', '') == AttachmentKind.VIDEO
            and capabilities.get('video')
        )
    ]

    if provider == 'gemini':
        parts = []
        text_content = _build_message_text_content(
            message,
            capabilities=capabilities,
            include_text_body=True,
            include_native_media_summary=False,
        )
        if text_content:
            parts.append(text_content)
        for attachment in native_media_attachments:
            parts.append(
                _upload_generativeai_file(
                    attachment.file.path,
                    getattr(attachment, 'attachment_name', '') or os.path.basename(attachment.file.name),
                    runtime_config['api_key'],
                )
            )
        return {
            'role': 'model' if role == 'assistant' else 'user',
            'parts': parts or [''],
        }

    if provider == 'openai_compatible' and native_media_attachments:
        return {
            'role': role,
            'content': _build_openai_compatible_multimodal_content(message, capabilities),
        }

    return {
        'role': role,
        'content': _build_message_text_content(
            message,
            capabilities=capabilities,
            include_text_body=True,
        ),
    }


def _request_openai_compatible_completion(
    *,
    model_name,
    api_key,
    messages,
    base_url,
    tools=None,
):
    # openai_compatible 允许本地反代网关自鉴权：仅有 key 时附加 Authorization header。
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    response = requests.post(
        _build_openai_endpoint(base_url),
        headers=headers,
        json={
            'model': model_name,
            'messages': messages,
            **({'tools': tools, 'tool_choice': 'auto'} if tools else {}),
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def _execute_local_memory_tool(character, tool_name, raw_arguments):
    try:
        arguments = json.loads(raw_arguments or '{}')
    except json.JSONDecodeError:
        arguments = {}

    if tool_name == 'list_memory_files':
        return list_memory_explorer_path(
            character,
            path_prefix=arguments.get('path_prefix', ''),
            recursive=bool(arguments.get('recursive', False)),
            max_entries=arguments.get('max_entries', 40),
        )

    if tool_name == 'read_memory_file':
        return read_memory_explorer_file(
            character,
            path=arguments.get('path', ''),
            max_chars=arguments.get('max_chars', MEMORY_TOOL_DEFAULT_MAX_CHARS),
        )

    return {
        'error': f'Unknown local tool: {tool_name}',
    }


def _generate_openai_compatible_response(model_name, api_key, messages, base_url, tools=None, character=None):
    if not tools:
        return _extract_openai_content(
            _request_openai_compatible_completion(
                model_name=model_name,
                api_key=api_key,
                messages=messages,
                base_url=base_url,
            )
        )

    history = list(messages)
    for _ in range(OPENAI_LOCAL_TOOL_CALL_LIMIT):
        try:
            response_json = _request_openai_compatible_completion(
                model_name=model_name,
                api_key=api_key,
                messages=history,
                base_url=base_url,
                tools=tools,
            )
        except Exception as exc:
            if _should_retry_without_tools(exc):
                logger.warning(
                    "OpenAI-compatible backend rejected local memory tools for model %s; retrying without tools.",
                    model_name,
                )
                return _extract_openai_content(
                    _request_openai_compatible_completion(
                        model_name=model_name,
                        api_key=api_key,
                        messages=messages,
                        base_url=base_url,
                    )
                )
            raise
        assistant_message = _extract_openai_assistant_message(response_json)
        tool_calls = assistant_message.get('tool_calls') or []
        history.append({
            'role': 'assistant',
            'content': assistant_message.get('content'),
            **({'tool_calls': tool_calls} if tool_calls else {}),
        })

        if not tool_calls:
            content = _extract_text_from_content(assistant_message.get('content'))
            if content:
                return content
            raise ValueError('OpenAI compatible API returned an empty response after tool execution')

        if character is None:
            raise ValueError('Local tool execution requires a character context')

        for tool_call in tool_calls:
            function_payload = tool_call.get('function') or {}
            tool_result = _execute_local_memory_tool(
                character,
                tool_name=function_payload.get('name', ''),
                raw_arguments=function_payload.get('arguments', '{}'),
            )
            history.append({
                'role': 'tool',
                'tool_call_id': tool_call.get('id', ''),
                'content': json.dumps(tool_result, ensure_ascii=False),
            })

    raise ValueError('OpenAI compatible API exceeded the local memory tool call limit')


def _stream_openai_compatible_response(model_name, api_key, messages, base_url):
    # openai_compatible 允许本地反代网关自鉴权：仅有 key 时附加 Authorization header。
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    with requests.post(
        _build_openai_endpoint(base_url),
        headers=headers,
        json={
            'model': model_name,
            'messages': messages,
            'stream': True,
        },
        stream=True,
        timeout=90,
    ) as response:
        response.raise_for_status()

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue

            line = raw_line.strip()
            if line.startswith('data:'):
                line = line[5:].strip()

            if line == '[DONE]':
                break

            data = json.loads(line)
            choices = data.get('choices') or []
            if not choices:
                continue

            delta = choices[0].get('delta') or {}
            content = delta.get('content')

            if isinstance(content, str) and content:
                yield content
                continue

            text = _extract_text_from_content(content)
            if text:
                yield text


def _iter_buffered_chunks(text, chunk_size=160):
    normalized = (text or '').strip()
    if not normalized:
        return

    for start_index in range(0, len(normalized), chunk_size):
        yield normalized[start_index:start_index + chunk_size]


def _stream_gemini_response(model_name, api_key, prompt_or_messages, tools=None):
    if not api_key:
        raise ValueError('API key is required for the selected model configuration')

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name, tools=tools if tools else None)
    response = model.generate_content(prompt_or_messages, stream=True)

    for chunk in response:
        text = getattr(chunk, 'text', '')
        if text:
            yield text


def _iter_text_chunks(runtime_config, prompt_or_messages, tools=None, character=None):
    provider = runtime_config['provider']
    model_name = runtime_config['model_name']
    api_key = runtime_config['api_key']

    if provider == 'gemini':
        yield from _stream_gemini_response(model_name, api_key, prompt_or_messages, tools=tools)
        return

    if provider == 'openai_compatible':
        if not isinstance(prompt_or_messages, list):
            prompt_or_messages = [{'role': 'user', 'content': str(prompt_or_messages)}]
        if tools:
            buffered_text = _generate_openai_compatible_response(
                model_name=model_name,
                api_key=api_key,
                messages=prompt_or_messages,
                base_url=runtime_config.get('base_url', ''),
                tools=tools,
                character=character,
            )
            yield from _iter_buffered_chunks(buffered_text)
            return
        yield from _stream_openai_compatible_response(
            model_name=model_name,
            api_key=api_key,
            messages=prompt_or_messages,
            base_url=runtime_config.get('base_url', ''),
        )
        return

    raise ValueError(f"Unsupported model provider: {provider}")


def _generate_text(runtime_config, prompt_or_messages, tools=None, character=None):
    provider = runtime_config['provider']
    model_name = runtime_config['model_name']
    api_key = runtime_config['api_key']

    if provider == 'gemini':
        if not api_key:
            raise ValueError('API key is required for the selected model configuration')

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name, tools=tools if tools else None)
        response = model.generate_content(prompt_or_messages)
        return response.text.strip()

    if provider == 'openai_compatible':
        if not isinstance(prompt_or_messages, list):
            prompt_or_messages = [{'role': 'user', 'content': str(prompt_or_messages)}]
        return _generate_openai_compatible_response(
            model_name=model_name,
            api_key=api_key,
            messages=prompt_or_messages,
            base_url=runtime_config.get('base_url', ''),
            tools=tools,
            character=character,
        )

    raise ValueError(f"Unsupported model provider: {provider}")


def _append_section(sections, title, content):
    normalized = (content or '').strip()
    if normalized:
        sections.append(f"[{title}]\n{normalized}")


def _truncate_text(value, max_length):
    normalized = (value or '').strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + '...'


def _try_parse_json_object(text):
    """Parse text as JSON, returning a dict on success, None otherwise.
    """
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _slice_balanced_json_object(text, start_index):
    """Return the substring from start_index to the matching closing '}'.

    Tracks nested braces and string literals (with backslash escapes) so
    that braces appearing inside JSON strings do not unbalance the scan.
    Returns None if no balanced match is found.
    """
    depth = 0
    in_string = False
    escape = False
    for end_index in range(start_index, len(text)):
        char = text[end_index]
        if escape:
            escape = False
            continue
        if char == '\\' and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return text[start_index:end_index + 1]
    return None


def _extract_json_object(raw_text):
    """Best-effort extraction of a top-level JSON object from a model response.

    Handles: raw JSON, ```` ```json ... ``` ```` and ```` ``` ... ``` ```` fences,
    JSON embedded in surrounding prose, and nested objects. Returns an empty
    dict if no valid JSON object can be recovered.
    """
    text = (raw_text or '').strip()
    if not text:
        return {}

    # 1) Direct parse
    parsed = _try_parse_json_object(text)
    if parsed is not None:
        return parsed

    # 2) Strip a leading/trailing markdown code fence and retry
    if text.startswith('```'):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        stripped = '\n'.join(lines).strip()
        if stripped and stripped != text:
            parsed = _try_parse_json_object(stripped)
            if parsed is not None:
                return parsed
            text = stripped

    # 3) Walk the text looking for balanced {...} regions
    start = text.find('{')
    while start != -1:
        candidate = _slice_balanced_json_object(text, start)
        if candidate is not None:
            parsed = _try_parse_json_object(candidate)
            if parsed is not None:
                return parsed
        start = text.find('{', start + 1)

    # Dump the full raw response to a file so we can see what the model
    # actually sent (the 300-char preview in the log is often not enough
    # to diagnose exotic responses such as a JSON object that ends mid-
    # string, or extra prose wrapping a truncated object). The file lives
    # in the OS temp directory (tempfile.gettempdir()) which is
    # git-ignored; do not commit it. Note: it may echo content from the
    # user's uploaded source files, so treat it as potentially containing
    # PII.
    DUMP_MAX_BYTES = 1_000_000  # cap at 1 MB so a chatty model can't fill the disk
    try:
        dump_path = os.path.join(
            tempfile.gettempdir(),
            f'ai_draft_raw_{int(time.time() * 1_000_000)}.txt',
        )
        raw_for_dump = raw_text or ''
        truncated_for_dump = len(raw_for_dump) > DUMP_MAX_BYTES
        with open(dump_path, 'w', encoding='utf-8', errors='replace') as _dump_file:
            if truncated_for_dump:
                _dump_file.write(raw_for_dump[:DUMP_MAX_BYTES])
                _dump_file.write('\n\n... [truncated for size; full response was '
                                 f'{len(raw_for_dump)} chars] ...\n')
            else:
                _dump_file.write(raw_for_dump)
        logger.info(
            "Failed to extract JSON object from model response (length=%d). "
            "Full raw response written to %s. Preview: %r",
            len(raw_for_dump),
            dump_path,
            raw_for_dump[:300],
        )
    except Exception as _dump_exc:
        logger.info(
            "Failed to extract JSON object from model response (length=%d). "
            "Preview: %r (raw-dump error: %s)",
            len(raw_text or ''),
            (raw_text or '')[:300],
            _dump_exc,
        )
    return {}


def _is_legacy_bootstrap_message(message):
    if message.role != 'user':
        return False

    content = (message.content or '').strip()
    return content.startswith('=== CHARACTER IDENTITY ===') and 'Please provide your initial greeting based on your character settings.' in content


def _build_user_turn_summary(message, include_text_body=False):
    summary = _build_message_text_content(
        message,
        capabilities={'text': True, 'image': False, 'video': False},
        include_text_body=include_text_body,
    )
    return summary or '[User sent an attachment]'


def _get_visible_history_messages(chat_session):
    history_messages = Message.objects.filter(chat_session=chat_session).order_by('timestamp')
    return [message for message in history_messages if not _is_legacy_bootstrap_message(message)]


def _get_user_profile(chat_session):
    return UserProfile.get_or_create_for_user(chat_session.user)


def _get_user_local_time(profile):
    if not profile.share_local_time or not profile.timezone:
        return ""

    try:
        return datetime.now(ZoneInfo(profile.timezone)).strftime('%Y-%m-%d %H:%M %Z')
    except Exception:
        return ""


def _get_user_local_datetime(profile):
    if not profile.share_local_time or not profile.timezone:
        return None

    try:
        return datetime.now(ZoneInfo(profile.timezone))
    except Exception:
        return None


def _contains_any_keyword(text, keywords):
    return any(keyword in text for keyword in keywords)


def _describe_daypart(hour):
    if 5 <= hour < 12:
        return 'morning'
    if 12 <= hour < 18:
        return 'afternoon'
    if 18 <= hour < 22:
        return 'evening'
    return 'night'


def _get_query_local_date_reference(profile, lowered_query):
    local_now = _get_user_local_datetime(profile)
    if not local_now:
        return ''

    if _contains_any_keyword(lowered_query, TOMORROW_QUERY_KEYWORDS):
        return (local_now + timedelta(days=1)).date().isoformat()
    if _contains_any_keyword(lowered_query, YESTERDAY_QUERY_KEYWORDS):
        return (local_now - timedelta(days=1)).date().isoformat()
    if (
        _contains_any_keyword(lowered_query, TODAY_QUERY_KEYWORDS)
        or _contains_any_keyword(lowered_query, WEATHER_QUERY_KEYWORDS)
    ):
        return local_now.date().isoformat()
    return ''


def _normalize_prompt_memory_section(title, content):
    text = (content or '').strip()
    if not text:
        return ''
    return f"# {title}\n{text}"


def _extract_prompt_memory_body(section):
    text = (section or '').strip()
    if not text:
        return ''

    parts = text.split('\n', 1)
    if len(parts) == 2 and parts[0].startswith('# '):
        return parts[1].strip()
    return text


def _build_account_runtime_sections(chat_session):
    profile = _get_user_profile(chat_session)

    context_lines = []
    local_now = _get_user_local_datetime(profile)
    if local_now:
        context_lines.append(f"User Local Time: {local_now.strftime('%Y-%m-%d %H:%M %Z')}")
        context_lines.append(f"User Local Daypart: {_describe_daypart(local_now.hour)}")
        context_lines.append(
            "Interpret relative time words such as today, tonight, and tomorrow in the user's local timezone."
        )
    if profile.share_location and profile.location_label:
        context_lines.append(
            f"Location Hint ({profile.get_location_precision_display()} level): {profile.location_label}"
        )
        context_lines.append("Do not imply a more precise real-world location than the user explicitly shared.")
    if profile.share_weather and profile.share_location and profile.location_label:
        context_lines.append(
            "Weather Context: If weather comes up, ground it in the shared location hint. "
            "Do not guess current conditions. Use live research when available; otherwise speak conditionally."
        )

    boundary_lines = []
    if profile.blocked_topics:
        boundary_lines.append(f"Blocked Topics: {profile.blocked_topics}")

    memory_lines = []
    if not profile.allow_long_term_memory:
        memory_lines.append("Do not convert personal conversation details into long-term persistent memory.")
    if not profile.allow_preference_inference:
        memory_lines.append("Do not infer or store new user preferences unless the user explicitly states them.")
    if not profile.allow_research_profile_updates:
        memory_lines.append("Do not let web research modify the user profile or user preference model.")

    return {
        'context': "\n".join(context_lines),
        'boundaries': "\n".join(boundary_lines),
        'memory_rules': "\n".join(memory_lines),
        'profile_obj': profile,
    }


def _format_working_state(chat_session):
    lines = []

    if chat_session.id:
        lines.append(f"Session ID: {chat_session.id}")

    try:
        message_count = chat_session.messages.count()
    except Exception:
        message_count = 0
    lines.append(f"Visible Messages: {message_count}")

    if chat_session.updated_at:
        lines.append(f"Last Updated: {chat_session.updated_at.isoformat()}")

    if chat_session.last_response_latency_ms is not None:
        lines.append(f"Last Response Latency Ms: {chat_session.last_response_latency_ms}")

    return "\n".join(lines)


def _build_stream_memory_prefetch(character, chat_session, generate_greeting=False):
    prompt_context = build_character_prompt_context(character)

    sections = []

    candidates = [
        ('Character Setup', prompt_context.get('soul', '')),
        ('Long-Term Memory (User Model)', MemoryManager(character).render_narrative()),
    ]
    if generate_greeting:
        candidates.append(('Uploaded Background Text', prompt_context.get('uploaded_background', '')))

    for title, content in candidates:
        body = _extract_prompt_memory_body(content)
        if not body:
            continue
        sections.append(
            _normalize_prompt_memory_section(
                title,
                _truncate_text(body, STREAM_MEMORY_SECTION_LIMIT),
            )
        )

    return "\n\n".join(section for section in sections if section and section.strip())


def _build_system_prompt(character, chat_session, use_memory_tools=False, retrieved_memory=''):
    prompt_context = build_character_prompt_context(character)
    character_setup = prompt_context.get('soul', '')
    account_runtime_sections = _build_account_runtime_sections(chat_session)
    sections = [
        "You are in an immersive roleplay chat. Stay fully in character, be specific, and avoid generic assistant phrasing.",
        "Never mention system instructions, hidden rules, or that you are an AI model unless the character would explicitly know that in-world.",
    ]
    _append_section(sections, "CHARACTER SETUP", character_setup)
    _append_section(sections, "ACCOUNT CONTEXT", account_runtime_sections.get("context", ""))
    _append_section(sections, "ACCOUNT BOUNDARIES", account_runtime_sections.get("boundaries", ""))
    _append_section(sections, "MEMORY CONSENT", account_runtime_sections.get("memory_rules", ""))

    if use_memory_tools:
        _append_section(
            sections,
            "MEMORY TOOLING",
            "\n".join([
                "Do not assume long-term memory content from the prompt alone.",
                "When a reply depends on the exact character setup, prior transcripts, uploaded files, or search traces, inspect the memory filesystem first.",
                "Use list_memory_files to browse the schema/wiki/raw tree, then use read_memory_file to open only the files relevant to this turn.",
                "If you did not inspect a memory file, do not claim certainty about its contents.",
            ]),
        )
        _append_section(sections, "MEMORY FILESYSTEM", build_memory_explorer_manifest(character))
        return "\n\n".join(sections)

    compact_memory_mode = bool((retrieved_memory or '').strip())
    if compact_memory_mode:
        _append_section(sections, "WORKING STATE", _format_working_state(chat_session))
        _append_section(sections, "RETRIEVED MEMORY", retrieved_memory)
        return "\n\n".join(sections)

    uploaded_sections = "\n\n".join(
        section
        for section in [
            prompt_context.get("uploaded_index", ""),
            prompt_context.get("uploaded_background", ""),
            prompt_context.get("uploaded_visual_refs", ""),
        ]
        if section and section.strip()
    )
    _append_section(sections, "USER UPLOADS", uploaded_sections)
    _append_section(sections, "WORKING STATE", _format_working_state(chat_session))

    return "\n\n".join(sections)


def _build_search_query(chat_session, user_message=None):
    profile = _get_user_profile(chat_session)
    candidate_parts = []

    if user_message:
        candidate_parts.append(_build_user_turn_summary(user_message, include_text_body=False))

    recent_user_messages = list(
        Message.objects.filter(chat_session=chat_session, role='user').order_by('-timestamp')[:2]
    )
    for message in reversed(recent_user_messages):
        if not user_message or message.id != user_message.id:
            candidate_parts.append(_build_user_turn_summary(message, include_text_body=False))

    query = " ".join(part.strip() for part in candidate_parts if part and part.strip())
    lowered_query = query.lower()
    if (
        profile.share_location
        and profile.location_label
        and _contains_any_keyword(lowered_query, LOCAL_SEARCH_KEYWORDS)
        and profile.location_label.lower() not in lowered_query
    ):
        query = f"{query} in {profile.location_label}"

    local_date_reference = _get_query_local_date_reference(profile, lowered_query)
    if local_date_reference and local_date_reference not in query:
        query = f"{query} {local_date_reference}"

    return _truncate_text(query, 300)


def build_research_context(chat_session, user_message=None):
    profile = _get_user_profile(chat_session)
    if not profile.default_enable_web_search:
        return {
            'query': '',
            'items': [],
            'provider': '',
            'error': '',
        }

    query = _build_search_query(chat_session, user_message=user_message)
    if not query:
        return {
            'query': '',
            'items': [],
            'provider': '',
            'error': '',
        }

    return search_web(query, chat_session=chat_session)


def _format_research_context(research_context):
    items = research_context.get('items') or []
    if not items:
        error = research_context.get('error', '')
        if error:
            return f"Web search requested but unavailable: {error}"
        return ""

    lines = [f"Search Query: {research_context.get('query', '')}"]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.get('title', 'Untitled')}")
        lines.append(f"URL: {item.get('url', '')}")
        if item.get('snippet'):
            lines.append(f"Snippet: {item.get('snippet')}")
    return "\n".join(lines)


def _get_tools(chat_session, runtime_config, allow_memory_tools=True):
    if allow_memory_tools and _supports_memory_tool_mode(runtime_config):
        return _build_memory_tool_specs()

    return []


def _build_provider_messages(
    chat_session,
    character,
    generate_greeting=False,
    research_context=None,
    allow_memory_tools=True,
    retrieved_memory='',
):
    runtime_config = _get_runtime_model_config(chat_session)
    capabilities = _get_model_capabilities(runtime_config)
    use_memory_tools = allow_memory_tools and _supports_memory_tool_mode(runtime_config)
    tools = _get_tools(chat_session, runtime_config, allow_memory_tools=allow_memory_tools)
    system_prompt = _build_system_prompt(
        character,
        chat_session,
        use_memory_tools=use_memory_tools,
        retrieved_memory=retrieved_memory,
    )
    prompt_context = build_character_prompt_context(character)
    if research_context:
        formatted_research = _format_research_context(research_context)
        if formatted_research:
            system_prompt = f"{system_prompt}\n\n[LIVE WEB RESEARCH]\n{formatted_research}"
    visible_history = _get_visible_history_messages(chat_session)
    character_reference_message = _build_character_reference_message(
        character,
        runtime_config,
        capabilities,
        prompt_context,
        use_memory_tools=use_memory_tools,
    )

    if generate_greeting:
        visible_history.append({
            'role': 'user',
            'content': (
                "Start the conversation now. Send the first in-character message proactively, "
                "grounded in the scenario and relationship context. Do not wait for the user to speak first."
            ),
        })

    if runtime_config['provider'] == 'gemini':
        formatted_history = [{'role': 'user', 'parts': [system_prompt]}]
        if character_reference_message:
            formatted_history.append(character_reference_message)
        for message in visible_history:
            if isinstance(message, Message):
                formatted_history.append(_build_provider_message_entry(message, runtime_config, capabilities))
                continue
            formatted_history.append({'role': 'user', 'parts': [message['content']]})
        return runtime_config, formatted_history, tools

    formatted_history = [{'role': 'system', 'content': system_prompt}]
    if character_reference_message:
        formatted_history.append(character_reference_message)
    for message in visible_history:
        if isinstance(message, Message):
            formatted_history.append(_build_provider_message_entry(message, runtime_config, capabilities))
            continue
        formatted_history.append({'role': 'user', 'content': message['content']})
    return runtime_config, formatted_history, tools


# ---------------------------------------------------------------------------
# Long-term memory pipeline (per-turn, SonettoHere parity)
# ---------------------------------------------------------------------------
def _publish_memory_event(chat_session_id, action):
    """Best-effort Redis pub/sub for SSE consumers; failures are logged but
    never fatal.
    """
    try:
        from django.conf import settings
        import redis

        client = redis.Redis.from_url(settings.CELERY_BROKER_URL or 'redis://localhost:6379/0')
        client.publish(
            f'chat:memory_updates:{chat_session_id}',
            json.dumps(action, ensure_ascii=False, default=str),
        )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            'Failed to publish memory event for session %s: %s', chat_session_id, exc,
        )


def _execute_memory_crud_tool(character, manager, source_message, tool_name, raw_args):
    """Local tool implementation invoked by the Celery worker ReAct loop."""
    try:
        arguments = json.loads(raw_args or '{}')
    except json.JSONDecodeError:
        arguments = {}

    if tool_name == 'create_memory':
        item = manager.create_item(
            section=arguments.get('section', ''),
            description=arguments.get('description', ''),
            reason=arguments.get('reason', ''),
            source_message=source_message,
        )
        return {
            'status': 'created',
            'short_id': item.short_id,
            'section': item.section,
            'description': item.description,
        }
    if tool_name == 'read_memories':
        section = (arguments.get('section') or '').strip()
        items = manager.list_items()
        if section:
            items = [item for item in items if item.section == section]
        return {
            'items': [
                {
                    'short_id': item.short_id,
                    'section': item.section,
                    'description': item.description,
                }
                for item in items
            ],
        }
    if tool_name == 'update_memory':
        item = manager.update_item(
            short_id=arguments.get('id', ''),
            description=arguments.get('description', ''),
            section=arguments.get('section'),
            reason=arguments.get('reason', ''),
            source_message=source_message,
        )
        return {'status': 'updated', 'short_id': item.short_id, 'description': item.description}
    if tool_name == 'delete_memory':
        removed = manager.delete_item(
            short_id=arguments.get('id', ''),
            reason=arguments.get('reason', ''),
            source_message=source_message,
        )
        return {'status': 'deleted', 'description': removed}
    if tool_name == 'merge_memories':
        item = manager.merge_items(
            id1=arguments.get('id1', ''),
            id2=arguments.get('id2', ''),
            content=arguments.get('content', ''),
            section=arguments.get('section', ''),
            reason=arguments.get('reason', ''),
            source_message=source_message,
        )
        return {'status': 'merged', 'kept_short_id': item.short_id, 'description': item.description}
    return {'error': f'Unknown memory tool: {tool_name}'}


def _collect_memory_actions(
    runtime_config,
    prompt,
    character,
    manager,
    source_message,
    tool_specs,
):
    """Drive the ReAct loop for the per-turn memory extraction call.

    Returns a list of action dicts suitable for SSE publish / audit logging.
    """
    provider = runtime_config['provider']
    messages = [
        {'role': 'system', 'content': prompt['system']},
        {'role': 'user', 'content': prompt['user']},
    ]

    actions: list[dict] = []
    if provider == 'openai_compatible':
        for _ in range(LONG_TERM_MEMORY_TOOL_ROUND_TRIP_LIMIT):
            try:
                response_json = _request_openai_compatible_completion(
                    model_name=runtime_config['model_name'],
                    api_key=runtime_config['api_key'],
                    messages=messages,
                    base_url=runtime_config.get('base_url', ''),
                    tools=tool_specs,
                )
            except Exception as exc:  # noqa: BLE001
                if _should_retry_without_tools(exc):
                    logger.warning(
                        'OpenAI-compatible backend rejected memory tools for %s; retrying without.',
                        runtime_config['model_name'],
                    )
                    response_json = _request_openai_compatible_completion(
                        model_name=runtime_config['model_name'],
                        api_key=runtime_config['api_key'],
                        messages=messages,
                        base_url=runtime_config.get('base_url', ''),
                    )
                else:
                    raise
            assistant_message = _extract_openai_assistant_message(response_json)
            tool_calls = assistant_message.get('tool_calls') or []
            messages.append({
                'role': 'assistant',
                'content': assistant_message.get('content'),
                **({'tool_calls': tool_calls} if tool_calls else {}),
            })
            if not tool_calls:
                break
            for tool_call in tool_calls:
                function_payload = tool_call.get('function') or {}
                tool_name = function_payload.get('name', '')
                result = _execute_memory_crud_tool(
                    character, manager, source_message,
                    tool_name, function_payload.get('arguments', '{}'),
                )
                actions.append({'tool': tool_name, 'result': result, 'short_id': (result.get('short_id') or result.get('kept_short_id') or '')})
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tool_call.get('id', ''),
                    'content': json.dumps(result, ensure_ascii=False),
                })
        return actions

    if provider == 'gemini':
        # Gemini path: ask the model for plain text describing what to do, parse
        # out JSON action triples, dispatch through the same local tool layer.
        try:
            if not runtime_config['api_key']:
                raise ValueError('API key is required for the selected model configuration')
            import google.generativeai as genai

            genai.configure(api_key=runtime_config['api_key'])
            response = genai.GenerativeModel(runtime_config['model_name']).generate_content(
                f"{prompt['system']}\n\n{prompt['user']}\n\n"
                'Respond with a JSON array of tool calls, e.g. '
                '[{"tool": "create_memory", "args": {"section": "身份", "description": "..."}}]. '
                'Allowed tools: create_memory / read_memories / update_memory / delete_memory / merge_memories.'
            )
            raw_text = (getattr(response, 'text', '') or '').strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning('Gemini memory call failed: %s', exc)
            return actions

        # We expect an array; if we got an object, wrap.
        try:
            data = _extract_json_object(raw_text)
        except (ValueError, TypeError):
            data = {}
        candidates = data.get('actions') if isinstance(data, dict) and data.get('actions') else None
        if candidates is None and isinstance(data, dict):
            # fall back: pluck the first list value we find
            for value in data.values():
                if isinstance(value, list):
                    candidates = value
                    break
        if not candidates:
            # As a last resort, look for the first JSON array in raw_text.
            match = re.search(r'\[[^\]]*\]', raw_text, re.DOTALL)
            if match:
                try:
                    candidates = json.loads(match.group(0))
                except json.JSONDecodeError:
                    candidates = []
        for entry in candidates or []:
            if not isinstance(entry, dict):
                continue
            tool_name = entry.get('tool') or entry.get('name') or ''
            args = entry.get('args') or entry.get('arguments') or {}
            result = _execute_memory_crud_tool(
                character, manager, source_message, tool_name, json.dumps(args, ensure_ascii=False),
            )
            actions.append({'tool': tool_name, 'result': result, 'short_id': (result.get('short_id') or result.get('kept_short_id') or '')})
        return actions

    raise ValueError(f'Unsupported model provider for memory sync: {provider}')


@shared_task(
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 2},
    rate_limit='30/m',
)
def sync_long_term_memory(self, message_id, chat_session_id, character_id):
    """Per-turn long-term-memory sync (SonettoHere parity).

    Mirrors ``LongTermMemoryInterface.send_history`` + the consumer
    coroutine from SonettoHere, but driven by Celery instead of an
    asyncio queue. The DB write happens here; the chat view never waits.

    Lock scope: we deliberately do **not** wrap the heading read in a
    ``transaction.atomic`` + ``select_for_update``. The per-tool
    ``MemoryManager`` CRUD methods each open their own short atomic block,
    so no character row lock is held across the multi-round ReAct turn.
    A long Gemini call (30s+) therefore no longer blocks other writers.

    Concurrency caveat for v1: two near-simultaneous turns for the same
    character can race on the same ``short_id`` because each per-tool
    ``transaction.atomic`` only protects a single write. Acceptable for
    the typical single-session flow; serialize per character with a
    Celery header or Redis flag in v2.
    """
    try:
        character = Character.objects.get(pk=character_id)
        chat_session = ChatSession.objects.get(pk=chat_session_id)
        message = Message.objects.select_related('chat_session').get(pk=message_id)

        profile = UserProfile.get_or_create_for_user(character.created_by)
        if not profile.allow_long_term_memory:
            logger.info('Long-term memory disabled for user %s; skipping.', character.created_by_id)
            return {'status': 'skipped', 'reason': 'user_disabled_long_term_memory'}
        if chat_session.is_private_mode:
            logger.info('Private mode active for session %s; skipping.', chat_session_id)
            return {'status': 'skipped', 'reason': 'private_mode'}

        items = list(
            CharacterMemoryItem.objects
            .filter(character=character)
            .order_by('section', 'short_id')
        )
        manager = MemoryManager(character)
        prompt = build_memory_extraction_prompt(
            character_name=character.name,
            items=items,
            chat_session=chat_session,
            new_message=message,
            timezone_name=profile.timezone or 'UTC',
        )
        runtime_config = _get_runtime_model_config(chat_session)
        actions = _collect_memory_actions(
            runtime_config=runtime_config,
            prompt=prompt,
            character=character,
            manager=manager,
            source_message=message,
            tool_specs=get_memory_crud_tool_specs(),
        )

        for action in actions:
            _publish_memory_event(chat_session_id, action)

        logger.info(
            'Long-term memory sync for session=%s character=%s actions=%s',
            chat_session_id, character_id, len(actions),
        )
        return {'status': 'ok', 'actions': len(actions)}
    except Exception as exc:  # noqa: BLE001
        logger.exception('Long-term memory sync failed: session=%s message=%s', chat_session_id, message_id)
        return {'status': 'error', 'error': str(exc)}


@shared_task(retry_backoff=True)
def update_session_title(chat_session, history_text, runtime_config):
    try:
        prompt = (
            "Analyze the following short conversation start.\n"
            "Generate a short, engaging title (2-6 words) that summarizes the topic.\n"
            "Rules:\n"
            "1. Use the same language as the conversation.\n"
            "2. Do not use quotation marks.\n"
            "3. Do not include words like Chat, Conversation, or Title.\n"
            "4. Return only the title text.\n\n"
            f"Conversation:\n{history_text}"
        )

        new_title = _generate_text(runtime_config, prompt).replace('"', '').replace("'", "").strip()
        if new_title:
            chat_session.title = new_title[:200]
            chat_session.save(update_fields=['title'])
    except Exception as exc:
        logger.error("Failed to auto-generate title for session %s: %s", chat_session.id, exc)


def _build_research_payload(chat_session, research_context):
    return {
        'query': research_context.get('query', ''),
        'provider': research_context.get('provider', ''),
        'items': research_context.get('items', []),
        'error': research_context.get('error', ''),
    }


def _finalize_ai_response(
    chat_session,
    character,
    runtime_config,
    ai_response_text,
    user_message=None,
    latency_ms=None,
    research_context=None,
):
    ai_message = Message.objects.create(
        chat_session=chat_session,
        role='assistant',
        content=ai_response_text,
        character=character,
        research_payload={},
    )

    update_fields = ['updated_at']
    if latency_ms is not None:
        chat_session.last_response_latency_ms = latency_ms
        update_fields.append('last_response_latency_ms')
    chat_session.save(update_fields=update_fields)

    if user_message is not None:
        visible_history_count = len(_get_visible_history_messages(chat_session))
        is_default_title = chat_session.title.startswith("Chat with ")
        if is_default_title or visible_history_count <= 4:
            conversation_text_for_title = (
                f"User: {_build_user_turn_summary(user_message, include_text_body=False)}\n"
                f"Character: {ai_response_text[:200]}"
            )
            update_session_title(chat_session, conversation_text_for_title, runtime_config)

    research_payload = _build_research_payload(chat_session, research_context or {})
    ai_message.research_payload = research_payload
    ai_message.save(update_fields=['research_payload'])

    # Async long-term memory write (SonettoHere parity). Fire-and-forget:
    # if the broker is unavailable we still return the AI reply successfully.
    try:
        sync_long_term_memory.delay(
            message_id=ai_message.id,
            chat_session_id=chat_session.id,
            character_id=character.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Failed to enqueue sync_long_term_memory: %s', exc)

    return ai_message


@shared_task(retry_backoff=True)
def generate_ai_response(message_id, character_id, generate_greeting=False, chat_session_id=None):
    try:
        character = Character.objects.get(id=character_id)
        user_message = Message.objects.get(id=message_id) if message_id else None
        chat_session = user_message.chat_session if user_message else None
        if chat_session is None and chat_session_id is not None:
            chat_session = character.chat_sessions.get(id=chat_session_id)
        if chat_session is None:
            raise ValueError('Chat session not found for response generation')
        research_context = build_research_context(chat_session, user_message=user_message)
        runtime_config, formatted_history, tools = _build_provider_messages(
            chat_session=chat_session,
            character=character,
            generate_greeting=generate_greeting,
            research_context=research_context,
        )

        started_at = time.perf_counter()
        ai_response_text = _generate_text(runtime_config, formatted_history, tools=tools, character=character)
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        ai_message = _finalize_ai_response(
            chat_session=chat_session,
            character=character,
            runtime_config=runtime_config,
            ai_response_text=ai_response_text,
            user_message=user_message,
            latency_ms=latency_ms,
            research_context=research_context,
        )

        return {
            'success': True,
            'message_id': ai_message.id,
            'content': ai_response_text,
            'latency_ms': latency_ms,
        }
    except Exception as exc:
        return {
            'success': False,
            'error': str(exc),
        }


def stream_ai_response(chat_session, character, user_message=None, generate_greeting=False):
    research_context = build_research_context(chat_session, user_message=user_message)
    retrieved_memory = _build_stream_memory_prefetch(
        character,
        chat_session,
        generate_greeting=generate_greeting,
    )
    runtime_config, formatted_history, tools = _build_provider_messages(
        chat_session=chat_session,
        character=character,
        generate_greeting=generate_greeting,
        research_context=research_context,
        allow_memory_tools=False,
        retrieved_memory=retrieved_memory,
    )

    started_at = time.perf_counter()
    collected_chunks = []

    for chunk in _iter_text_chunks(runtime_config, formatted_history, tools=tools, character=character):
        if not chunk:
            continue
        collected_chunks.append(chunk)
        yield {'type': 'delta', 'content': chunk}

    ai_response_text = ''.join(collected_chunks).strip()
    latency_ms = int((time.perf_counter() - started_at) * 1000)

    if not ai_response_text:
        raise ValueError('The model returned an empty response')

    ai_message = _finalize_ai_response(
        chat_session=chat_session,
        character=character,
        runtime_config=runtime_config,
        ai_response_text=ai_response_text,
        user_message=user_message,
        latency_ms=latency_ms,
        research_context=research_context,
    )

    yield {
        'type': 'done',
        'message_id': ai_message.id,
        'content': ai_message.content,
        'timestamp': ai_message.timestamp.isoformat(),
        'latency_ms': latency_ms,
        'provider': runtime_config['provider'],
        'model_name': runtime_config['model_name'],
        'research_payload': ai_message.research_payload,
    }
