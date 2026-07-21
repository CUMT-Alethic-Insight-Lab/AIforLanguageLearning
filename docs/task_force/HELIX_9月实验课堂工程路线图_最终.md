# HELIX 9月实验课堂工程路线图（最终版）

> 生成日期: 2026-06-01 · 更新日期: 2026-06-03 (第 5 轮)
> 基于 6 个只读探索 subagent 报告 + 手动 Web 调研合成
> 目标: 2026 年 9 月进入实验课堂，后端 9950X3D + RTX 5080，课堂 30-60 名学生
> 最高目标: 为 CSSCI 期刊实验提供可信实验数据
>
> **⚠️ 当前工程推进范围截止到 Phase 3：Phase 1 analytics 数据归属统一、Phase 2 课堂轮流练最小闭环、Phase 3 Web 局域网访问/部署准备。Phase 4+（CSSCI 深度导出、教师端大 UI、并发压测等）暂列后续，不进入当前实现队列。**

---

## 1. P0 优先级（9 月前必须完成）

| # | 事项 | 关联文件 | 工作量 | 说明 |
|---|------|---------|-------|------|
| 1 | **修 frontend build** | `app/v5/src/stores/voice.ts:379-452` | S | `startCustomSession` 函数体缺少闭合 `}`。导致整个 npm build 失败，blocking 项 |
| 2 | **FastAPI 挂载静态文件 + SPA fallback** | `backend_fastapi/app/main.py` | S | `npm run build` 后让 FastAPI 通过 StaticFiles 托管前端 dist/，配置 hash fallback 到 index.html |
| 3 | **课堂语音隔离 —— 引入 classroom_session_id** | `backend_fastapi/app/main.py:320-380` (`get_all_chat_history_from_events`) | M | 历史查询现在只按 conversation_id 过滤。需增加 classroom_session_id/user_id 维度防止上下文串号 |
| 4 | **WS 连接加入 user_id 服务端校验** | `backend_fastapi/app/main.py:144-162` | M | 当前 user_id 为客户端传入的可选字符串，无服务端校验。任课教师可伪造他人 user_id |
| 5 | **REST 接口 user_id 服务端校验** | `analytics_router.py` (`POST /intervention` 从 body 取 student_id，`/student/{student_id}/report`、`/student/{student_id}/dashboard` 等从路径参数取 student_id) | M | 多个接口未与 JWT token 比对 student_id。需统一校验路径参数 student_id 与当前登录用户是否匹配；`POST /intervention` 的 body student_id 改为从 token 或路径参数获取 |
| 6 | **MinIO 启动崩溃防护** | `backend_fastapi/app/infrastructure/storage/minio_storage.py:11` (模块级 `from minio import Minio`)，反向传播：`main.py:26` 导入 `storage_router` → `storage_router.py:9` 导入 `get_minio_storage` → `minio_storage.py` | S | `from minio import Minio` 在模块级别 import，MinIO 不可用时整个后端启动崩溃。需改为函数内 import 保护 |
| 7 | **新增 classrooms/classroom_sessions/experiments 表** | `backend_fastapi/app/domain/models.py` + `db.py` | L | 见第 5 节数据模型。这是实验课堂和 CSSCI 数据的根基 |
| 8 | **教师课堂控制台页面（前端）** | `app/v5/src/views/` | L | 需新建 classroom 视图：学生列表、点名发言、切换轮次、查看实时反馈 |
| 9 | **学生课中等待/发言/反馈页面** | `app/v5/src/views/` | M | 课前查词已有，课中发言需要新视图：排队指示器、录音按钮、反馈展示 |
| 10 | **HTTPS 证书方案 + 部署验证** | LAN 网络环境 | S | 浏览器 getUserMedia() 在 LAN HTTP 下不可用。教师机需 mkcert/自签证书 |

### P0 总工作量: 约 3-4 人周（含前端 2 视图 + 数据模型 + API 改造 + build 修复）

---

## 2. P1 优先级（9 月前最好完成）

| # | 事项 | 关联文件 | 工作量 | 说明 |
|---|------|---------|-------|------|
| 1 | **CSSCI 数据导出 API (CSV/JSON)** | `analytics_router.py` | M | 实验结束后需导出原始数据供统计分析。无导出能力则无法为论文提供数据 |
| 2 | **ASR/LLM 并发排队 + ThreadPool 限制** | `voice_stream.py` + `main.py` | M | 30-60 人同时 ASR（SeamlessM4T CPU）会撑爆 CPU。需 asyncio.Semaphore + ThreadPoolExecutor(max_workers=N) |
| 3 | **语音对话数据进入学情分析链路** | `analytics_router.py` + `analytics/facade.py` | M | 当前口语维度 A11-A15 虽然从 conversation_events 读取，但需确认 session/class 维度的聚合查询 |
| 4 | **上下文摘要压缩迁移到 WS 管线** | `model_router.py` → `voice_stream.py` | M | `ConversationContext` 的摘要压缩/滑动窗口逻辑只用于 REST 路径，WS 管线直接从 SQLite 全量拉取。需复用压缩逻辑 |
| 5 | **teacherAnalytics.ts 前端连接** | `app/v5/src/services/teacherAnalytics.ts` + `views/` | M | 教师分析 API 已完整（11 个端点），但前端无一个视图使用该服务 |
| 6 | **设备检测页** | `app/v5/src/views/` | S | 学生首次访问时检测麦克风权限、网络延迟、浏览器兼容性 |
| 7 | **学生课后作文改进（语音→作文）** | `routers/essays.py` | S | 语音对话后可一键生成作文草稿供课后修改 |
| 8 | **voice.ts build 修复后验证全链路** | `app/v5/src/stores/voice.ts` | S | 修完 `}` 缺失后做一次完整 npm build + dev 验证 |

### P1 总工作量: 约 3-5 人周

---

## 3. 明确冻结的功能

| 功能 | 原因 | 当前状态 | 冻结后影响 |
|------|------|---------|-----------|
| **Neo4j 知识图谱** | 不是主链路，降级需区分场景。`domain/knowledge_graph/client.py:8-14` 有 ImportError 保护（`NEO4J_AVAILABLE=False` 时所有方法返回 None/[]）；`service.py:58-65` 的 `_get_client()` 捕获连接异常 | **词汇推荐（内部，vocab.py -> get_kg_service().recommend_vocabulary()）**: 三层推荐策略（薄弱点扩展→已学扩展→兜底），Neo4j 不可用时策略 1/2 返回空，落入预定义词库兜底，用户无感知 ✅ **降级良好**。**公共 KG 接口**（`knowledge_graph_router.py`: `/relations`, `/learning-path`）: Neo4j 不可用时返回**空结果**而非 500，但用户无法区分"数据不存在"与"系统不可用"，存在隐式降级风险 |
| **Elasticsearch 搜索** | 不是主链路，降级良好 | `domain/vocabulary_service.py` 有 try/except | 词汇模糊搜索回退到 LLM 兜底 |
| **Redis 缓存** | 不是主链路 | `infrastructure/cache.py` 有降级逻辑 | 缓存失效，性能略降但功能正常 |
| **Celery 批量任务** | 降级良好 | 有 `_DummyCelery` 回退 | 日摘要/分层分析任务改为同步或手动触发 |
| **MinIO 文件存储** | 需做 import 保护后冻结 | `minio_storage.py:6` 模块级 `from minio import Minio`（pip 包未装 → 启动崩；服务未启 → 运行时 500），通过 `main.py:26` → `storage_router.py:8` → `minio_storage.py` 传播 | 图片上传/存储不可用，文字可继续 |
| **PaddleOCR** | 不是主链路 | `ocr.py` 懒加载（PaddleOCR 为主路径，rapidocr_onnxruntime 为兜底，无 Tesseract） | **文字作文不受影响**（直接文本提交不走 OCR）。**图片 OCR 不保证**：图片作文识别可能失败（空字符串），调用方需自行降级 |
| **实时屏幕助教 (RTA)** | 明确冻结 | 所有 `window.api` 引用均无需迁移 | 教师端实时提醒功能 9 月不可用 |
| **Electron 桌面版** | Web 优先优先 | `assistant.ts` 全部依赖 window.api | 学生只需浏览器，教师端通过 Web 访问 |
| **Electron local whisper** | Electron 冻结 | 前端不调用 | 无影响 |
| **Softbus/ZeroMQ** | Electron 冻结 | 仅前端 Electron IPC | 无影响 |
| **知识图谱三层推荐** | Neo4j 冻结 | `domain/knowledge_graph/` | 无影响 |

---

## 4. 现有代码中最危险的 10 个点

| # | 风险 | 文件 | 行号 | 严重程度 | 后果 |
|---|------|------|------|---------|------|
| 1 | `startCustomSession` 函数体缺失闭合 `}` | `app/v5/src/stores/voice.ts` | 379-452 | **阻断** | npm build 完全失败。不修任何一个 Web 页面都跑不起来 |
| 2 | user_id 为客户端传入的可选字符串，无服务端校验 | `backend_fastapi/app/main.py` | 144-162 | **高危** | 学生可伪造 user_id 串改/旁听/写入他人对话记录 |
| 3 | `get_all_chat_history_from_events()` 只按 conversation_id 过滤，不按 user_id/session_id | `backend_fastapi/app/main.py` | 320-380 | **高危** | 课堂轮流练时多人会话上下文完全混合 |
| 4 | `analytics_router.py` 5 个端点从路径参数取 student_id 但未与 JWT token 比对；`POST /intervention` 从 request body 取 student_id。受影响端点：`/student/{student_id}/dashboard`(L195)、`/student/{student_id}/profile`(L117)、`/student/{student_id}/report`(L271)、`/student/{student_id}/class-assignment`(L308)、`/student/{student_id}/llm-profile`(L368)、`POST /intervention`(L336 body student_id) | `backend_fastapi/app/interfaces/analytics_router.py` | 多处 | **高危** | 任意学生可伪造 student_id 查看他人全部学情（dashboard/profile/report/llm-profile）或自行分配到任意班级（class-assignment），或创建他人干预任务（intervention） |
| 5 | `class-assignment` endpoint 依赖前端传入 class_id | `backend_fastapi/app/interfaces/analytics_router.py` | 308-315 | **中危** | 学生可自行分配到任意班级 |
| 6 | `from minio import Minio` 为模块级 import（在 `minio_storage.py:6`），通过 `main.py:26` → `storage_router.py:8` → `minio_storage.py` 传播。分两种情况：(a) minio pip 包未安装 → ImportError → 后端**启动崩溃**；(b) pip 包已安装但 MinIO 服务器未运行 → `get_minio_storage()` 首次调用时报错 → 运行时 500，不影响启动 | `backend_fastapi/app/infrastructure/storage/minio_storage.py` | L6 import | **中危** | 见左侧说明 |
| 7 | `CONTEXT_SET` 事件可更新 session_user_id 但 conversation_id 不变 | `backend_fastapi/app/main.py` | 1276-1282 | **中危** | 教师切换学生后新旧上下文混合 |
| 8 | `ConversationContext`（model_router.py）与 WS 事件存储（main.py）两条独立路径不互通 | `backend_fastapi/app/model_router.py` vs `main.py` | 全局 | **中危** | REST 和 WS 两条管线的上下文逻辑重复且不一致 |
| 9 | 全系统无限流/排队/超时/取消/重试机制 | `backend_fastapi/app/voice_stream.py` | 全局 | **中危** | 30-60 人同时 ASR 可撑爆 CPU，Kimi API 被 QPS 限流 |
| 10 | `post_test_backend.py` 多处硬编码 8011 端口，与当前 8012 不一致 | `tests/` 多个文件 | 多处 | **低危** | 测试端口与运行端口不一致导致测试失败 |

---

## 5. 需要新增的最小数据模型

以下是基于 SQLModel（项目当前 ORM）的最小新增表定义建议，用于写入 `backend_fastapi/app/domain/models.py`：

```python
# 实验（通过 experiment_groups.experiment_id 反向关联，不在 Experiment 上设 group_id 避免循环引用）
class Experiment(SQLModel, table=True):
    __tablename__ = "experiments"
    id: int = Field(primary_key=True)
    name: str
    description: str | None = None
    classroom_id: int | None = Field(default=None, foreign_key="classrooms.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExperimentGroup(SQLModel, table=True):
    __tablename__ = "experiment_groups"
    id: int = Field(primary_key=True)
    experiment_id: int = Field(foreign_key="experiments.id")
    name: str
    is_treatment: bool = False  # True=实验组, False=对照组

class ExperimentGroupMember(SQLModel, table=True):
    __tablename__ = "experiment_group_members"
    id: int = Field(primary_key=True)
    group_id: int = Field(foreign_key="experiment_groups.id")
    student_id: int = Field(foreign_key="users.id")
    __table_args__ = (UniqueConstraint("group_id", "student_id"),)
    is_treatment: bool = False  # True=实验组, False=对照组

# 班级与课程
class Classroom(SQLModel, table=True):
    __tablename__ = "classrooms"
    id: int = Field(primary_key=True)
    name: str
    course_id: int | None = Field(default=None, foreign_key="courses.id")
    teacher_id: int = Field(foreign_key="users.id")  # User.__tablename__ = "users"
    semester: str | None = None
    academic_year: str | None = None

class Course(SQLModel, table=True):
    __tablename__ = "courses"
    id: int = Field(primary_key=True)
    name: str
    description: str | None = None
    grade_level: str | None = None  # e.g., "初中", "高中", "大学"

class Lesson(SQLModel, table=True):
    __tablename__ = "lessons"
    id: int = Field(primary_key=True)
    course_id: int = Field(foreign_key="courses.id")
    title: str
    order: int  # 课时编号
    objectives: str | None = None  # 教学目标

# 课堂活动
class ClassroomSession(SQLModel, table=True):
    __tablename__ = "classroom_sessions"
    id: int = Field(primary_key=True)
    classroom_id: int = Field(foreign_key="classrooms.id")
    lesson_id: int | None = Field(default=None, foreign_key="lessons.id")
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id")
    date: date
    start_time: datetime
    end_time: datetime | None = None
    status: str = "scheduled"  # scheduled / ongoing / finished

class SessionActivity(SQLModel, table=True):
    __tablename__ = "session_activities"
    id: int = Field(primary_key=True)
    session_id: int = Field(foreign_key="classroom_sessions.id")
    activity_type: str  # vocab_drill / voice_practice / essay / quiz
    student_id: int = Field(foreign_key="users.id")  # User.__tablename__ = "users"
    start_time: datetime
    end_time: datetime | None = None
    round_number: int = 1

class ActivityTurn(SQLModel, table=True):
    __tablename__ = "activity_turns"
    id: int = Field(primary_key=True)
    activity_id: int = Field(foreign_key="session_activities.id")
    student_id: int = Field(foreign_key="users.id")  # User.__tablename__ = "users"
    turn_number: int
    ai_response_type: str | None = None  # correction / elaboration / followup / etc
    response_latency_ms: int | None = None
    teacher_intervention: str | None = None  # yes / no / prompt
    student_adopted: bool | None = None  # 学生是否采纳AI建议
    conversation_event_ids: list[int] | None = None  # JSON 数组，关联 conversation_events.id，替代逗号分隔字符串
    essay_result_id: int | None = Field(default=None, foreign_key="essay_results.id")
    vocab_query_ids: list[int] | None = None  # JSON 数组，关联 user_vocab_queries.id

# 评估记录
class Assessment(SQLModel, table=True):
    __tablename__ = "assessments"
    id: int = Field(primary_key=True)
    student_id: int = Field(foreign_key="users.id")  # User.__tablename__ = "users"
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id")
    assessment_type: str  # pre_test / post_test
    date: date
    score: float | None = None
    raw_data: str | None = None  # JSON: 各维度原始评分
```

### 需要修改的现有表

- `StudentProfile` (`domain/models.py:30`) — 新增 `classroom_id: int | None = Field(default=None, foreign_key="classrooms.id")`。**共存策略**：保留 `class_id: str | None` 不动（已有旧数据），新代码优先使用 `classroom_id`，旧数据通过 `class_id` 查询。不可直接修改 `class_id` 类型，这会破坏现有数据。
- `User` — 可考虑添加 `experiment_group_id` 字段（也可通过 `experiment_group_members` 关联查询，不需要冗余字段）
- `conversation_events` — 新增 `session_activity_id: int | None` FK
- `essay_submissions` — 新增 `session_activity_id: int | None` FK
- `essay_results` — 新增 `session_activity_id: int | None` FK
- `user_vocab_queries` — 新增 `session_activity_id: int | None` FK

### 迁移策略

使用 Alembic （项目已有 `alembic/versions/` + `alembic/env.py`）逐步迁移。建议分两次:
1. 第一批: Classroom/Course/Lesson/ClassroomSession — 用于 9 月课堂
2. 第二批: Experiment/ExperimentGroup/Assessment — 用于 CSSCI 实验数据收集

---

## 6. Web 课堂版最小部署方案

### 架构图
```
┌─────────────────────────────────────────────────────┐
│              教师本机 （9950X3D + RTX 5080）          │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  FastAPI (端口 8012)                          │   │
│  │  ├─ /api/v1/* （REST）                        │   │
│  │  ├─ /ws/v1    （WebSocket）                   │   │
│  │  ├─ /         （静态文件：前端 dist/）           │   │
│  │  └─ SQLite   （data/app.db）                   │   │
│  └──────────────────────────────────────────────┘   │
│                         ↑ HTTPS (自签证书)            │
│                    ┌────┴────┐                       │
│                    │  mkcert  │                       │
│                    └────┬────┘                       │
│                         │                            │
│  ┌──────────────────────┴──────────────────────┐    │
│  │  LAN （192.168.x.x / 10.x.x.x）              │    │
│  └──────────────────────┬──────────────────────┘    │
│           ┌─────────────┼──────────┐                 │
│           ▼             ▼          ▼                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐      │
│  │ 学生 A     │ │ 学生 B     │ │ 教师（浏览器）│     │
│  │ (浏览器)   │ │ (浏览器)   │ │ (浏览器)   │      │
│  └────────────┘ └────────────┘ └────────────┘      │
└─────────────────────────────────────────────────────┘
```

### 步骤

**Step 1 — 修 build**
- 修复 `app/v5/src/stores/voice.ts:452` 缺失的闭合 `}`
- `npm run build` 输出到 `app/v5/dist/`

**Step 2 — FastAPI 托管前端**
```python
# backend_fastapi/app/main.py 新增（在所有 API 路由注册之后）
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DIST_DIR = Path(__file__).resolve().parent.parent.parent.parent / "app" / "v5" / "dist"

if DIST_DIR.is_dir():
    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")
    for _root_file in ["favicon.ico", "robots.txt", "site.webmanifest"]:
        _f = DIST_DIR / _root_file
        if _f.is_file():
            @app.get(f"/{_root_file}", include_in_schema=False)
            async def _serve_root_file(file_path: Path = _f):
                return FileResponse(str(file_path))
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(str(DIST_DIR / "index.html"))
else:
    import logging
    logger.warning("Frontend dist not found at %s — SPA routes disabled", DIST_DIR)
```
注意：
- **不使用 `app.mount("/", StaticFiles(... html=True))`**：这样会拦截所有请求（包括 API 路由），导致 API 404 被重定向到 index.html。
- 前端使用 `createWebHashHistory()`，刷新只需返回 index.html（路径 `/`），无需 catch-all route。
- `/assets/*` 由 StaticFiles 直接匹配。
- `include_in_schema=False` 避免污染 OpenAPI 文档。
- dist 目录不存在时优雅降级，不影响纯 API 后端使用。
- 路径计算：`backend_fastapi/app/main.py` → 上 4 层到项目根 → `app/v5/dist`。Windows 下使用 `Path.resolve()` 确保可靠。

**Step 3 — HTTPS 自签证书**
```powershell
# 教师机安装 mkcert
choco install mkcert  # 或 winget install mkcert
mkcert -install
mkcert 192.168.1.100   # 替换为教师机实际 LAN IP

# FastAPI 启动使用证书
uvicorn app.main:app --host 0.0.0.0 --port 8012 --ssl-certfile 192.168.1.100.pem --ssl-keyfile 192.168.1.100-key.pem
```

**Step 4 — 学生访问**
- 学生浏览器输入 `https://192.168.1.100:8012`
- 首次访问会提示证书风险（自签证书的正常行为）
- 允许麦克风权限后即可使用

**Step 5 — 启动脚本**
修改 `scripts/start.ps1`，加入证书参数和 `--reload` 条件判断

### 备用方案（无 HTTPS）
如果教室网络无法使用 HTTPS，可用 `localhost` + 端口转发:
- 教师机运行 `nginx` 反向代理（`http://localhost:8012` → `https://localhost:443`）
- 或使用 `ngrok` / `cloudflared` 隧道（需确认课堂 LAN 可用）

---

## 7. 语音课堂轮流练最小方案

### 当前限制
- 一轮对话需要 17 步（录音→VAD→ASR→LLM→TTS→播放）
  ⚠️ **TTS 非真流式**：前端当前不逐片播放 `TTS_CHUNK`，只播放 `TTS_RESULT`（全量音频）。后端先生成完整 WAV 再拆片发送，非真流式。
- SeamlessM4T ASR 使用 CPU 推理，30 人并发撑爆 CPU
- Kimi API 有 QPS 限制
- WebSocket 连接数需限制

### 最小方案

**原则**: 一次只让 1-2 名学生发言，其他学生旁听（可看到转写和 AI 回答）

```
教师点名 → 学生 A 开始录音 → ASR → LLM → TTS → 学生 A 播放 (仅 TTS_RESULT)
                                                         ↓
                                                    所有旁听学生显示转写文本
                                                         ↓
教师点名 → 学生 B 开始录音 → ASR → LLM → TTS → 学生 B 播放 (仅 TTS_RESULT)

注：TTS_CHUNK 事件已发送但不作为播放信号；前端通过 TTS_RESULT 接收全量音频后统一播放。
```

**实现要点**:

1. **并发控制**:
   - 引入 `classroom_session_id`，所有 WS 连接携带此参数
   - 后端维护 `session_active_speaker`（内存 dict，key=classroom_session_id, value=user_id）
   - 教师通过 `WS 消息（类型=SELECT_SPEAKER）` 指定当前发言人
   - 非当前发言人的 WS `AUDIO_CHUNK_BIN` 被后端丢弃或忽略

2. **旁听学生视图**:
   - 非当前发言人收到 `ASR_FINAL` 和 `LLM_RESULT` 事件，但不会触发 TTS
   - 前端自动滚屏显示转写文本

3. **超时控制**:
   - 每个发言人默认 120 秒发言超时
   - 无活动 30 秒后自动结束轮到下一位

4. **教师控制**:
   - 教师页面: 显示在线学生列表，点击选择发言人
   - 教师可随时打断当前发言人（`INTERRUPT_SPEAKER` 消息）
   - 教师可看当前转写内容（旁听模式）

### 需要修改的代码

| 文件 | 修改内容 | 工作量 |
|------|---------|--------|
| `backend_fastapi/app/main.py` `/ws/v1` | 接入 classroom_session_id 上下文、speaker_queue 校验 | M |
| `backend_fastapi/app/voice_stream.py` | 增加并发限流（Semaphore）、ASR thread pool | M |
| `app/v5/src/stores/voice.ts` | 新增 turn-taking 状态管理 | M |
| `app/v5/src/views/ClassroomView.vue`（新建） | 教师课堂控制台：学生列表、发言控制、实时转写 | L |
| `app/v5/src/views/StudentSession.vue`（新建） | 学生等待/发言/旁听视图 | M |

**工作量**: 约 2-3 人周（含前后端）

---

## 8. CSSCI 实验数据采集方案

### 数据采集架构

```
学生活动（查词/对话/作文）
        │
        ▼
┌──────────────────┐
│  SQLite 主库      │
│  - conversation_events  │
│  - user_vocab_queries   │
│  - essay_results        │
│  - learning_records     │
│  - session_activities   │  ← 新增
│  - activity_turns       │  ← 新增
│  - assessments          │  ← 新增（前测/后测）
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  CSV/JSON 导出 API  │  ← 新增
│  /api/v1/analytics/  │
│    export-trial-data  │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 统计分析工具        │
│  (SPSS / R / Python)│
└──────────────────┘
```

### 必须采集的实验字段

| 维度 | 字段 | 来源 | 说明 |
|------|------|------|------|
| 分组 | experiment_id, group_id, is_treatment | `experiments` + `experiment_groups` | 新表 |
| 前测/后测 | assessment_type, score, raw_data | `assessments` 表 | 新表 |
| 课堂轮次 | session_id, activity_id, round_number | `classroom_sessions` + `session_activities` | 新表 |
| 任务编号 | lesson_id + activity_type | `lessons` + `session_activities.activity_type` | 新表 |
| AI 反馈类型 | ai_response_type | `activity_turns.ai_response_type` | 新表 |
| 响应时长 | response_latency_ms | `conversation_events` + `activity_turns` | 已有 + 新表 |
| 教师干预 | teacher_intervention | `activity_turns.teacher_intervention` | 新表 |
| 学生采纳 | student_adopted | `activity_turns.student_adopted` | 新表 |
| 词汇增长 | user_vocab_queries + vocabulary_items | 现有表 | 按时序对齐 session |
| 作文评分 | essay_results.dimensions | 现有表 | 按时序对齐 session |
| 口语表现 | conversation_events 的 audio_duration_ms / word_count | 现有表 | 按时序对齐 session |

### 导出 API 设计

```python
# backend_fastapi/app/interfaces/analytics_router.py 新增

@router.get("/export-trial-data")
async def export_trial_data(
    experiment_id: int,
    format: str = "csv",  # csv / json
    user_id: int = Depends(get_current_user),
    session: Session = Depends(get_db)
):
    """导出指定实验的全部数据，供 CSSCI 论文统计分析"""
    # 1. 校验权限（仅实验负责教师可导出）
    # 2. 组装宽表：每个 student × session × activity × turn 一行
    # 3. 包含所有实验字段
    # 4. 返回 CSV/JSON 文件下载
```

### 数据完整性要求

1. **时间戳对齐**: 所有 `conversation_events`, `user_vocab_queries`, `essay_results` 需关联到 `session_activities.id`
2. **原始数据快照**: 每次前测/后测导出前，将当前全量数据库备份为 `data/export_snapshots/experiment_{id}_pre_{date}.db`
3. **估算指标标注**: 导出数据中所有估算字段（A4/A8/A14/A15/A18/A20）需标注为 `is_estimated: true`

---

## 9. 可复用开源项目/设计清单

| 开源项目 | 可复用概念 | HELIX 对应用法 | 许可证 | 复用方式 |
|---------|-----------|---------------|-------|---------|
| **Moodle Groups** | 按组管理学生、实验组/对照组 | 借鉴 Groups 的数据模型，不直接集成 Moodle | GPL 2.0 | 仅借鉴设计 |
| **Moodle Gradebook** | 学生成绩记录 + 前测/后测 | 借鉴 gradebook 的 grade_item/grade_grade 概念 | GPL 2.0 | 仅借鉴设计 |
| **Moodle xAPI** | 学习事件记录 API | 借鉴 `actor/verb/object` 三元组设计 HELIX event schema | GPL 2.0 | 仅借鉴设计 |
| **Open edX Course/Run** | 课程→学期→选课分层 | 对应 HELIX Course→Lesson→ClassroomSession | AGPL 3.0 | 仅借鉴设计 |
| **Open edX LMS/Studio** | 学生端/管理端分离 | 对应 HELIX Web 课堂版与教师控制台 | AGPL 3.0 | 仅借鉴设计 |
| **H5P xAPI** | 互动内容触发学习事件 | 课后练习内容可参考 H5P 的类型体系 | MIT | 借鉴设计 |
| **BigBlueButton 角色模型** | moderator/viewer/participant | 对应 HELIX 教师/发言学生/旁听学生 | LGPL 3.0 | 仅借鉴角色设计 |
| **BigBlueButton 会议管理** | API 创建/销毁房间 | HELIX 可选借鉴 classroom_session 生命周期管理 | LGPL 3.0 | 仅借鉴设计 |
| **Tesseract OCR** | PaddleOCR 替代方案 | 如果 PaddleOCR 冻结后需要 OCR 能力 | Apache 2.0 | 可直接集成 |
| **mkcert** | 本地自签证书 | 教师机 HTTPS 部署 | BSD | 可直接集成 |

> **注意**: Moodle( GPL 2.0)、Open edX( AGPL 3.0)、BigBlueButton( LGPL 3.0) 的许可证与 HELIX 现有许可证（MIT）不兼容，**不应直接复制代码**。仅借鉴设计/数据模型概念。

---

## 10. 预计工作量和最大风险

### 工作量汇总

| 阶段 | 事项 | 工作量 | 依赖 |
|------|------|-------|------|
| **已完成基础项** (✅ 已完成) | build 修复、MinIO 防护、static mount、WS JWT 身份、vocab/essays 去 user_id 伪造、课堂数据模型骨架、classroom API、analytics 教师端入口权限、research export API | 已完成 | — |
| **Phase 1: 数据归属统一** (✅ 第 5 轮已完成) | analytics `resolve_class_id_for_user` / `get_class_user_ids` 对齐 ClassEnrollment | S (1-2天) | 已完成基础项 |
| **Phase 2: 语音课堂轮流练** (✅ 第 6 轮已完成) | 当前发言人、非当前学生音频拒收、ActivityTurn 自动落库 | M-L (1-2周) | Phase 1 |
| **Phase 3: Web 局域网访问/部署准备** (✅ 第 7 轮已完成) | FastAPI 静态托管、局域网访问、HTTPS/WSS 预案 | M (1周) | Phase 1-2 |
| **后续冻结项** (📋 暂列后续) | CSSCI 深度导出、pre/post test、teacherAnalytics 大 UI、学生旁听视图、并发压测、生产级 HTTPS 部署 | 后续评估 | Phase 1-3 |

> **2026-06-03 第 5 轮更新**: Phase 1（analytics 数据归属统一到 ClassEnrollment / Classroom）已完成；Codex 集成回归已通过 140 个相关测试。当前工程范围仍截止到 Phase 3；下一轮进入 Phase 2 课堂轮流练最小闭环。Phase 4+ 暂列后续，不作为当前实现目标。

> **2026-06-03 第 6 轮更新**: Phase 2（课堂轮流练最小闭环）已完成；新增 current speaker API、`CLASSROOM_AUDIO_REJECTED` 事件、课堂 `SessionActivity`/`ActivityTurn` 最小落库。Codex 集成回归已通过 146 个相关测试。下一轮进入 Phase 3 Web 局域网访问/部署准备；Phase 4+ 继续冻结。

> **2026-06-03 第 7 轮更新**: Phase 3（Web 局域网访问/部署准备）已完成；前端默认后端地址在静态 Web/LAN 场景改为同源，保留 Vite/Electron 开发默认 `localhost:8012`；新增 `scripts/start_lan_web.ps1` 用于构建前端并在 `0.0.0.0:8012` 托管。当前要求的 Phase 1-3 到此收口，Phase 4+ 继续冻结。

**总预计工作量**: 约 8-12 人周（2-3 人团队约 4-6 周）

### 最大风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| **Kimi API 课堂不可用**（网络/配额/限流） | 中 | **高** — 语音对话核心不可用 | Kimi API + 本地 Qwen 竞速机制已实现但需验证 30 人并发时的表现；准备模拟模式用于不可用时的演示 |
| **30 人同时 ASR 撑爆 CPU** | 高 | **高** — 课堂轮流练延迟不可接受 | 限制并发 ASR 线程数（Semaphore）+ 一次只允许 1 人发言。RTX 5080 16GB 可作为 ASR GPU 推理候选，但 SeamlessM4T 当前是 CPU 路径 |
| **npm build 修复后级联错误** | 中 | **高** — 前端停摆 | voice.ts 的 `}` 缺失导致多个级联错误（TS1005）。修复后可能暴露新错误。需逐行验证 |
| **自签 HTTPS 导致学生设备访问受阻** | 中 | **中** — 课堂第一印象差 | 教室内批量分发 mkcert 根证书，或在教师机上配置受信任证书（如有 Windows AD/域） |
| **前端教师界面 9 月前开发不完** | 中 | **中** — 课堂控制依赖 WebSocket 手工操作 | 优先完成"列表点名 + 发起对话"核心功能，可视化仪表盘可后补 |
| **CSSCI 数据不完整** | 低 | **中** — 论文数据不可用 | 需在实验开始前确认所有实验字段已覆盖。建议 8 月底做一次模拟实验验证数据采集完整性 |
| **context_store.py 死代码引发现状误判** | 低 | **低** — 徒增分析工作量 | 已确认是死代码，删除或标识为 `@deprecated` |

---

## 附录 A: 贡献者

| 角色 | Agent 名称 | 审计范围 |
|------|-----------|---------|
| Subagent 1 | subagent-1-identity-classroom | 身份、班级、课堂与实验数据模型 |
| Subagent 2 | subagent-2-voice-turn-taking | 语音对话与课堂轮流机制 |
| Subagent 3 | subagent-3-context-management | 上下文管理、存档、恢复、模型调用 |
| Subagent 4 | subagent-4-web-classroom | Web 课堂版可行性 |
| Subagent 5 | subagent-5-data-closed-loop | 查词、作文、学情分析数据闭环 |
| Subagent 6 | subagent-6-dependency-audit | 可选依赖与开源替代 |
| Aggregator | (父 agent 直接合成) | 总控汇总 |

## 附录 B: 在线调研来源

- Moodle xAPI Developer Resources: https://moodledev.io/docs/4.5/apis/subsystems/xapi
- Moodle Groups/Gradebook 概念: 官方文档概览
- Open edX Platform Architecture: https://docs.openedx.org/en/latest/developers/references/developer_guide/architecture.html
- BigBlueButton Architecture: http://bigbluebutton.github.io/2.4/architecture.html
- H5P xAPI Integration: https://h5p.org/documentation/x-api
- Open edX Course Enrollment: https://edx.readthedocs.io/projects/open-edx-building-and-running-a-course/en/open-release-sumac.master/manage_live_course/course_enrollment.html
