# 🤖 AI for Foreign Language Learning (AIFL)
### 全栈式本地化外语学习 AI 助手 · 教师端 + 学生端 · 端云协同

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B%20%7C%203.14-blue)
![Vue](https://img.shields.io/badge/Vue.js-3.4-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-teal)
![Electron](https://img.shields.io/badge/Electron-31.x-slateblue)

---

> **外行人一句话**：这是一个装在电脑上的"AI 外语私教"，能帮你查单词、改作文、练口语，所有 AI 推理都可以完全本地化运行，不用担心隐私泄露。
>
> **内行人一句话**：基于 FastAPI + Vue 3 + Electron 的全栈外语学习平台，支持多模态 LLM 路由（本地 LM Studio ↔ 云端 Kimi）、实时语音对话（ASR→LLM→TTS 端到端 <1s）、实时课堂助教（RTA，屏幕感知 + 语音唤醒 + 结构化决策）、学情分析 Agent 集群、知识图谱关联推荐，采用 SQLite/SQLModel + Redis + ES + Neo4j + MinIO 的多存储策略，目标硬件为 AMD 9950X3D + RTX 5080 16GB 全本地推理。

---

## 📑 目录

- [🎯 项目概述](#-项目概述)
- [🖼️ 系统全景图](#️-系统全景图)
- [✨ 核心功能矩阵](#-核心功能矩阵)
- [🚀 快速开始](#-快速开始)
- [⚙️ 后端服务配置详解](#️-后端服务配置详解)
- [🧩 依赖服务矩阵](#-依赖服务矩阵)
- [🏗️ 代码实现逻辑与架构设计](#️-代码实现逻辑与架构设计)
- [📡 API 接口速查](#-api-接口速查)
- [🔧 开发指南](#-开发指南)
- [🖥️ 硬件推荐与性能基准](#️-硬件推荐与性能基准)
- [🐛 故障排查](#-故障排查)

---

## 🎯 项目概述

AIFL 是一个面向中高级外语学习者的智能化学习平台，核心设计理念是**"端云协同、数据自治"**——所有敏感学习数据（作文、口语录音、学习轨迹）默认留在本地，AI 推理优先走本地 GPU（LM Studio），仅在本地资源不足或需要更强模型时自动 fallback 到云端 Kimi API。

### 三大核心场景

| 场景 | 用户价值 | 技术亮点 |
|------|---------|---------|
| **智能词汇** | 输入一个单词，AI 给出 CEFR 分级、多义项、真题考点、记忆曲线 | LLM 结构化 JSON 输出 + SM-2 遗忘曲线算法 |
| **作文批改** | 粘贴作文，AI 从 6 维度评分并给出全文润色 | Jinja2 Prompt 模板 + 多模态 OCR（图片作文） |
| **口语对话** | 与 AI 外教实时语音对话，可随时打断 | WebSocket 流式协议 + VAD 语音端点检测 + Barge-in 打断续接 |

### 两大教师端特色

| 场景 | 用户价值 | 技术亮点 |
|------|---------|---------|
| **实时助教 (RTA)** | 课堂上隐形 AI 助教，只在必要时语音/弹窗提醒 | 屏幕帧变化检测 + ASR 唤醒词 "Hi Helix" + LLM 结构化决策（should_intervene / use_tts） |
| **学情分析** | 自动生成班级/学生多维学情报告 | 20+ 维度分析 + 三层 Agent 架构 + 干预任务生成 |

---

## 🖼️ 系统全景图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AIFL 系统全景图                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────┐    ┌─────────────────────────────────────┐ │
│  │      前端 (Electron + Vue)   │    │           后端 (FastAPI)             │ │
│  │      app/v5/                 │    │      backend_fastapi/app/            │ │
│  │  ┌───────────────────────┐   │    │  ┌─────────────────────────────────┐ │ │
│  │  │  Vue 3 SPA (教师/学生) │   │◄──►│  │  Routers (REST + WebSocket)      │ │ │
│  │  │  - 词汇/作文/对话/分析  │   │ WS │  │  - vocab / essays / voice        │ │ │
│  │  │  - 实时助教悬浮窗       │   │    │  │  - analytics / admin / auth      │ │ │
│  │  │  - 系统设置面板         │   │    │  │  - realtime-assistant (RTA)      │ │ │
│  │  └───────────────────────┘   │    │  └─────────────────────────────────┘ │ │
│  │  ┌───────────────────────┐   │    │  ┌─────────────────────────────────┐ │ │
│  │  │  Electron Main        │   │    │  │  Domain Services                 │ │ │
│  │  │  - 系统托盘/全局快捷键 │   │    │  │  - 词汇生成 (LLM JSON 解析)       │ │ │
│  │  │  - 智能悬浮窗 overlay  │   │    │  │  - 作文批改 (6 维度评分)          │ │ │
│  │  │  - 屏幕截图/ASR/TTS   │   │    │  │  - 实时助教 Session (感知-决策)   │ │ │
│  │  └───────────────────────┘   │    │  │  - 学情分析 Agent 集群            │ │ │
│  └─────────────────────────────┘    │  └─────────────────────────────────┘ │ │
│                                     │  ┌─────────────────────────────────┐ │ │
│                                     │  │  Infrastructure                  │ │ │
│                                     │  │  - LLM 路由 (本地 ↔ 云端竞速)    │ │ │
│                                     │  │  - TTS 合成 (Kokoro CPU)         │ │ │
│                                     │  │  - ASR 识别 (SeamlessM4T CPU)    │ │ │
│                                     │  │  - OCR 识别 (Surya/Paddle)       │ │ │
│                                     │  └─────────────────────────────────┘ │ │
│                                     └──────────────────────────────────────┘ │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         数据层 (多存储策略)                               ││
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  ││
│  │  │ SQLite   │ │ Redis    │ │ ES       │ │ Neo4j    │ │ MinIO        │  ││
│  │  │ (主业务)  │ │ (缓存/队列)│ │ (全文搜索)│ │ (知识图谱)│ │ (文件/对象)   │  ││
│  │  │ SQLModel │ │ Celery   │ │ 词汇索引  │ │ 词关系网  │ │ 作文/截图    │  ││
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         AI 推理层 (端云协同)                              ││
│  │  ┌────────────────────────┐    ┌───────────────────────────────────────┐ ││
│  │  │ 本地 LM Studio (GPU)   │    │ 云端 Kimi API (fallback)              │ ││
│  │  │ - Qwen3.5-9B (对话)    │    │ - moonshot-v1-auto                    │ ││
│  │  │ - Qwen-VL (多模态)     │    │ - 网络异常时自动降级                   │ ││
│  │  │ - RTX 5080 16GB        │    │                                       │ ││
│  │  └────────────────────────┘    └───────────────────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ 核心功能矩阵

### 学生端功能

| 模块 | 功能点 | 技术实现 |
|------|--------|---------|
| **词汇** | 查词、OCR 识词、AI 生成释义、SM-2 复习、知识图谱关联 | `routers/vocab.py` + `llm.py` + `domain/srs/` |
| **作文** | 提交作文、AI 批改（6 维度评分）、错误纠正、全文润色 | `routers/essays.py` + Jinja2 Prompt |
| **对话** | 实时语音对话、场景选择、打断续接、TTS 播放 | `main.py` WebSocket + `voice_stream.py` |
| **学习记录** | 学习时长统计、能力雷达图、薄弱环节分析 | `routers/learning.py` + ECharts |

### 教师端功能

| 模块 | 功能点 | 技术实现 |
|------|--------|---------|
| **实时助教 (RTA)** | 屏幕感知、语音唤醒 "Hi Helix"、智能建议、TTS 打断 | `domain/realtime_assistant/session.py` |
| **学情分析** | 班级 Dashboard、学生画像、周报生成、干预任务 | `application/analytics/` |
| **管理面板** | 用户管理、配置热更新、服务健康检查、日志查看 | `interfaces/admin_router.py` |
| **悬浮窗查词** | Ctrl+Shift+S 截图查词、Ctrl+Shift+C 划词查词 | `electron/main/managers/system-integration-manager.ts` |

---

## 🚀 快速开始

### 环境要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| OS | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| Python | 3.10 | **3.13.5 或 3.14.0** |
| Node.js | 18 | 20 LTS |
| GPU | 无（CPU 模式）| RTX 5080 16GB（本地 LLM） |
| 内存 | 16GB | 64GB（9950X3D 平台） |
| 磁盘 | 10GB | 50GB SSD |

### 第一步：克隆仓库并创建虚拟环境

```bash
# 克隆项目
git clone <repo-url>
cd AiforForiegnLanguageLearning

# 创建 Python 虚拟环境 (后端)
cd backend_fastapi
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"
```

### 第二步：配置环境变量

创建 `backend_fastapi/.env` 文件（参考已有 `.env` 模板）：

```env
# ===== 基础配置 =====
AIFL_APP_ENV=development
AIFL_PORT=8012

# ===== LLM 配置 (本地 LM Studio) =====
AIFL_LLM_BASE_URL=http://127.0.0.1:1234/v1
AIFL_LLM_API_KEY=lm-studio
AIFL_LLM_MODEL=local-model
AIFL_LLM_TIMEOUT_SECONDS=30

# ===== 数据库 =====
AIFL_DATABASE_URL=sqlite:///./data/app.db

# ===== JWT =====
AIFL_JWT_SECRET=your-super-secret-key-change-this-in-production

# ===== 基础设施 (可选，按需启用) =====
AIFL_REDIS_URL=redis://localhost:6379/0
AIFL_ES_URL=http://localhost:9200
AIFL_NEO4J_URL=bolt://localhost:7687
AIFL_NEO4J_USER=neo4j
AIFL_NEO4J_PASSWORD=password
AIFL_MINIO_ENDPOINT=localhost:9000
AIFL_MINIO_ACCESS_KEY=minioadmin
AIFL_MINIO_SECRET_KEY=minioadmin

# ===== 语音模块 =====
AIFL_ENABLE_ASR=true
AIFL_ASR_BACKEND=seamless
AIFL_ASR_MODEL=small
AIFL_ASR_DEVICE=cpu
AIFL_ASR_COMPUTE_TYPE=int8

# ===== 实时助教 (RTA) =====
AIFL_RTA_ENABLED=true
AIFL_RTA_LLM_MODEL=moonshot-v1-auto
AIFL_RTA_LLM_BASE_URL=
AIFL_RTA_LLM_API_KEY=
AIFL_RTA_LLM_TIMEOUT=15
AIFL_RTA_COOLDOWN=5
AIFL_RTA_MAX_CONTEXT=6
AIFL_RTA_TTS_ENABLED=true
```

### 第三步：启动 LM Studio（本地 LLM）

1. 下载并安装 [LM Studio](https://lmstudio.ai/)
2. 加载推荐模型：**`Qwen3.5-9B-Instruct`**（或 `Qwen3.5-9B-Instruct-GGUF`）
3. 开启 Local Server，默认端口 `1234`
4. 确认模型已加载，左侧显示绿色状态

> ⚠️ **重要**：请勿加载 `Qwen3.5-35B-A3B` 或其他大 MoE 模型作为默认对话模型，除非显式需要。35B 模型虽然激活参数只有 3B，但加载/切换成本高，且会挤占显存。系统已通过 `_score_llm_model` 排序逻辑自动优先选择 9B。

### 第四步：启动基础设施服务（可选）

```powershell
# 在项目根目录运行 PowerShell 脚本
./scripts/start_infra_native.ps1
```

这会启动 Redis、RabbitMQ、Elasticsearch（如果已安装）。

### 第五步：启动后端

```bash
cd backend_fastapi
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

# 方式 1：直接启动
uvicorn app.main:app --host 0.0.0.0 --port 8012 --reload

# 方式 2：通过脚本（推荐，自动检查依赖）
../scripts/start.ps1
```

### 第六步：启动前端

```bash
cd app/v5
npm install
npm run dev
```

前端开发服务器默认运行在 `http://localhost:5173`，会自动代理到后端 `http://localhost:8012`。

### 第七步：验证

- 打开浏览器访问 `http://localhost:5173`
- 或使用 Swagger UI 测试 API：`http://localhost:8012/docs`
- 健康检查：`GET http://localhost:8012/health`

---

## ⚙️ 后端服务配置详解

### 1. 配置加载优先级

后端采用 **Pydantic Settings** 管理配置，加载优先级从高到低：

```
环境变量 > .env 文件 > 默认值
```

所有配置项定义在 `backend_fastapi/app/settings.py` 中，支持通过 `AIFL_` 前缀的环境变量覆盖。

### 2. 运行时配置热更新

`backend_fastapi/app/runtime_config.json` 是运行时可写的配置存储，用于：
- 前端设置面板实时修改模型选择、温度等参数
- `list_available_llm_models()` 自动缓存 LM Studio 的可用模型列表
- Prompt 模板热替换

```json
{
  "models": {
    "primary": "qwen/qwen3.5-9b",
    "available": ["qwen3.5-9b", "qwen/qwen3.5-9b", ...],
    "scene": {
      "chat": "qwen/qwen3.5-9b",
      "vocab": "",
      "essay": "",
      "analytics": ""
    }
  }
}
```

> ⚠️ **注意**：`runtime_config.json` 中的 `models.primary` 会被 `list_available_llm_models()` 自动刷新。如果手动修改，确保使用正确的模型 ID，否则可能导致错误调用大模型。

### 3. LLM 模型解析链

当调用 `chat_complete()` 或 `chat_complete_multimodal()` 且未显式传入 `model` 参数时，系统按以下优先级解析模型：

```
1. 场景模型 (runtime_config.json models.scene.{scene})
2. 主模型 (runtime_config.json models.primary)
3. Settings 默认模型 (settings.llm_model)
4. 查询 LM Studio /models 端点，按 _rank_models 排序取最优
   - 排序规则：参数量越小越优先
   - 惩罚项：vl(+200), thinking(+300), coder(+150), a3b/moe(+50)
```

### 4. 语音对话链路配置

语音对话（`main.py` WebSocket `/api/voice/start`）采用**云端优先 + 本地兜底**策略：

```python
voice_cloud_model = "moonshot-v1-auto"    # Kimi 云端模型
voice_local_model = "qwen3.5-9b"          # 本地 LM Studio 模型
```

- 若配置了 `KIMI_API_KEY`，优先调用 Kimi，1 秒超时无响应则 fallback 到本地
- 若未配置 Kimi，直接走本地模型
- 支持 Barge-in 打断：用户在 AI 播报时发送新音频，系统计算已播报字节比例，将未播报内容注入下一轮上下文

### 5. 实时助教 (RTA) 配置

RTA 默认使用云端 Kimi（`moonshot-v1-auto`），但可通过环境变量切换到本地：

```env
AIFL_RTA_LLM_MODEL=qwen3.5-9b
AIFL_RTA_LLM_BASE_URL=http://127.0.0.1:1234/v1
AIFL_RTA_LLM_API_KEY=lm-studio
```

RTA 的核心决策逻辑：
1. **触发源**：屏幕帧变化 / ASR 语音 / 鼠标框选 / 显式唤醒
2. **预筛选**：`SmartTriggerEngine` + `ProactiveSuggestionEngine` 检测关键词和信号
3. **LLM 决策**：`_generate_suggestion()` 调用 LLM，要求返回结构化 JSON
   ```json
   {
     "should_intervene": true,
     "intervention_type": "hint",
     "content": "简短建议",
     "use_tts": false,
     "urgency": "medium"
   }
   ```
4. **TTS 条件触发**：仅当 `use_tts=true` 时才合成 Kokoro 音频，默认静默显示

---

## 🧩 依赖服务矩阵

### 必需依赖

| 服务 | 用途 | 安装方式 | 默认端口 |
|------|------|---------|---------|
| **Python 3.10+** | 后端运行时 | 官网下载 | - |
| **Node.js 18+** | 前端构建 | 官网下载 | - |
| **LM Studio** | 本地 LLM 推理 | [lmstudio.ai](https://lmstudio.ai/) | 1234 |
| **SQLite** | 主数据库 | Python 内置 | - |

### 可选依赖（按需启用）

| 服务 | 用途 | 安装方式 | 默认端口 | 不启用时的降级行为 |
|------|------|---------|---------|-------------------|
| **Redis** | 缓存、Celery 消息队列 | `scoop install redis` / Docker | 6379 | 本地内存字典 |
| **RabbitMQ** | Celery  broker | `scoop install rabbitmq` / Docker | 5672 | 直接同步执行 |
| **Elasticsearch** | 词汇全文搜索 | `scoop install elasticsearch` | 9200 | 数据库 LIKE 查询 |
| **Neo4j** | 知识图谱存储 | Docker / 官网 | 7687 | 跳过图谱功能 |
| **MinIO** | 对象存储（作文图片等） | Docker / 官网 | 9000 | 本地文件系统 |
| **Celery Worker** | 异步任务（作文批改、周报生成） | `celery -A app.infrastructure.messaging.celery_app worker` | - | 同步阻塞执行 |

### 一键启动脚本

```powershell
# 启动所有基础设施
./scripts/start_infra_native.ps1

# 启动后端 + 前端开发服务器
./scripts/start.ps1

# 仅启动服务健康检查
./scripts/check-services.ts
```

---

## 🏗️ 代码实现逻辑与架构设计

> 本节面向希望深入理解系统设计的开发者。

### 1. 项目目录结构

```
AiforForiegnLanguageLearning/
├── app/v5/                          # 前端 (Vue 3 + Electron)
│   ├── electron/main/               # Electron 主进程
│   │   ├── managers/                # 窗口管理、系统托盘、IPC
│   │   └── preload.ts               # 预加载脚本 (contextBridge)
│   ├── public/overlay.html          # 智能悬浮窗独立页面
│   ├── src/
│   │   ├── views/                   # 页面级组件
│   │   ├── components/              # 通用组件
│   │   ├── stores/                  # Pinia 状态管理
│   │   ├── services/                # API 服务封装
│   │   └── types/                   # TypeScript 类型声明
│   └── package.json
│
├── backend_fastapi/                 # 后端 (FastAPI)
│   ├── app/
│   │   ├── main.py                  # FastAPI 应用入口 + WebSocket 语音链路
│   │   ├── settings.py              # Pydantic Settings 配置中心
│   │   ├── llm.py                   # LLM 调用封装 (OpenAI 兼容) + 模型解析
│   │   ├── model_router.py          # 多模型路由 (本地 ↔ 云端竞速)
│   │   ├── tts.py                   # TTS 合成 (Kokoro + Edge-TTS fallback)
│   │   ├── voice_stream.py          # ASR (SeamlessM4T) + VAD
│   │   ├── ocr.py                   # OCR 图像识别
│   │   ├── db.py                    # SQLModel / SQLAlchemy 数据库会话
│   │   ├── runtime_config.py        # 运行时可变配置 (热更新)
│   │   ├── prompts/                 # Jinja2 Prompt 模板
│   │   │   ├── essay_grade.j2
│   │   │   └── ...
│   │   ├── domain/                  # 领域层 (核心业务逻辑)
│   │   │   ├── models.py            # SQLModel 实体定义
│   │   │   ├── realtime_assistant/  # RTA 实时助教
│   │   │   │   ├── session.py       # 单会话感知-决策-行动闭环
│   │   │   │   ├── suggestion_engine.py  # 主动建议引擎
│   │   │   │   ├── trigger_engine.py     # 智能触发决策
│   │   │   │   └── screen_detector.py    # 屏幕变化检测
│   │   │   └── srs/                 # SM-2 间隔重复算法
│   │   ├── application/             # 应用层 (用例编排)
│   │   │   └── analytics/           # 学情分析
│   │   │       ├── agents.py        # LLM Agent 定义
│   │   │       ├── orchestration.py # 分析编排器
│   │   │       ├── weekly_report.py # 周报生成
│   │   │       └── daily_summary.py # 日报汇总
│   │   ├── interfaces/              # 接口适配层 (REST + WS)
│   │   │   ├── admin_router.py      # 管理面板 API
│   │   │   ├── auth_router.py       # 认证 API
│   │   │   └── realtime_assistant_router.py  # RTA WebSocket
│   │   ├── routers/                 # 业务路由
│   │   │   ├── vocab.py             # 词汇 API
│   │   │   ├── essays.py            # 作文 API
│   │   │   ├── voice.py             # 语音对话 HTTP API
│   │   │   ├── learning.py          # 学习记录 API
│   │   │   ├── system.py            # 系统配置 API
│   │   │   └── compat_legacy.py     # 旧版兼容 API
│   │   └── infrastructure/          # 基础设施层
│   │       ├── security.py          # JWT / 密码哈希
│   │       ├── messaging/           # Celery / 消息队列
│   │       └── persistence/         # ES / Neo4j 客户端
│   ├── data/                        # SQLite 数据库 + runtime_config.json
│   ├── tests/                       # pytest 测试集
│   ├── alembic/                     # 数据库迁移
│   └── pyproject.toml
│
├── docs/                            # 架构文档
│   ├── Detailed_System_Architecture.md
│   └── agent_prompts/               # Agent Prompt 设计文档
│
├── scripts/                         # 自动化脚本
│   ├── start.ps1
│   ├── start_infra_native.ps1
│   └── check-services.ts
│
├── shared/types/                    # 前后端共享类型
└── README.md
```

### 2. 后端架构：分层设计

采用 **Clean Architecture 简化版**——四层分离，但不过度抽象：

```
┌─────────────────────────────────────────────────────────────┐
│  Interfaces (接口层)                                          │
│  - FastAPI Routers / WebSocket Endpoints                     │
│  - 负责：序列化/反序列化、认证鉴权、参数校验                  │
│  - 不直接调用外部服务，只调用 Application / Domain          │
├─────────────────────────────────────────────────────────────┤
│  Application (应用层)                                         │
│  - 用例编排：analytics orchestration、RTA session           │
│  - 负责：事务边界、跨领域协调、DTO 转换                     │
├─────────────────────────────────────────────────────────────┤
│  Domain (领域层)                                              │
│  - 核心业务：词汇生成、作文评分、SM-2 算法、RTA 决策         │
│  - 负责：业务规则、领域模型、不依赖外部框架                   │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure (基础设施层)                                  │
│  - 外部适配：数据库、LLM HTTP 客户端、TTS、ASR、缓存         │
│  - 负责：技术细节、框架代码、可替换的实现                     │
└─────────────────────────────────────────────────────────────┘
```

### 3. LLM 调用链路详解

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│   Router    │────►│  model_router   │────►│  _resolve_llm_model │
│  (业务路由)  │     │  (多模型路由)    │     │  (模型解析 + 缓存)   │
└─────────────┘     └─────────────────┘     └─────────────────────┘
                                                       │
              ┌────────────────────────────────────────┘
              ▼
┌─────────────────────┐     ┌─────────────────────┐
│  chat_complete()    │     │ chat_complete_multimodal()
│  (纯文本对话)        │     │ (文本 + 图片多模态)
└─────────────────────┘     └─────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│  _build_chat_messages()                                  │
│  - system_prompt (Jinja2 模板)                           │
│  - history (最近 N 轮上下文)                              │
│  - user_text / image_base64                              │
└─────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│  httpx.AsyncClient → POST /chat/completions            │
│  - OpenAI 兼容格式                                       │
│  - 支持 streaming / non-streaming                        │
└─────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│  _extract_chat_response_text() / _extract_delta_text()  │
│  - 处理 content / reasoning_content / delta 多种格式    │
│  - 容错空响应、异常 JSON                                  │
└─────────────────────────────────────────────────────────┘
```

### 4. 语音对话 WebSocket 协议

```
Client (Electron)              Server (FastAPI)
      │                              │
      ├────── WS CONNECT ───────────►│
      │                              │
      ├────── AUDIO_START ──────────►│  开始新对话轮次
      │                              │
      ├────── AUDIO_CHUNK (binary) ─►│  音频流 (Opus / PCM)
      │                              │  ┌── VAD 检测语音端点
      │                              │  ├── ASR 识别 (SeamlessM4T)
      │                              │  ├── LLM 推理 (Kimi → 本地 fallback)
      │                              │  └── TTS 合成 (Kokoro)
      │                              │
      │◄───── ASR_PARTIAL ──────────┤  实时转写中间结果
      │◄───── ASR_FINAL ────────────┤  最终转写文本
      │◄───── LLM_TOKEN ────────────┤  流式生成 token (调试)
      │◄───── LLM_RESULT ───────────┤  完整回复文本
      │◄───── TTS_CHUNK (base64) ───┤  音频分片 (WAV)
      │◄───── TTS_RESULT ───────────┤  音频发送完毕
      │◄───── TASK_FINISHED ────────┤  本轮结束
      │                              │
      ├────── AUDIO_END ────────────►│  用户停止说话
      │                              │
      ├────── AUDIO_BARGE_IN ───────►│  用户打断，取消当前 TTS
      │                              │
```

### 5. 实时助教 (RTA) 决策流

```
屏幕帧 / ASR / 框选 / 唤醒词
        │
        ▼
┌─────────────────────────────┐
│  SmartTriggerEngine         │  事件缓冲区 + 优先级决策
│  ProactiveSuggestionEngine  │  关键词检测（犹豫/重复/纠错/唤醒）
└─────────────────────────────┘
        │
        ▼ 触发条件满足
┌─────────────────────────────┐
│  RealtimeAssistantSession   │
│  ._generate_suggestion()     │
│                             │
│  1. 组装 Prompt (课件+语音) │
│  2. LLM 调用 (多模态降级)   │
│  3. _extract_rta_decision() │  解析 JSON 决策
│  4. should_intervene?       │
│     ├── false → 静默丢弃    │
│     └── true  → 继续        │
│  5. use_tts?                │
│     ├── false → 仅 overlay  │
│     └── true  → overlay + TTS│
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│  WebSocket → 前端 overlay   │
│  悬浮窗显示 (entry/loading/result)
└─────────────────────────────┘
```

### 6. 数据库实体关系

核心实体（`app/domain/models.py`）：

- **User** - 用户（学生/教师/管理员，RBAC 权限）
- **Vocabulary** - 词汇条目（单词、CEFR 级别、义项 JSON）
- **VocabularyReview** - 复习记录（SM-2 参数：interval, repetitions, ease_factor, next_review）
- **EssaySubmission** - 作文提交（原文、批改结果 JSON、分数）
- **Conversation** - 对话会话（语音对话上下文）
- **LearningRecord** - 学习记录（时长、模块、正确率）
- **Class** / **ClassAssignment** - 班级与学生分配
- **PromptTemplate** - Prompt 模板版本管理

### 7. 关键设计模式

| 模式 | 应用位置 | 说明 |
|------|---------|------|
| **Repository** | `db.py` + `routers/` | SQLModel Session 依赖注入 |
| **Strategy** | `model_router.py` | 本地/云端模型竞速策略 |
| **Chain of Responsibility** | `llm.py` 降级链 | 多模态 → 纯文本 → 竞速 → fallback |
| **State Machine** | `session.py` RTA | 会话状态管理（_active, _lock） |
| **Observer** | `suggestion_engine.py` | ASR 流事件监听与信号检测 |
| **Template Method** | `prompts/*.j2` | Jinja2 Prompt 模板化 |

---

## 📡 API 接口速查

### 核心 REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /v1/vocab/lookup` | 查词 | 传入单词，返回结构化释义 |
| `POST /v1/vocab/lookup-ocr` | OCR 查词 | 传入图片 Base64，识别后查词 |
| `POST /v1/essays/grade` | 作文批改 | 6 维度评分 + 润色 |
| `GET /api/voice/generate-prompt` | 生成对话提示 | 按场景生成开场白 |
| `POST /api/auth/login` | 登录 | JWT Token |
| `GET /api/admin/services` | 服务健康检查 | LLM / ASR / TTS / 基础设施 |
| `GET /health` | 健康检查 | 服务存活探针 |

### WebSocket 端点

| 端点 | 说明 |
|------|------|
| `WS /api/voice/start` | 语音对话主链路 |
| `WS /api/v1/realtime-assistant/ws` | 实时助教 |

### Swagger UI

启动后端后访问：`http://localhost:8012/docs`

---

## 🔧 开发指南

### 后端开发

```bash
cd backend_fastapi
.venv\Scripts\activate

# 运行测试
pytest tests/ -q

# 运行特定测试
pytest tests/test_realtime_assistant.py -v

# 代码格式化
ruff check .
ruff format .

# 数据库迁移
alembic revision --autogenerate -m "describe_change"
alembic upgrade head
```

### 前端开发

```bash
cd app/v5
npm run dev          # 开发服务器
npm run build        # 生产构建 (vue-tsc + vite)
npm run build:electron   # 编译 Electron 主进程
electron-builder     # 打包可执行文件
```

### 添加新 Router

1. 在 `backend_fastapi/app/routers/` 创建新文件
2. 继承 `APIRouter`，定义端点
3. 在 `backend_fastapi/app/main.py` 中 `app.include_router()`
4. 更新 `README.md` API 速查表

---

## 🖥️ 硬件推荐与性能基准

### 推荐配置（全本地推理）

| 组件 | 型号 | 用途分配 |
|------|------|---------|
| CPU | AMD Ryzen 9 9950X3D | ASR / OCR / TTS / 业务逻辑 |
| GPU | RTX 5080 16GB | LLM 推理 (Qwen3.5-9B ~7GB) |
| 内存 | 64GB DDR5-5600 | 多模型并发缓冲 |
| 存储 | 1TB NVMe SSD | 模型文件 + 数据库 |

### 各模块资源占用

| 模块 | GPU 显存 | GPU 利用率 | 延迟 |
|------|---------|-----------|------|
| LLM (Qwen3.5-9B) | ~7GB | 30-40% | ~500ms/token |
| TTS (Kokoro CPU) | 0GB | 0% | 500-1200ms |
| ASR (SeamlessM4T CPU) | 0GB | 0% | ~300ms |
| VLM (MiniCPM-V) | ~4GB | - | - |

> 💡 **显存优化**：当前主链路已去除 XTTS 常驻 GPU 依赖，16GB 显存可舒适容纳 LLM + VLM。

---

## 🐛 故障排查

### 后端启动失败

| 现象 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError` | 虚拟环境未激活或依赖未安装 | `pip install -e ".[dev]"` |
| `Address already in use` | 端口 8012 被占用 | `lsof -i :8012`  kill 掉，或改 `AIFL_PORT` |
| `Pydantic validation error` | `.env` 文件格式错误 | 检查是否有中文引号或缺失值 |

### LLM 调用异常

| 现象 | 原因 | 解决 |
|------|------|------|
| 总是调用 35B 大模型 | `runtime_config.json` 缓存污染 | 删除 `backend_fastapi/data/runtime_config.json` 重启，或检查 `llm.py` `_resolve_llm_model` |
| `404 model not found` | LM Studio 未加载对应模型 | 在 LM Studio 中加载 `Qwen3.5-9B` |
| 响应极慢 | GPU 显存不足导致换页 | 关闭其他 GPU 程序，或换更小模型 |
| 返回 `(网络不太稳定)` | LM Studio 未启动或端口错误 | 检查 `AIFL_LLM_BASE_URL` 和 LM Studio Server 状态 |

### 前端构建失败

| 现象 | 原因 | 解决 |
|------|------|------|
| `vue-tsc` 类型错误 | TS 类型不匹配 | `npm run build` 会严格检查，修复类型声明 |
| Electron 打包失败 | 缺少 `electron-builder` 配置 | 检查 `app/v5/package.json` `build` 字段 |

### 语音对话无声音

1. 检查浏览器/Electron 是否有麦克风权限
2. 检查 `AIFL_ENABLE_ASR=true`
3. 检查 LM Studio 是否运行（本地 fallback 需要）
4. 查看后端日志是否有 `ASR failed` 或 `TTS failed`

---

## 📄 许可证

MIT License © 2025 AIFL Team

---

*README 版本: v2.0*  
*更新日期: 2026-04-19*
