"""Character draft background jobs.

``start_character_draft`` 会创建一条 ``CharacterDraftJob`` 并把真正的生成
工作放到进程内后台线程执行：HTTP 请求立即返回，前端轮询任务行拿到真实
进度，页面刷新后重新轮询即可恢复显示。

- 结果缓存：任务行带内容指纹（文件 sha256 集合 + 提示语 + 语言），同语
  料再次生成直接复用历史结果（stage='cache'，0 次 LLM 调用，秒级）。
- 取消：``cancel_character_draft_job`` 把状态置为 ``canceling``，runner 在
  启动与落定前检查并终止（协作式取消；单请求进行中不中断）。
- 崩溃残留的 ``running`` 行由 ``sweep_stale_jobs`` 在下次 start 时标记为
  failed。

线程与 Django：每个线程持有自己的 DB 连接，退出时必须关闭（finally 里的
``connections.close_all()``），否则连接池会被后台线程逐渐吃满。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading

from django.db import connections
from django.utils import timezone

from .models import CharacterDraftJob

logger = logging.getLogger(__name__)

# running 行超过该时长没有任何进度更新，视为 runner 已死（进程崩溃/重启）。
STALE_JOB_MINUTES = 15


class DraftJobCanceled(Exception):
    """canceling 状态检查命中时抛出，终止任务。"""


def compute_content_fingerprint(staged_uploads: list, text_context: str, locale: str, model_id: str = '') -> str:
    """全部文件内容哈希 + 提示语 + 语言 + 模型身份 → 内容指纹。

    同一语料重传后 upload_ids 全变，但 sha256 不变；指纹相同即可直接
    复用已完成任务的最终结果（秒级出卡）。模型身份参与指纹：换模型时
    旧缓存自然失效，避免返回另一个模型的旧结果。
    """
    hashes = sorted(
        str(upload.get('content_hash') or '')
        for upload in staged_uploads
    )
    payload = json.dumps(
        {
            'files': hashes,
            'context': text_context or '',
            'locale': locale or '',
            'model': model_id or '',
            # 提取契约变更（新增/修改要求模型输出的字段）时递增，让旧缓存失效。
            'prompt_version': 2,
        },
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def start_draft_job_thread(job_id: int) -> None:
    thread = threading.Thread(
        target=_run_job_with_cleanup,
        args=(job_id,),
        daemon=True,
        name=f'character-draft-job-{job_id}',
    )
    thread.start()


def _run_job_with_cleanup(job_id: int) -> None:
    try:
        execute_draft_job(job_id)
    finally:
        # 线程持有的连接必须归还/关闭，否则每次任务泄漏一个连接。
        connections.close_all()


def _check_canceled(job: CharacterDraftJob) -> None:
    """刷新状态并检查取消标记；取消时落定最终状态并抛出。"""
    fresh_status = (
        CharacterDraftJob.objects.filter(id=job.id)
        .values_list('status', flat=True)
        .first()
    )
    if fresh_status == CharacterDraftJob.Status.CANCELING:
        job.status = CharacterDraftJob.Status.CANCELED
        job.stage = 'canceled'
        job.save(update_fields=['status', 'stage', 'updated_at'])
        raise DraftJobCanceled(f'Draft job {job.id} canceled by user.')


def execute_draft_job(job_id: int) -> None:
    """在后台线程里跑完一次草稿生成（models/ORM 均为同步调用）。"""
    # 延迟导入避免模块级循环：schema 顶层要导入本模块来启动线程。
    from .graphql.schema import (
        _compute_character_draft,
        _get_draft_prompt_locale,
        _resolve_staged_uploads_from_assets,
        _resolve_staged_uploads_from_events,
        DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET,
    )

    job = CharacterDraftJob.objects.filter(id=job_id).first()
    if job is None:
        logger.error('Draft job %s vanished before the runner started.', job_id)
        return
    if job.status == CharacterDraftJob.Status.CANCELING:
        job.status = CharacterDraftJob.Status.CANCELED
        job.stage = 'canceled'
        job.save(update_fields=['status', 'stage', 'updated_at'])
        return

    inputs = job.inputs or {}
    upload_ids = inputs.get('upload_ids') or []
    asset_ids = inputs.get('asset_ids') or []
    text_context = inputs.get('text_context') or ''
    locale = inputs.get('locale') or ''

    try:
        job.stage = 'resolve'
        job.save(update_fields=['stage', 'updated_at'])
        _check_canceled(job)

        draft_locale = _get_draft_prompt_locale(job.user, locale)

        full_text_budget = {'remaining': DRAFT_FULL_TEXT_TOTAL_CHAR_BUDGET}
        staged_uploads = []
        if upload_ids:
            staged_uploads.extend(
                _resolve_staged_uploads_from_events(job.user, upload_ids, full_text_budget)
            )
        if asset_ids:
            staged_uploads.extend(
                _resolve_staged_uploads_from_assets(job.user, asset_ids, full_text_budget)
            )
        # 去重与 start mutation 保持同一规则（按 file_url 兜底）。
        seen_urls = set()
        deduped_uploads = []
        for upload in staged_uploads:
            dedup_key = upload.get('file_url') or upload.get('name')
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)
            deduped_uploads.append(upload)

        # 结果级缓存：同一内容指纹（文件 sha256 集合 + 提示语 + 语言 + 模型
        # 身份）的历史任务直接复用最终结果，0 次 LLM 调用，秒级完成。
        try:
            runtime_config = _get_draft_runtime_config(job.user)
            model_id = '{}:{}@{}'.format(
                runtime_config.get('provider', ''),
                runtime_config.get('model_name', ''),
                runtime_config.get('base_url', ''),
            )
        except Exception:  # noqa: BLE001 - 无可用模型时 _compute 阶段会明确报错
            model_id = ''
        content_fingerprint = compute_content_fingerprint(deduped_uploads, text_context, locale, model_id=model_id)
        job.content_fingerprint = content_fingerprint
        job.save(update_fields=['content_fingerprint', 'updated_at'])
        previous = (
            CharacterDraftJob.objects
            .filter(
                user=job.user,
                content_fingerprint=content_fingerprint,
                status=CharacterDraftJob.Status.SUCCEEDED,
            )
            .exclude(result__isnull=True)
            .order_by('-id')
            .first()
        )
        if previous is not None:
            _check_canceled(job)
            job.status = CharacterDraftJob.Status.SUCCEEDED
            job.stage = 'cache'
            job.detail = f'reused result of job {previous.id} (content fingerprint match)'
            job.result = previous.result
            job.save(update_fields=['status', 'stage', 'detail', 'result', 'updated_at'])
            logger.info(
                'Draft job %s reused result of job %s via content fingerprint (0 LLM calls).',
                job.id, previous.id,
            )
            return

        draft_fields, meta = _compute_character_draft(
            job.user,
            draft_locale,
            text_context or None,
            deduped_uploads,
        )

        # 落定前再查一次取消：请求进行中无法中断，至少不让已取消的任务落定成功。
        _check_canceled(job)

        job.status = CharacterDraftJob.Status.SUCCEEDED
        job.stage = 'done'
        job.detail = str(meta or '')
        job.result = draft_fields
        job.save(update_fields=['status', 'stage', 'detail', 'result', 'updated_at'])
        logger.info(
            'Draft job %s succeeded (staged_uploads=%s, meta=%s).',
            job.id, len(deduped_uploads), meta,
        )
    except DraftJobCanceled:
        logger.info('Draft job %s canceled.', job_id)
    except Exception as exc:  # noqa: BLE001 - 后台线程的失败必须落回任务行
        logger.exception('Draft job %s failed: %s', job_id, exc)
        CharacterDraftJob.objects.filter(id=job_id).update(
            status=CharacterDraftJob.Status.FAILED,
            stage='failed',
            error=str(exc)[:4000],
        )


def sweep_stale_jobs(user) -> int:
    """把该用户超时无更新的 running/canceling 行标记为 failed。

    在 start mutation 里调用：runner 只存在于本进程，进程重启后旧行永远
    不会再有进度更新，不清理的话前端会无限轮询。
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=STALE_JOB_MINUTES)
    stale = CharacterDraftJob.objects.filter(
        user=user,
        status__in=[CharacterDraftJob.Status.RUNNING, CharacterDraftJob.Status.CANCELING],
        updated_at__lt=cutoff,
    )
    count = 0
    for job in stale:
        job.status = CharacterDraftJob.Status.FAILED
        job.stage = 'failed'
        job.error = f'Runner stopped updating for over {STALE_JOB_MINUTES} minutes (server restart?).'
        job.save(update_fields=['status', 'stage', 'error', 'updated_at'])
        count += 1
    return count
