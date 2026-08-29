"""Character draft background-job tests.

与 test_memory.py 相同的 SQLite-in-memory 模式。注意：后台线程在 TestCase
的未提交事务里看不到数据，所以这里不启动真线程——start mutation 打断
``start_draft_job_thread``，随后在测试线程里同步调用 ``execute_draft_job``，
事务可见性与生产代码路径（同一 runner 函数）完全一致。
"""
import json
import unittest.mock
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from .test_memory import SQLITE_TEST_DATABASES

DRAFT_JSON = json.dumps({
    'name': 'Job Drafted Character',
    'description': 'A detailed background in three sentences. Second sentence. Third sentence.',
    'affiliation': 'Lab',
    'tags': ['job', 'draft'],
})

BATCH_NOTE_JSON = json.dumps({
    'batch_summary': 'batch summary',
    'citations': [],
    'personality_evidence': ['证据一'],
    'language_style': [],
    'behavior_notes': [],
    'emotion_triggers': [],
    'relationships': [],
})

MERGE_JSON = json.dumps({
    'profile_summary': {
        'name': '玛丽',
        'description': '三个句子组成的描述。第二句。第三句。',
        'personality': '冷静但倔强',
        'appearance': '',
        'affiliation': '第二学生社团',
        'tags': ['学生', '会长'],
    },
    'dialogue_library': {},
    'behavior_samples': [],
    'evolution': [],
})


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class ReducePipelineProgressTests(TestCase):
    """纯函数级：进度回调、checkpoint 回调、断点复用。"""

    def _uploads(self, count=17):
        return [
            {
                'name': f'f{index}.txt',
                'content': f'玛丽: 台词第{index}句\n旁白: 描述\n' * 20,
                'file_url': f'media/uploads/{index}.txt',
                'content_hash': f'hash-{index}',
            }
            for index in range(count)
        ]

    @staticmethod
    def _llm_call(calls):
        from chat.character_reduce import BATCH_NOTE_SYSTEM

        def llm_call(system_prompt, user_prompt):
            calls.append(system_prompt)
            if system_prompt == BATCH_NOTE_SYSTEM:
                return BATCH_NOTE_JSON
            return MERGE_JSON
        return llm_call

    def test_progress_and_checkpoint_callbacks_fire(self):
        from chat.character_reduce import run_reduce_pipeline

        calls = []
        progress = []
        notes = []
        result = run_reduce_pipeline(
            self._uploads(),
            '玛丽',
            llm_call=self._llm_call(calls),
            progress_callback=lambda stage, done, total: progress.append((stage, done, total)),
            on_batch_note=lambda sig, tier, files, note: notes.append((sig, tier, files, note)),
        )

        # 17 个文件按 8/批 → 3 批；进度从 0 推进到 3，随后进入 merge。
        self.assertEqual(progress[0], ('analyze', 0, 3))
        self.assertEqual(progress[-1], ('merge', 0, 1))
        analyze_events = [event for event in progress if event[0] == 'analyze']
        self.assertEqual(analyze_events[-1], ('analyze', 3, 3))
        self.assertEqual(len(notes), 3)
        for signature, tier, files, note in notes:
            # 签名是内容寻址的：目标角色 + 层 + 内容哈希序列。
            self.assertTrue(signature.startswith(f'玛丽::{tier}::'))
            self.assertIn('hash-', signature)
            self.assertEqual(len(files), len(note.get('_files') or files))
        self.assertEqual(result['batch_count'], 3)
        self.assertEqual(result['result']['profile_summary']['name'], '玛丽')

    def test_batch_signature_content_addressed(self):
        from chat.character_reduce import _batch_signature

        same_content_a = [{'content_hash': 'h1', 'file_url': 'media/a.txt'}]
        same_content_b = [{'content_hash': 'h1', 'file_url': 'media/reupload-uuid/b.txt'}]
        self.assertEqual(
            _batch_signature('星野', 'main', same_content_a),
            _batch_signature('星野', 'main', same_content_b),
        )
        # 目标角色不同 → 笔记语义不同 → 签名必须不同。
        self.assertNotEqual(
            _batch_signature('星野', 'main', same_content_a),
            _batch_signature('玛丽', 'main', same_content_a),
        )

    def test_extract_core_excerpts_pure_rules(self):
        from chat.character_reduce import extract_character_core_excerpts

        uploads = [
            {
                'name': 'scene1.txt',
                'content': (
                    '旁白: 清晨的教室\n'
                    '星野: 早啊，困死了。\n'
                    '白子: 你又迟到了。\n'
                    '旁白: 她打了个哈欠。\n'
                    '星野: 嘛，偶尔一次。\n'
                ),
            },
            {
                'name': 'other.txt',
                'content': '旁白: 这里没有任何主要角色的戏份。\n',
            },
        ]
        excerpts = extract_character_core_excerpts(uploads, '星野', max_total_chars=10000)
        # 台词行与上下文进来了，无关文件被整体跳过。
        self.assertIn('星野: 早啊，困死了。', excerpts)
        self.assertIn('白子: 你又迟到了。', excerpts)
        self.assertNotIn('other.txt', excerpts)
        self.assertLessEqual(len(excerpts), 10000)

        # 目标角色没出现 → 空串（调用方回退 reduce 管线）。
        self.assertEqual(extract_character_core_excerpts(uploads, '不存在的人'), '')

    def test_extract_budget_keeps_dialogue_over_mentions(self):
        """上下文超限防护：预算紧张时先丢提及窗口，台词行必须保留。"""
        from chat.character_reduce import extract_character_core_excerpts

        uploads = [{
            'name': 's.txt',
            'content': (
                '星野: 关键台词一句\n'
                + ''.join(f'旁白里提到星野的长段描写第{i}句\n' for i in range(500))
            ),
        }]
        excerpts = extract_character_core_excerpts(uploads, '星野', max_total_chars=300)
        self.assertIn('星野: 关键台词一句', excerpts)

    def test_extract_core_excerpts_budget_round_robin(self):
        from chat.character_reduce import extract_character_core_excerpts

        uploads = [
            {'name': f'f{i}.txt', 'content': f'星野: 台词{i}\n旁白: 描述{i}\n' * 100}
            for i in range(10)
        ]
        excerpts = extract_character_core_excerpts(uploads, '星野', max_total_chars=5000)
        self.assertLessEqual(len(excepts if False else excerpts), 5000)
        # 轮转采样：预算内应覆盖多个文件而不是只取前几个。
        covered = sum(1 for i in range(10) if f'f{i}.txt' in excerpts)
        self.assertGreaterEqual(covered, 5)

    def test_completed_notes_skip_batch_llm_calls(self):
        from chat.character_reduce import BATCH_NOTE_SYSTEM, MERGE_SYSTEM, run_reduce_pipeline

        first_calls = []
        notes = []
        run_reduce_pipeline(
            self._uploads(),
            '玛丽',
            llm_call=self._llm_call(first_calls),
            on_batch_note=lambda sig, tier, files, note: notes.append(
                {'signature': sig, 'tier': tier, 'files': files, 'note': note},
            ),
        )
        batch_calls_first = sum(1 for system in first_calls if system == BATCH_NOTE_SYSTEM)
        self.assertEqual(batch_calls_first, 3)

        second_calls = []
        second_notes = []
        completed = {entry['signature']: entry['note'] for entry in notes}
        result = run_reduce_pipeline(
            self._uploads(),
            '玛丽',
            llm_call=self._llm_call(second_calls),
            on_batch_note=lambda *args: second_notes.append(args),
            completed_notes=completed,
        )

        # 断点续跑：批次零调用，只剩合并；且不再产出新笔记。
        self.assertEqual(sum(1 for system in second_calls if system == BATCH_NOTE_SYSTEM), 0)
        self.assertEqual(sum(1 for system in second_calls if system == MERGE_SYSTEM), 1)
        self.assertEqual(second_notes, [])
        self.assertEqual(result['result']['profile_summary']['name'], '玛丽')

    def test_fetch_cached_note_lazy_lookup(self):
        """completed_notes 为空时，fetch_cached_note 命中同样跳过批次调用。"""
        from chat.character_reduce import BATCH_NOTE_SYSTEM, run_reduce_pipeline

        first_calls = []
        notes = []
        run_reduce_pipeline(
            self._uploads(),
            '玛丽',
            llm_call=self._llm_call(first_calls),
            on_batch_note=lambda sig, tier, files, note: notes.append(
                {'signature': sig, 'note': note},
            ),
        )
        cache = {entry['signature']: entry['note'] for entry in notes}

        second_calls = []
        result = run_reduce_pipeline(
            self._uploads(),
            '玛丽',
            llm_call=self._llm_call(second_calls),
            fetch_cached_note=lambda signature: cache.get(signature),
        )
        self.assertEqual(sum(1 for system in second_calls if system == BATCH_NOTE_SYSTEM), 0)
        self.assertEqual(result['result']['profile_summary']['name'], '玛丽')

    def test_progress_callback_exception_cancels_pipeline(self):
        from chat.character_reduce import run_reduce_pipeline

        calls = []

        def canceling_callback(stage, done, total):
            if stage == 'analyze' and done >= 1:
                raise RuntimeError('canceled')

        with self.assertRaises(RuntimeError):
            run_reduce_pipeline(
                self._uploads(),
                '玛丽',
                llm_call=self._llm_call(calls),
                progress_callback=canceling_callback,
            )
        # 取消后不再继续发起新的合并调用。
        self.assertLess(len(calls), 4)


@override_settings(DATABASES=SQLITE_TEST_DATABASES)
@override_settings(DEV_AUTO_LOGIN_ENABLED=False)
class CharacterDraftJobFlowTests(TestCase):
    """start/cancel mutation + runner（同步执行）的行为。"""

    def setUp(self):
        from chat.models import ModelConfiguration, ModelRole, ModelRoleAssignment

        self.user = User.objects.create_user(username='draft-owner', password='x')
        self.other_user = User.objects.create_user(username='draft-other', password='x')
        config = ModelConfiguration.objects.create(
            user=self.user,
            name='Default Draft Model',
            provider='openai_compatible',
            model_name='gpt-4.1-mini',
            api_key='user-api-key',
            base_url='https://example.com/v1',
        )
        ModelRoleAssignment.objects.update_or_create(
            user=self.user,
            role=ModelRole.TEXT,
            defaults={'model_config': config},
        )

    def graphql(self, query, variables=None, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(
            '/api/graphql/',
            data=json.dumps({'query': query, 'variables': variables or {}}),
            content_type='application/json',
        )

    def _start(self, text_context='Character concept from the user.'):
        return self.graphql(
            """
            mutation StartDraft($textContext: String) {
              startCharacterDraft(textContext: $textContext) {
                id status stage progressDone progressTotal
              }
            }
            """,
            variables={'textContext': text_context},
            user=self.user,
        )

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    @unittest.mock.patch('chat.graphql.schema._generate_text')
    def test_start_creates_job_and_runner_succeeds(self, mock_generate_text, mock_start_thread):
        from chat.draft_jobs import execute_draft_job
        from chat.models import CharacterDraftJob

        mock_generate_text.return_value = DRAFT_JSON
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self._start()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('errors', payload)
        job_id = int(payload['data']['startCharacterDraft']['id'])
        self.assertEqual(payload['data']['startCharacterDraft']['status'], 'running')
        # 测试不执行 on_commit 回调（真线程看不到未提交事务），只验证
        # 生产路径注册了线程启动。
        self.assertEqual(len(callbacks), 1)

        execute_draft_job(job_id)
        job = CharacterDraftJob.objects.get(id=job_id)
        self.assertEqual(job.status, CharacterDraftJob.Status.SUCCEEDED)
        self.assertEqual(job.stage, 'done')
        self.assertEqual(job.result['name'], 'Job Drafted Character')

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    @unittest.mock.patch('chat.graphql.schema._generate_text')
    def test_runner_marks_failure_on_model_error(self, mock_generate_text, mock_start_thread):
        from chat.draft_jobs import execute_draft_job
        from chat.models import CharacterDraftJob

        mock_generate_text.return_value = '这不是 JSON 的普通回复，没有任何对象。'
        response = self._start()
        job_id = int(response.json()['data']['startCharacterDraft']['id'])

        execute_draft_job(job_id)
        job = CharacterDraftJob.objects.get(id=job_id)
        self.assertEqual(job.status, CharacterDraftJob.Status.FAILED)
        self.assertIn('valid JSON', job.error)

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    def test_cancel_before_runner_start_marks_canceled(self, mock_start_thread):
        from chat.draft_jobs import execute_draft_job
        from chat.models import CharacterDraftJob

        response = self._start()
        job_id = int(response.json()['data']['startCharacterDraft']['id'])

        cancel_response = self.graphql(
            """
            mutation CancelDraft($id: ID!) {
              cancelCharacterDraftJob(id: $id) { id status }
            }
            """,
            variables={'id': str(job_id)},
            user=self.user,
        )
        self.assertEqual(
            cancel_response.json()['data']['cancelCharacterDraftJob']['status'], 'canceling',
        )

        # runner 启动时看到 canceling → 直接落定 canceled，不跑模型。
        execute_draft_job(job_id)
        job = CharacterDraftJob.objects.get(id=job_id)
        self.assertEqual(job.status, CharacterDraftJob.Status.CANCELED)

    def test_cancel_rejects_foreign_job(self):
        from chat.models import CharacterDraftJob

        job = CharacterDraftJob.objects.create(user=self.other_user)
        response = self.graphql(
            """
            mutation CancelDraft($id: ID!) {
              cancelCharacterDraftJob(id: $id) { id status }
            }
            """,
            variables={'id': str(job.id)},
            user=self.user,
        )
        self.assertIn('errors', response.json())

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    def test_same_fingerprint_carries_checkpoint(self, mock_start_thread):
        from chat.models import CharacterDraftJob

        first = self._start()
        job_id = int(first.json()['data']['startCharacterDraft']['id'])
        checkpoint_entry = {
            'signature': 'main::media/uploads/0.txt',
            'tier': 'main',
            'files': ['f0.txt'],
            'note': {'batch_summary': '已有笔记'},
        }
        CharacterDraftJob.objects.filter(id=job_id).update(
            status=CharacterDraftJob.Status.FAILED,
            checkpoint=[checkpoint_entry],
        )

        second = self._start()
        second_id = int(second.json()['data']['startCharacterDraft']['id'])
        self.assertNotEqual(second_id, job_id)
        resumed = CharacterDraftJob.objects.get(id=second_id)
        self.assertEqual(resumed.checkpoint, [checkpoint_entry])

    @unittest.mock.patch('chat.graphql.schema._generate_text')
    def test_single_shot_path_one_llm_call(self, mock_generate_text):
        """≥12 个文件且指定目标角色 → 预筛 + 单次请求直达，只调 1 次模型。"""
        from chat.graphql.schema import _compute_character_draft

        mock_generate_text.return_value = DRAFT_JSON
        uploads = [
            {
                'name': f's{i}.txt',
                'kind': 'text',
                'content': f'星野: 台词{i}\n旁白: 描述\n' * 10,
            }
            for i in range(15)
        ]
        draft, meta = _compute_character_draft(
            self.user, 'zh-CN', '目标角色名: 星野', uploads,
        )
        self.assertEqual(draft['name'], 'Job Drafted Character')
        self.assertEqual(meta['path'], 'single_shot')
        self.assertEqual(mock_generate_text.call_count, 1)
        prompt = mock_generate_text.call_args[0][1]
        self.assertIn('星野: 台词', prompt)

    @unittest.mock.patch('chat.graphql.schema._generate_text')
    def test_single_shot_retries_once_then_raises(self, mock_generate_text):
        """单请求输出无效 → 带提醒重试 1 次 → 仍失败则抛错（不回退多请求管线）。"""
        from chat.graphql.schema import _compute_character_draft

        mock_generate_text.return_value = '不是 JSON 的普通回复'
        uploads = [
            {
                'name': f's{i}.txt',
                'kind': 'text',
                'content': f'星野: 台词{i}\n旁白: 描述\n' * 10,
            }
            for i in range(15)
        ]
        with self.assertRaises(ValueError):
            _compute_character_draft(self.user, 'zh-CN', '目标角色名: 星野', uploads)
        # 恰好 2 次调用：首次 + 1 次重试。
        self.assertEqual(mock_generate_text.call_count, 2)

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    @unittest.mock.patch('chat.graphql.schema._generate_text')
    def test_runner_single_shot_then_result_cache_hits(
        self, mock_generate_text, mock_start_thread,
    ):
        """主链路端到端：首轮单请求出卡；同语料重新上传后再次生成直接命中
        结果缓存（stage=cache，0 次 LLM 调用）。"""
        from chat.draft_jobs import execute_draft_job
        from chat.models import CharacterDraftJob
        from chat.assets.store import AssetStore
        from django.core.files.uploadedfile import SimpleUploadedFile

        # 13 个语料文件（≥12 走单请求主链路；指定目标角色 星野）。
        def stage_uploads():
            ids = []
            for index in range(13):
                file_obj = SimpleUploadedFile(
                    f'scene_{index}.txt',
                    (f'星野: 台词{index}\n旁白: 描述\n' * 30).encode('utf-8'),
                    content_type='text/plain',
                )
                event, _ = AssetStore.upload(self.user, file_obj, f'scene_{index}.txt')
                ids.append(str(event.id))
            return ids

        mock_generate_text.return_value = DRAFT_JSON

        first = self.graphql(
            """
            mutation StartDraft($uploadIds: [String!], $textContext: String) {
              startCharacterDraft(uploadIds: $uploadIds, textContext: $textContext) { id status }
            }
            """,
            variables={'uploadIds': stage_uploads(), 'textContext': '目标角色名: 星野'},
            user=self.user,
        )
        first_id = int(first.json()['data']['startCharacterDraft']['id'])
        execute_draft_job(first_id)
        job = CharacterDraftJob.objects.get(id=first_id)
        self.assertEqual(job.status, CharacterDraftJob.Status.SUCCEEDED)
        self.assertNotEqual(job.stage, 'cache')
        self.assertEqual(job.result['name'], 'Job Drafted Character')
        # 单请求主链路：首轮恰好 1 次 LLM 调用。
        self.assertEqual(mock_generate_text.call_count, 1)

        # 二轮（同语料重新上传 → 相同内容哈希）：直接命中结果缓存。
        mock_generate_text.reset_mock()
        second = self.graphql(
            """
            mutation StartDraft($uploadIds: [String!], $textContext: String) {
              startCharacterDraft(uploadIds: $uploadIds, textContext: $textContext) { id status }
            }
            """,
            variables={'uploadIds': stage_uploads(), 'textContext': '目标角色名: 星野'},
            user=self.user,
        )
        second_id = int(second.json()['data']['startCharacterDraft']['id'])
        execute_draft_job(second_id)
        second_job = CharacterDraftJob.objects.get(id=second_id)
        self.assertEqual(second_job.status, CharacterDraftJob.Status.SUCCEEDED)
        self.assertEqual(second_job.stage, 'cache')
        self.assertEqual(second_job.result, job.result)
        mock_generate_text.assert_not_called()

    @unittest.mock.patch('chat.graphql.schema.start_draft_job_thread')
    def test_my_latest_draft_job_returns_own_latest(self, mock_start_thread):
        response = self._start()
        latest_id = response.json()['data']['startCharacterDraft']['id']

        query_response = self.graphql(
            """
            query {
              myLatestCharacterDraftJob { id status }
            }
            """,
            user=self.user,
        )
        self.assertEqual(
            query_response.json()['data']['myLatestCharacterDraftJob']['id'], latest_id,
        )

        # 其他用户查询不到。
        other_response = self.graphql(
            """
            query {
              myLatestCharacterDraftJob { id status }
            }
            """,
            user=self.other_user,
        )
        self.assertIsNone(other_response.json()['data']['myLatestCharacterDraftJob'])

    def test_sweep_stale_jobs_marks_dead_runners_failed(self):
        from chat.draft_jobs import sweep_stale_jobs
        from chat.models import CharacterDraftJob

        dead = CharacterDraftJob.objects.create(user=self.user, stage='analyze')
        CharacterDraftJob.objects.filter(id=dead.id).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )
        fresh = CharacterDraftJob.objects.create(user=self.user, stage='analyze')

        count = sweep_stale_jobs(self.user)
        self.assertEqual(count, 1)
        dead.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(dead.status, CharacterDraftJob.Status.FAILED)
        self.assertEqual(fresh.status, CharacterDraftJob.Status.RUNNING)

    def test_check_canceled_raises_and_finalizes(self):
        """_check_canceled：canceling → 落定 canceled 并抛出。"""
        from chat.draft_jobs import DraftJobCanceled, _check_canceled
        from chat.models import CharacterDraftJob

        job = CharacterDraftJob.objects.create(
            user=self.user,
            status=CharacterDraftJob.Status.CANCELING,
        )
        with self.assertRaises(DraftJobCanceled):
            _check_canceled(job)
        job.refresh_from_db()
        self.assertEqual(job.status, CharacterDraftJob.Status.CANCELED)
