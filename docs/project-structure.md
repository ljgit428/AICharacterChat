# 目录结构与职责规范（Project Structure）

> 本文档是目录系统的唯一权威说明：每个目录"是什么、放什么、不放什么"。
> 结构调整时先改这里，再动文件。

## 设计原则

1. **根目录只留入口**：`README.md`、部署配置和三大代码目录，其余一律归位。
2. **文档全部进 `docs/`**，按用途分四类（design / guides / benchmarks / versions），不再散落根目录或混进测试产物。
3. **一次性产物进 `tmp/`**：测试素材、截图验证输出、临时归档。整目录 gitignore，永不提交。
4. **运行时数据与代码分离**：用户上传（`media/`）、日志（`logs/`）、模型权重（`ml_models/`）都是机器本地状态，全部 ignore。
5. **Django app 分层清晰**：业务模块在 app 根，测试收进 `tests/` 包，独立工具脚本进 `scripts/`。

## 总览

```
PrisMate/
├── README.md                  # 项目门面：简介、快速开始、功能清单
├── docker-compose.yml         # 本地基础设施（Redis）
├── .github/workflows/         # CI：前端 ESLint + 后端 Flake8
│
├── backend/                   # Django 5.2 服务端
│   ├── chat/                  # ★ 唯一的业务应用
│   ├── prismate/              # 项目装配层（settings/celery/root urls）
│   ├── scripts/               # 独立运行的工具脚本（不随应用启动加载）
│   ├── manage.py              # Django 管理入口
│   ├── requirements*.txt      # 依赖清单（base / asr / tts 三档）
│   │
│   ├── media/                 # [ignored] 运行时用户上传 = MEDIA_ROOT
│   ├── static/                # [ignored] collectstatic 输出
│   ├── logs/                  # [ignored] 运行日志
│   ├── ml_models/             # [ignored] 本地 ML 权重（每角色一个子目录，如 seia_onnx）
│   ├── profile_out/           # [ignored] reduce 原型逐文件笔记输出
│   └── reduce_out/            # [ignored] reduce 管线最终 profile 输出
│
├── frontend/                  # Next.js 15 客户端
│   ├── src/app/               # 路由（App Router）：每条路由一个 page.tsx
│   ├── src/components/        # 全部 React 组件（扁平放置）
│   ├── src/constants/         # 编译期常量（index.ts + providerPresets.ts）
│   ├── src/hooks/             # 自定义 React hooks
│   ├── src/i18n/              # zh-CN / en-US 文案与 provider
│   ├── src/lib/               # 框架级客户端实例（Apollo）
│   ├── src/services/          # 浏览器侧服务封装（语音等）
│   ├── src/store/             # Redux Toolkit slices
│   ├── src/types/             # 共享 TS 类型
│   ├── src/utils/             # 纯函数工具（REST client 在此）
│   ├── public/                # 静态资源直出
│   │
│   ├── logs/                  # [ignored] dev server 日志
│   ├── scripts/               # [ignored] 一次性浏览器测试脚本
│   └── test-results/          # [ignored] Playwright 输出
│
├── docs/                      # ★ 全部文档（唯一入口见下表）
└── tmp/                       # [ignored] 本地一次性产物，永不提交
    ├── test-assets/           #   手工测试素材（音频、剧本 txt、视频帧）
    ├── gui-test-screenshots/  #   GUI 黑盒验证截图 + mock LLM server
    └── archive/               #   已废弃的本机文件存档
```

## `backend/chat/` 内部分层

| 成员 | 职责 |
|---|---|
| `models.py` / `serializers.py` | ORM 模型与 DRF 序列化器 |
| `views.py` / `urls.py` / `file_views.py` | REST 接口层 |
| `graphql/` | Strawberry schema 与 resolver（角色 CRUD、草稿生成） |
| `tasks.py` | Celery 任务：LLM 回复生成、记忆管线 |
| `soul.py` | 灵魂/人格系统（prompt 组装核心） |
| `character_reduce.py` | 大批量上传的 map-reduce 角色提取管线 |
| `asr.py` / `tts.py` | 实时语音输入/回复的 provider 抽象 |
| `attachments.py` / `search.py` / `model_catalog.py` | 附件限额、联网搜索、模型目录 |
| `authentication.py` / `authentication_views.py` / `middleware.py` | 鉴权与中间件 |
| `constants.py` / `apps.py` / `admin.py` | 应用常量与装配 |
| `memory/` | 长期记忆子系统（manager/prompts/Memory Tools 文件系统后端） |
| `migrations/` | ORM 迁移（自动生成，勿手改） |
| `management/commands/` | `manage.py` 自定义命令（如 `run_character_reduce`） |
| `tests/` | 测试包：`test_api.py` / `test_memory.py` / `test_realtime.py` |

## `docs/` 分类法

| 子目录 | 放什么 | 现有内容 |
|---|---|---|
| `docs/design/` | 系统/功能设计规格（写代码前定稿的"为什么&怎么做"） | memory-system-spec · memory-system-v2 · natural-chat-design · chat-ui-redesign-spec |
| `docs/guides/` | 操作手册、日常命令速查 | daily-commands |
| `docs/benchmarks/` | 性能/延迟实测报告 | latency-v0.1.3 |
| `docs/versions/` | 版本发布记录 | v0.1.2 |
| `architecture.md` | 全链路数据流参考（原根目录 ARCHITECTURE.md） | — |
| `project-structure.md` | 本文：目录职责权威说明 | — |

## 新东西放哪里（路由规则）

- 新设计文档 → `docs/design/<feature>-design.md`
- 新 REST/GraphQL 端点 → `chat/views.py` 或 `chat/graphql/`，路由挂到对应 urls
- 新测试 → `chat/tests/test_<域>.py`（不要再造 `tests_xxx.py` 散在 app 根）
- 新前端组件 → `src/components/`；新常量 → `src/constants/`
- 新工具脚本（手动运行、不进 CI）→ `backend/scripts/`
- 手工测试用的音频/文本素材 → `tmp/test-assets/`，用完可删
- 模型权重下载目标 → `backend/ml_models/<角色>_onnx/`。目录只是本机存放
  习惯，真正生效的是各角色「语音模型」设置里的 `onnx_model_dir`——每个
  角色指向自己的模型，没有全局环境变量兜底。

## 本次规范化迁移对照（v0.1.3）

| 旧位置 | 新位置 | 说明 |
|---|---|---|
| `ARCHITECTURE.md` | `docs/architecture.md` | 数据流参考归入 docs |
| `spec/*.md` | `docs/design/` | 设计规格统一入口 |
| `everydaycommand.md` | `docs/guides/daily-commands.md` | 速查手册归入 docs |
| `docs/latency-v0.1.3.md` | `docs/benchmarks/latency-v0.1.3.md` | 实测报告归类 |
| `test/`（根目录） | `tmp/test-assets/` | 测试素材移出仓库视野；其中的 `chat-ui-redesign-spec.md` 提升为 `docs/design/` |
| `gui-test-screenshots/` | `tmp/gui-test-screenshots/` | 截图与 mock server 归入 tmp |
| `backend/db.sqlite3`、`backend/cookies.txt` | `tmp/archive/` | 陈年调试残留归档 |
| `backend/models/` | `backend/ml_models/` | 避免 Django models 命名冲突；角色 `tts_config` 里指向旧目录的绝对路径已同步修正（本机库） |
| `backend/chat/tests*.py` | `backend/chat/tests/` 包 | app 根只留业务模块 |
| `frontend/src/constants.ts` | `frontend/src/constants/index.ts` | 与 `constants/providerPresets.ts` 同居一处；`@/constants` 导入不受影响 |
