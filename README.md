# AI for Foreign Language Learning (AIFL)

全栈本地化外语学习平台：词汇学习、作文批改、实时语音对话、课堂实时助教、学情分析。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B%20%7C%203.14-blue)
![Vue](https://img.shields.io/badge/Vue.js-3.4-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-teal)
![Electron](https://img.shields.io/badge/Electron-31.x-slateblue)

AIFL 是一个运行在桌面端（Electron）的外语学习应用。设计原则是端云协同、数据留在本地：学习数据（作文、录音、学习轨迹）默认存本地 SQLite，AI 推理优先走本地 LM Studio，仅在需要更强模型时调用云端 Kimi API。

技术栈：FastAPI + SQLModel 后端，Vue 3 + Electron 前端，本地 LLM（LM Studio / Qwen3.5-9B）与云端 Kimi 双路路由，ASR 用 SeamlessM4T（CPU），TTS 用 Kokoro（CPU），OCR 用 PaddleOCR。可选接入 Redis / Elasticsearch / Neo4j / MinIO，不装也能跑。

## 目录

- [功能](#功能)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [后端配置](#后端配置)
- [依赖服务](#依赖服务)
- [代码结构与设计](#代码结构与设计)
- [API 速查](#api-速查)
- [开发指南](#开发指南)
- [硬件推荐](#硬件推荐)
- [故障排查](#故障排查)

## 功能

### 学生端

| 模块 | 功能 | 实现位置 |
|------|------|---------|
| 词汇 | 查词、OCR 识词、LLM 生成释义与 CEFR 分级、SM-2 间隔复习、知识图谱关联 | `routers/vocab.py`、`domain/srs/` |
| 作文 | 文本或图片（OCR）提交，六维度评分（内容/结构/词汇/语法/流畅度/逻辑），错误纠正与全文润色 | `routers/essays.py`、`domain/essay_scoring.py` |
| 口语对话 | WebSocket 实时语音对话，云端与本地 LLM 竞速响应，支持打断续接 | `main.py` (`/ws/v1`)、`voice_stream.py` |
| 学习记录 | 学习时长统计、能力雷达、薄弱点分析 | `routers/learning.py` |

### 教师端

| 模块 | 功能 | 实现位置 |
|------|------|---------|
| 实时助教 (RTA) | 屏幕感知 + 语音唤醒（"Hi Helix"），LLM 结构化决策是否介入，默认静默弹窗、必要时 TTS 播报 | `domain/realtime_assistant/session.py` |
| 学情分析 | 多维度班级/学生报告、周报生成、干预任务 | `application/analytics/` |
| 管理面板 | 用户管理、配置热更新、服务健康检查、日志查看 | `interfaces/admin_router.py` |
| 悬浮窗 | Ctrl+Shift+S 截图查词、Ctrl+Shift+C 划词查词 | `electron/main/managers/system-integration-manager.ts` |

## 系统架构

```
┌─────────────────────────────┐    ┌─────────────────────────────────────┐
│   前端 (Electron + Vue 3)    │    │           后端 (FastAPI)             │
│   app/v5/                    │    │   backend_fastapi/app/               │
│  ┌───────────────────────┐   │    │  ┌─────────────────────────────────┐ │
│  │ Vue 3 SPA (教师/学生)  │   │◄──►│  │ Routers / Interfaces (REST+WS)   │ │
│  │ 词汇/作文/对话/分析    │   │ WS │  │ vocab/essays/voice/analytics/    │ │
│  │ RTA 悬浮窗/设置面板    │   │    │  │ admin/auth/realtime-assistant    │ │
│  └───────────────────────┘   │    │  └─────────────────────────────────┘ │
│  ┌───────────────────────┐   │    │  ┌─────────────────────────────────┐ │
│  │ Electron Main          │   │    │  │ Application / Domain             │ │
│  │ 托盘/全局快捷键/overlay│   │    │  │ 词汇生成/作文评分/SM-2/RTA 会话  │ │
│  └───────────────────────┘   │    │  │ 学情分析编排                     │ │
└─────────────────────────────┘    │  └─────────────────────────────────┘ │
                                   │  ┌─────────────────────────────────┐ │
                                   │  │ Infrastructure                   │ │
                                   │  │ LLM 路由(本地↔云端竞速)          │ │
                                   │  │ TTS: Kokoro → Edge-TTS → 静音    │ │
                                   │  │ ASR: SeamlessM4T (CPU)           │ │
                                   │  │ OCR: PaddleOCR → RapidOCR        │ │
                                   │  └─────────────────────────────────┘ │
                                   └──────────────────────────────────────┘

数据层: SQLite/SQLModel (主业务) + 可选 Redis (缓存/队列) / Elasticsearch (词汇全文搜索)
        / Neo4j (知识图谱) / MinIO (对象存储)

AI 推理层: 本地 LM Studio (Qwen3.5-9B) ↔ 云端 Kimi API (moonshot-v1-auto)，竞速或降级
```

## 快速开始

### 环境要求

| 组件 | 最低 | 推荐 |
|------|------|------|
| OS | Windows 10 / Ubuntu 20.04 | Windows 11 |
| Python | 3.10 | 3.13+ |
| Node.js | 18 | 20 LTS |
| GPU | 无（CPU 模式） | 16GB 显存（本地 LLM） |
| 内存 | 16GB | 32GB+ |

### 1. 克隆并安装后端

```bash
git clone https://github.com/CUMT-Alethic-Insight-Lab/AIforLanguageLearning.git
cd AIforLanguageLearning/backend_fastapi

python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

pip install -e ".[dev]"
```

### 2. 配置环境变量

在 `backend_fastapi/.env` 中配置（全部以 `AIFL_` 为前缀）：

```env
AIFL_APP_ENV=development
AIFL_PORT=8012
AIFL_DATABASE_URL=sqlite:///./data/app.db
AIFL_JWT_SECRET=change-this-in-production

# 本地 LLM (LM Studio)
AIFL_LLM_BASE_URL=http://127.0.0.1:1234/v1
AIFL_LLM_API_KEY=lm-studio
AIFL_LLM_MODEL=local-model

# 可选基础设施
AIFL_REDIS_URL=redis://localhost:6379/0
AIFL_ES_URL=http://localhost:9200
AIFL_NEO4J_URL=bolt://localhost:7687
AIFL_MINIO_ENDPOINT=localhost:9000

# 语音 / 实时助教
AIFL_ENABLE_ASR=true
AIFL_ASR_BACKEND=seamless
AIFL_RTA_ENABLED=true
AIFL_RTA_LLM_MODEL=moonshot-v1-auto
```

### 3. 启动 LM Studio

1. 安装 [LM Studio](https://lmstudio.ai/)
2. 加载 `Qwen3.5-9B-Instruct`（GGUF）
3. 开启 Local Server（默认端口 1234）

注意：不建议把 35B 级 MoE 模型设为默认对话模型。系统的 `_rank_models` 排序会自动优先选择小模型，但如果 `runtime_config.json` 里缓存了错误的模型 ID，可能误调大模型。

### 4. 启动

```powershell
# 可选：启动本地基础设施 (Redis / ES 等)
./scripts/start_infra_native.ps1

# 后端
cd backend_fastapi
uvicorn app.main:app --host 0.0.0.0 --port 8012 --reload

# 前端（另开终端）
cd app/v5
npm install
npm run dev
```

一键脚本：`./scripts/start.ps1` 会检查环境并同时拉起前后端。

### 5. 验证

- 前端：`http://localhost:5173`
- API 文档：`http://localhost:8012/docs`
- 健康检查：`GET http://localhost:8012/health`

## 后端配置

### 两套配置机制

| 机制 | 位置 | 用途 |
|------|------|------|
| Settings | `app/settings.py` | 启动时加载，环境变量 > `.env` > 默认值，Pydantic Settings 管理 |
| Runtime Config | `data/runtime_config.json` | 运行时热更新：模型选择、温度等，前端设置面板直接写入 |

### LLM 模型解析链

调用 `chat_complete()` 未显式传 `model` 时，按以下顺序解析：

1. `runtime_config.json` 的场景模型 `models.scene.{scene}`
2. `runtime_config.json` 的主模型 `models.primary`
3. Settings 默认模型 `settings.llm_model`
4. 查询 LM Studio `/models`，按 `_rank_models` 排序取最优（小模型优先；名称含 vl +200、thinking +300、coder +150、a3b/moe +50 的惩罚分）

### 语音对话的 LLM 策略

语音链路（`main.py` 的 `/ws/v1`）采用**竞速**：云端 Kimi（配置了 `KIMI_API_KEY` 时）与本地 LM Studio 并发请求，首 token 先到者胜出，慢的一方取消。模型名：

```python
voice_cloud_model = "moonshot-v1-auto"   # Kimi 云端
voice_local_model = "qwen3.5-9b"         # 本地 LM Studio
```

### 实时助教 (RTA) 决策流程

1. 触发源：屏幕帧变化 / ASR 语音 / 鼠标框选 / 唤醒词
2. 预筛选：`SmartTriggerEngine` + `ProactiveSuggestionEngine` 检测关键词与信号
3. LLM 决策：要求返回结构化 JSON：
   ```json
   {
     "should_intervene": true,
     "intervention_type": "hint",
     "content": "简短建议",
     "use_tts": false,
     "urgency": "medium"
   }
   ```
4. `use_tts=false` 时仅弹窗显示，`true` 时才合成 Kokoro 语音播报

RTA 默认用云端 Kimi，可通过 `AIFL_RTA_LLM_BASE_URL` 等环境变量切到本地。

## 依赖服务

### 必需

| 服务 | 用途 |
|------|------|
| Python 3.10+ | 后端运行时 |
| Node.js 18+ | 前端构建 |
| LM Studio | 本地 LLM 推理（端口 1234） |
| SQLite | 主数据库（内置） |

### 可选（不装时自动降级）

| 服务 | 用途 | 端口 | 降级行为 |
|------|------|------|---------|
| Redis | 缓存、Celery 队列 | 6379 | 本地内存字典 |
| RabbitMQ | Celery broker | 5672 | 同步执行 |
| Elasticsearch | 词汇全文搜索 | 9200 | 数据库 LIKE 查询 |
| Neo4j | 知识图谱 | 7687 | 跳过图谱推荐 |
| MinIO | 对象存储 | 9000 | 本地文件系统 |
| Celery Worker | 异步任务（作文批改、周报） | - | 同步阻塞执行 |

## 代码结构与设计

### 目录结构

```
├── app/v5/                        # 前端 (Vue 3 + Electron)
│   ├── electron/main/             # 主进程：窗口/托盘/IPC 管理
│   ├── public/overlay.html        # RTA 悬浮窗页面
│   └── src/
│       ├── views/                 # 页面组件
│       ├── components/            # 通用组件
│       ├── stores/                # Pinia 状态
│       └── services/              # API 封装
│
├── backend_fastapi/
│   ├── app/
│   │   ├── main.py                # 应用入口 + 语音 WebSocket (/ws/v1)
│   │   ├── settings.py            # Pydantic Settings
│   │   ├── llm.py                 # LLM 调用封装 + 模型解析
│   │   ├── model_router.py        # 本地/云端路由
│   │   ├── tts.py                 # Kokoro → Edge-TTS → 静音
│   │   ├── voice_stream.py        # ASR (SeamlessM4T) + VAD
│   │   ├── ocr.py                 # PaddleOCR → RapidOCR
│   │   ├── runtime_config.py      # 运行时配置热更新
│   │   ├── prompts/               # Jinja2 Prompt 模板
│   │   ├── domain/                # 领域层
│   │   │   ├── models.py          # User / VocabularyItem / LearningRecord 等
│   │   │   ├── srs/               # SM-2 间隔重复
│   │   │   ├── realtime_assistant/# RTA：session / trigger / suggestion / screen
│   │   │   └── classroom/         # Classroom / ClassEnrollment
│   │   ├── application/           # 应用层：学情分析编排、周报、日报
│   │   ├── interfaces/            # 接口层：admin / auth / analytics / RTA 等 router
│   │   ├── routers/               # 业务路由：vocab / essays / voice / learning / system
│   │   └── infrastructure/        # 安全、消息队列、ES/Neo4j 客户端
│   ├── data/                      # SQLite 数据库 + runtime_config.json
│   ├── tests/                     # pytest
│   └── alembic/                   # 数据库迁移
│
├── docs/                          # 架构与开发文档
├── scripts/                       # start.ps1 / start_infra_native.ps1 / check-services.ts
└── shared/types/                  # 前后端共享类型
```

### 分层约定

`interfaces/routers → application → domain → infrastructure`，只允许上层依赖下层。

### 语音 WebSocket 协议 (`/ws/v1`)

```
Client                             Server
  │────── AUDIO_START ──────────────►│  开始一轮对话
  │────── AUDIO_CHUNK (binary) ─────►│  音频流
  │                                  │  VAD → ASR → LLM(竞速) → TTS
  │◄───── ASR_PARTIAL / ASR_FINAL ───│  转写中间/最终结果
  │◄───── LLM_TOKEN / LLM_RESULT ────│  流式/完整回复
  │◄───── TTS_CHUNK / TTS_RESULT ────│  音频分片/完毕
  │◄───── TASK_FINISHED ─────────────│  本轮结束
  │────── AUDIO_BARGE_IN ───────────►│  用户打断：取消当前 TTS，
  │                                  │  未播报内容注入下一轮上下文
```

### 数据模型

- `User`、`StudentProfile`、`VocabularyItem`、`LearningRecord`、`LearningPath` — `app/domain/models.py`
- `ConversationEvent`、`EssaySubmission` — `app/models.py`
- `Classroom`、`ClassEnrollment` — `app/domain/classroom/models.py`
- `PromptRegistry`（Prompt 模板版本管理）— `app/domain/prompt_management/models.py`

## API 速查

### REST

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/vocab/lookup` | POST | 查词，返回结构化释义 |
| `/v1/vocab/lookup-ocr` | POST | 图片 OCR 后查词 |
| `/v1/essays/grade` | POST | 作文批改（六维度评分） |
| `/api/voice/generate-prompt` | POST | 按场景生成对话开场白 |
| `/api/auth/login` | POST | 登录，返回 JWT |
| `/api/admin/services` | GET | 服务健康检查 |
| `/health` | GET | 存活探针 |

### WebSocket

| 端点 | 说明 |
|------|------|
| `/ws/v1` | 语音对话主链路 |
| `/api/v1/realtime-assistant/ws` | 实时助教 |

完整文档见启动后的 `http://localhost:8012/docs`。

## 开发指南

```bash
# 后端
cd backend_fastapi
pytest                      # 单元测试（asyncio_mode=auto）
ruff check app/             # 代码检查 (line-length=100)
alembic revision --autogenerate -m "change" && alembic upgrade head

# 前端
cd app/v5
npm run dev                 # 开发服务器
npm run build               # 生产构建 (vue-tsc + vite)
npm run dist                # Electron 打包，输出至 release/
```

新增 router：在 `interfaces/`（新功能）或 `routers/` 下创建文件，在 `main.py` 中 `app.include_router()`。

更多规范见 [AGENTS.md](AGENTS.md) 和 [docs/development_guide/](docs/development_guide/)。

## 硬件推荐

全本地推理的参考配置：

| 组件 | 型号 | 用途 |
|------|------|------|
| CPU | AMD Ryzen 9 9950X3D | ASR / OCR / TTS / 业务逻辑 |
| GPU | RTX 5080 16GB | LLM 推理（Qwen3.5-9B 约 7GB） |
| 内存 | 64GB DDR5 | 多模型并发缓冲 |

各模块大致开销：LLM 约 7GB 显存、TTS（Kokoro）与 ASR（SeamlessM4T）均跑 CPU。主链路不常驻 GPU 大型 TTS，16GB 显存可同时容纳 LLM 和一个视觉模型。

## 故障排查

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| `ModuleNotFoundError` | venv 未激活或依赖未装 | `pip install -e ".[dev]"` |
| `Address already in use` | 8012 端口被占 | 杀掉占用进程或改 `AIFL_PORT` |
| 调用了非预期的大模型 | `runtime_config.json` 缓存了错误模型 ID | 删除 `backend_fastapi/data/runtime_config.json` 后重启 |
| `404 model not found` | LM Studio 未加载模型 | 加载 `Qwen3.5-9B-Instruct` |
| LLM 响应极慢 | 显存不足换页 | 换更小模型或释放显存 |
| 语音对话无声音 | 麦克风权限 / ASR 未启用 / LM Studio 未运行 | 检查 `AIFL_ENABLE_ASR` 与后端日志中的 ASR/TTS 报错 |
| 前端 `vue-tsc` 报错 | 类型不匹配 | `npm run build` 会严格检查，按报错修 |

## 许可证

MIT License © 2025-2026 CUMT Alethic Insight Lab
