# Memory System v2 — 记得住 · 会成长 · 看得见

> Status: **设计稿 — 未实现。** v1（`spec/memory-system-spec.md`）已落地的
> 部分保持不变；本文档只描述增量改动，冲突时以本文档为准。
>
> 需求由项目作者于 2026-08 会话中确认，措辞如下：
> 「先做到能记住和成长，用户要能看见记忆。遗忘要少做，要遗忘就要做到
> 合理还要有个开关。」
>
> 参考调研：waku-agent（检索门 + 定期固化）、Cyrene-Agent（L0/L1/L2 分层 +
> 冲突判断）、AnySoul docs（用进废退 + 沉默而非删除 + 认知时钟）。
> 结论性取舍记录在 §7「明确不做」。

## 0. 需求基线与既定决策

| # | 决策 | 结论 |
|---|------|------|
| D1 | 话题模式 / 聊天模式的关系 | 记忆挂在角色（`CharacterMemoryItem.character`），两种模式的会话读写同一库。**维持现状，不改。** |
| D2 | 存储形态 | 维持**结构化条目**（section + description + history）。**不做日记式按日期分段文本**——追加式文本无法修正旧事实，是 migration 0008–0022 已走过的弯路。日期作为条目正文规范（绝对日期）+ 展示层排序维度。 |
| D3 | 写入时机 | 维持**每轮 AI 回复后一次提取任务**。会话结束批量方案在角色扮演场景不成立（会话边界模糊），且会推迟"成长可见"的反馈。成本优化交给 §3.1 的门控预留。 |
| D4 | 遗忘 | **默认零自动删除。** 唯一删除路径是提取 agent 发现矛盾时的纠错（v1 已有，保留）。定期整理只合并不删除（§6）。自动衰减本期不实现，仅留设计位（§6.2）。 |
| D5 | 术语 | 不引入 L0/L1/L2 等外部术语。"最重要的分区优先注入"只是注入排序策略（§3.2），不是新架构。 |

## 1. 现状问题清单（2026-08 代码核实）

| 级别 | 问题 | 代码定位 |
|------|------|----------|
| P0 | **会话第一条用户消息被静默丢弃**：前端首条发送 `message:''` + `start_conversation:true`（`ChatInterface.tsx:242,302`），后端空会话走 `generate_greeting` 分支不保存消息（`views.py:_prepare_chat_turn`）。后果：① 用户第一句话（常含自我介绍）永远进不了历史与记忆提取；② 这是作者自测「发消息看不见记忆 update」的直接原因。2026-08-23 已用 mock LLM 全链路复现。 | `frontend/src/components/ChatInterface.tsx`；`backend/chat/views.py` |
| P0 | 记忆任务无 broker 降级：worker 未运行时 `.delay()` 静默失败（仅 log warning），开发环境表现为"发了消息永远没有记忆" | `backend/chat/tasks.py:2525`（对照：标题任务有 `_dispatch_session_title_update` 同步降级，`tasks.py:2440`） |
| P0 | 注入截断 900 字符：十几条之后记忆对 AI 不可见，用户在 /memory 页看得到、AI 却"失忆" | `STREAM_MEMORY_SECTION_LIMIT = 900`，`backend/chat/tasks.py:72`；使用点 `tasks.py:1877` |
| P1 | **CRUD 工具参数异常会中止整轮任务**：工具执行抛错（如缺字段）直接冒泡到任务顶层 → `status:error`，本轮已产生的合法动作一并丢失、无 SSE 事件。v1 spec §5.6 本要求"返回驳回字符串让模型重试"。2026-08-23 复现（mock 发错参数名即触发） | `tasks.py:_collect_memory_actions` / `_execute_memory_crud_tool` |
| P1 | 前端零反馈：SSE toast 从未实现（前端无任何 `memory_update` 引用）；后端 `_publish_memory_event` 发布的 Redis 频道也**没有订阅方** | `backend/chat/tasks.py:2130`（发布无人消费）；`frontend/src/**` grep 无命中 |
| P1 | 成长缺失：无关系状态、无共同经历的结构化承载 | — |
| P2 | 无定期整理：碎片化只增不减（merge 仅在单轮提取时偶发触发） | — |
| P2 | `GET .../memory/narrative` 与 `audit` 接口仅在路由保留名中出现，未实现 | `backend/chat/views.py:198` |

## 2. 设计原则

1. **不新增依赖**：不上向量库、不上 embedding、不加 Python 包。全部改动落在现有 Django + Celery + React 栈内。
2. **人设不可被 AI 修改**：成长只发生在记忆条目层，`Character` 的 persona 字段仍为用户专属写。（v1 §2.2 结论继续有效。）
3. **数据库仍是唯一事实源**：`wiki/memory.md` 与 narrative 都只是渲染视图。
4. **每个 Phase 独立可验收**，顺序执行，随时可以停在某个 Phase。

---

## 3. Phase 1 — 记得住（可靠性修复）

### 3.1 Broker 降级（修 P0-1）

新增调度助手，替换 `tasks.py:2525` 处的内联 try/except：

```python
# backend/chat/tasks.py
@shared_task(bind=True)
def sync_long_term_memory(self, ...):   # 任务本体不动

def dispatch_memory_sync(chat_session, ai_message, character):
    """先投递 broker；失败且允许时同步执行（开发环境无 Redis/worker 也能写入）。"""
    try:
        sync_long_term_memory.delay(
            message_id=ai_message.id,
            chat_session_id=chat_session.id,
            character_id=character.id,
        )
    except Exception as exc:
        logger.warning('Memory enqueue failed (%s); inline fallback=%s',
                       exc, settings.MEMORY_SYNC_INLINE_FALLBACK)
        if settings.MEMORY_SYNC_INLINE_FALLBACK:
            sync_long_term_memory.apply(
                args=[ai_message.id, chat_session.id, character.id],
                throw=False,
            )
```

- 新增设置 `MEMORY_SYNC_INLINE_FALLBACK`（`BoolField`，默认 `True`；生产环境建议关掉并在 `.env.template` 注明）。
- **代价说明**：inline 回调会把整段提取（含最多 8 轮工具往返）阻塞在回复收尾路径上。流式路径下 `done` 事件在此之前发出，用户感知为"回复结束后连接多挂几秒"，可接受；这是与静默丢数据之间的显式取舍。
- 顺带补齐可观测性：任务返回值已有 `{status, actions}`，增加 `logger.info` 的 `reason` 字段透传（skipped 原因），方便 §8 的自测流程直接读日志定性。

### 3.2 截断修复 + 注入优先级（修 P0-2）

`_build_stream_memory_prefetch` 改为预算感知的组合：

```python
# backend/chat/memory/manager.py 新增签名
def render_narrative(self, *, budget_chars: int | None = None) -> tuple[str, bool]:
    """返回 (narrative, truncated)。超预算时：关系 → 里程碑 全文保住，
    其余分区按 updated_at 新→旧逐条填入剩余预算，装不下的整条丢弃。"""
```

- `STREAM_MEMORY_SECTION_LIMIT` 900 → **6000**（约容纳 100 条 60 字条目；现代模型上下文下仍属保守值）。
- 分区优先级常量放 `memory/constants.py`：`RELATIONSHIP_SECTION = '关系'`、`MILESTONE_SECTION = '里程碑'`（Phase 2 复用）。
- `truncated` 标志随响应暴露给 /memory 页（§5.2），截断从"静默失忆"变为"可见的容量提示"。
- **为 L2 检索留好接缝（零成本保险）**：prompt 侧取记忆只允许经过一个入口
  `MemoryManager.get_prompt_memory(character, *, budget_chars)`（本期的"全量+优先级裁剪"
  也实现为该函数的默认策略）。将来切换为检索式注入时，只替换这一个函数的实现，
  prompt 组装、聊天管线、/memory 预览均不动。

**验收**：构造 120 条记忆的角色，prompt 中「关系」「里程碑」完整、其余按新鲜度截到预算内；`truncated=True` 在接口可见。

### 3.3 首条消息修复（修 P0-1，2026-08-23 实测新增）

约定：**只要用户带了非空文本，就一定作为真实消息保存并回复**；开场白仅在
"显式 `start_conversation` 且无文本"时生成。

- 后端 `_prepare_chat_turn`：`generate_greeting` 改为
  `start_conversation and not message_content and not attachments`
  （即用户有话时 greeting 让位）；其余逻辑不变。
- 前端 `ChatInterface.tsx:302`：首条发送改为
  `message: trimmedInput, start_conversation: false`——首句得到正常回复，
  而不是被替换成开场白。
- 兼容性：老会话（已有消息）行为不变；纯开场请求（空文本）行为不变。

### 3.4 工具驳回代替任务中止（修 P1-工具异常）

`_execute_memory_crud_tool` 外包一层 try/except：任何 `ValueError`
（缺字段、超长、id 不存在）转为
`{'status': 'rejected', 'error': str(exc)}` 作为 tool 结果回给模型继续本轮
ReAct 循环；只有基础设施级异常才让任务失败。对齐 v1 spec §5.6 的原始设计。

---

## 4. Phase 2 — 会成长（约定分区）

数据模型**零迁移**：成长完全通过两个约定分区表达，复用现有 `section` 自由字段与 `description_history` 版本链。

### 4.1 提取 prompt 规则（`memory/prompts.py`）

`COLD_START_SYSTEM` / `UPDATE_SYSTEM` 追加一段「特殊分区规则」：

```
特殊分区:
- 「关系」: 此分区永远只允许一条记忆，描述当前关系的阶段与氛围
  （例: 已从陌生变得亲近，开始互相开玩笑）。关系变化时必须用
  update_memory 更新该条，禁止新建第二条。
- 「里程碑」: 只追加带绝对日期开头的共同经历（例: 2026-08-23 第一次一起看了流星雨）。
  只在两条确实描述同一事件时才允许 merge；不得因为时间久远而删除。
```

### 4.2 Manager 层硬约束（防 prompt 失效）

`MemoryManager.create_item`：当 `section == RELATIONSHIP_SECTION` 且该分区已有条目时，
**自动转写**为对最新一条的 `update_item`（history 追加 reason
`"auto-redirect: single-entry section"`，audit 记 UPDATE）。prompt 规则是第一道防线，
manager 是第二道，两层都失效也不产生脏数据。

### 4.3 为什么这样就算"成长"

- 关系条目的 `description_history` 天然就是**关系变化史**（每次 old→new 带 reason 和时间戳），前端无需任何新表即可画时间线；
- 里程碑分区天然就是**共同经历年表**（append-only + 绝对日期）；
- 人设字段零接触，符合设计原则 2。

---

## 5. Phase 3 — 看得见（可见性）

### 5.1 聊天页更新提示（轮询方案，非 SSE）

**取舍依据**：SSE 链路目前三处缺失（后端无订阅方、流生成器未挂载频道、前端无监听），
而"每轮结束后拉一次计数"一行接口都不用加——现有
`GET /api/characters/{id}/memory` 已返回 `{count, sections, wiki_markdown}`。

行为：AI 回复完成（stream `done`）后，前端对该角色的 memory count 做一次比对；
count 增加 → composer 附近弹 chip：

> 🧠 记忆 +2 · 点击查看 →（链接 `/memory?character=<id>`）

- 实现点：共享聊天组件内一个 `useEffect`（发送流程完成后触发），两套模式（话题/聊天）同时受益；
- SSE toast（v1 spec §7）降级为未来增强项，本版不做。

### 5.2 /memory 页增强

| 区块 | 内容 | 数据来源（全部现成） |
|------|------|---------------------|
| 关系卡片（页面顶部） | 当前关系描述 + 可展开的变化时间线（old→new + reason + 时间） | 「关系」分区条目及其 `description_history` |
| 里程碑时间线 | 按条目正文的绝对日期渲染纵向年表 | 「里程碑」分区条目 |
| AI 视角预览按钮 | 弹层展示实际注入 prompt 的 narrative 原文；`truncated=true` 时顶部黄条提示"超出 AI 可见预算，以下为截断后内容" | 新端点 §5.3 |
| 容量提示 | 条目数接近预算时显示常规提示文案 | list 响应 + `truncated` |

### 5.3 补齐 narrative 端点（修 P2-6）

```
GET /api/characters/{id}/memory/narrative
→ { "narrative": str,          # 即 §3.2 render_narrative(budget_chars=6000) 的产物
     "truncated": bool,
     "count": int,
     "last_updated": iso8601 | null }
```

权限沿用既有 owned-by 门控。`audit` 端点同样只欠实现（表和写入都在），
顺手补上：`GET .../memory/audit` 返回最近 50 条 `MemoryAuditLog`。

### 5.4 i18n

`zh-CN.ts` / `en-US.ts` 各新增约 8 个 key（chip 文案、关系卡片标题、时间线标签、
AI 视角、截断警告等）。

**验收**：发一条含新事实的消息后，聊天页出现 chip 且数字正确；/memory 页三个新区块
对老数据（无关系/里程碑分区）优雅降级为空态。

---

## 6. Phase 4 — 整理与遗忘预留

### 6.1 定期整理（合并，不删除）

Celery beat 周期任务 `consolidate_character_memory(character_id)`：

- 输入：单个角色的全部条目（一次一个角色的锁，避免并发写冲突）；
- 行为：仅调用 `merge_items` 合并语义重复/高度相近条目（合并保留双方 history，可审计可追溯），清理空分区名拼写变体；
- **绝不 delete**；矛盾纠错仍只属于每轮提取任务；
- 开关：`UserProfile.allow_memory_consolidation`（默认 `True`，可在设置关闭）——这是 D4"要遗忘就要有开关"原则在整理动作上的落实；
- 触发节奏：先用 beat 每日低频跑（凌晨、按角色分片），观察后再考虑改为按写入量触发。

### 6.2 自动衰减 — 本期不实现，仅留设计位

若未来启用，约束条件一次性写死在此（防止将来拍脑袋上线）：

1. 全局开关 `allow_memory_decay`，**默认 OFF**；
2. 只归档（退出注入 + 归档区可见可恢复），**永不删除**；
3. 时钟用**认知时钟**（AnySoul 式）：衰减进度跟随记忆写入活动推进，不用墙钟天数——用户两周不来，感情不清零；
4. 强度信号：被注入即 +1，长期未注入降级。

## 7. 明确不做（Non-goals）

| 项 | 理由 |
|----|------|
| 向量检索 / pgvector / embedding | 条目规模到几百之前收益小；Cyrene 证明"无 embedding 优雅降级"可行，说明它是可选增强不是地基 |
| L0/L1/L2 分层：**分阶段吸收效果，不引入术语**（2026-08-23 修正：作者原意是"不了解用法与效果"，并非拒绝；同日作者确认设计前提应为**记忆无限增长**） | 三层的*效果*拆解——L0 核心常驻＝§3.2 优先级注入 + §4 关系分区（本期实现）；L1 近期状态＝会话历史（已有）；L2 长尾语义检索＝**路线图必做项而非可选项**：按每天 30 轮 × 平均 0.3~0.5 条/轮估算，活跃用户一年即积累数千条，远超任何注入预算。终局形态为双引擎——①检索（向量+关键词取相关 top-K 注入）②固化（定期把陈年碎片合并为分区摘要，摘要常驻保底、细节按需检索），上下文占用恒定而记忆无限延长；§6.1 整理任务即固化引擎雏形，「里程碑」时间线建议保留细节不参与压缩。**阈值只决定紧迫度，不改变必做性**：条目 > 100 或 narrative 持续顶满预算即启动实现（pgvector + embedding，候选 BGE-M3 本地量化版 or API）。在此之前维持"全量+裁剪"注入；L0/L1/L2 命名本身不进入代码与 UI |
| 日记式按日期分段文本存储 | 见 D2；无法修正旧事实 |
| 会话结束批量写入 | 见 D3；会话边界模糊 + 反馈延迟 |
| AI 修改人设/灵魂文档 | v1 §2.2 结论；migration 0020 已烧过一次 |
| AnySoul 式克隆 / 混合 / 随机游走联想 | 角色运营功能而非基础设施，进 roadmap 不进本版 |
| SSE 实时推送 toast | 三处链路缺口 vs 一行轮询；降级为未来增强 |

## 8. 测试计划

- **单元**：`dispatch_memory_sync` broker 失败 → inline 执行成功（mock delay 抛错）；`render_narrative(budget_chars)` 超预算时「关系」「里程碑」保全 + `truncated` 正确；关系分区 create→update 自动转写；narrative/audit 端点权限。
- **Prompt 快照**：更新后的 COLD_START/UPDATE golden file（含特殊分区规则段）。
- **手工自测脚本**（写给作者本人，2026-08-23 已用 mock LLM 实测通过 ✅）：
  1. ~~不启动 worker~~ → fallback 待实现（§3.1）；当前版本必须启动 worker：
     `python -m celery -A prismate worker --loglevel=info --pool=solo -c 1`
  2. **第一条消息会被开场白机制吞掉（§3.3 修复前）**——请发第二条再验证记忆；
  3. 发"你记住哦，我是一名护士，经常上夜班"→ /memory 页出现「身份」条目 ✅；
  4. worker 日志 `skipped: private_mode` ✅（私密会话开关已实测拦截）。

## 9. 实施顺序

| Phase | 改动文件（预估） | 前置依赖 |
|-------|------------------|----------|
| 1 | `tasks.py`、`memory/manager.py`、`memory/prompts.py`(无)、`settings.py`、`.env.template`、`tests_memory.py` | 无 |
| 2 | `memory/prompts.py`、`memory/manager.py`、`memory/constants.py`(新) | 无（可与 1 并行） |
| 3 | `views.py`(narrative/audit)、`frontend/src/components/ChatInterface.tsx` 或聊天容器、`app/memory/page.tsx`、`utils/api.ts`、`i18n/*` | Phase 1（narrative 依赖预算逻辑）、Phase 2（区块依赖约定分区） |
| 4 | `tasks.py`(consolidate task)、`celery.py` beat 配置、`models.py`(UserProfile 开关)+migration | Phase 2 |

每个 Phase 合并为独立 commit，遵循现有 conventional commit 风格
（`feat(memory): ...` / `fix(memory): ...`）。
