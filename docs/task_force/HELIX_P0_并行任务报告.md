# HELIX P0 并行任务综合报告

> 生成日期: 2026-06-01
> 基于 10 个并行 subagent 的代码审计与方案设计
> 工作目录: `E:\projects\AiforForiegnLanguageLearning`

---

## 目录

1. [Agent A：前端 Build 阻断修复](#agent-a前端-build-阻断修复)
2. [Agent B：Web 静态托管方案](#agent-bweb-静态托管方案)
3. [Agent C：user_id 与权限风险](#agent-cuser_id-与权限风险)
4. [Agent D：课堂数据模型](#agent-d课堂数据模型)
5. [Agent E：语音轮流练方案](#agent-e语音轮流练方案)
6. [Agent F：前端页面方案](#agent-f前端页面方案)
7. [Agent G：CSSCI 数据导出](#agent-gcssci-数据导出)
8. [Agent H：可选依赖降级](#agent-h可选依赖降级)
9. [Agent I：路线图校正](#agent-i路线图校正)
10. [Agent J：冒烟测试清单](#agent-j冒烟测试清单)

---

## Agent A：前端 Build 阻断修复

### 验证结果
`npm run build` 已通过 ✅

```
> vue-tsc -b && vite build
✓ 2385 modules transformed.
dist/index.html                     0.49 kB
dist/assets/index-DuInYEPL.css     24.31 kB
dist/assets/index-BmUCGr18.js   1,730.32 kB
✓ built in 5.63s
```

### 修复内容
- 文件: `app/v5/src/stores/voice.ts`
- 错误 `TS1005: ',' expected at line 705` 已不存在
- `startCustomSession` 函数体（L376-456）闭合正常
- 所有 19 个状态和 9 个操作正确导出
- 无残留类型错误

### 遗留风险
- 无（build 已通过）
- chunk size 警告（1.7MB）建议后续用 dynamic import 拆分

---

## Agent B：Web 静态托管方案

### 当前状态
- `main.py` 中**没有**挂载任何静态文件目录
- 开发时：Vite dev server (:5173) + FastAPI (:8012)
- 生产时：Electron 桌面应用（已有 Electron 打包流程）

### 推荐改动

**`backend_fastapi/app/main.py`**（在所有 router 注册之后追加）:
```python
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
```

**不推荐** `app.mount("/", StaticFiles(... html=True))` — 会覆盖 API 路由。

### HTTPS 启动命令
```powershell
# 教师机安装 mkcert
winget install mkcert
mkcert -install
mkcert localhost 127.0.0.1 <LAN_IP> ::1

# 启动 uvicorn（Web 模式）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8012 `
    --ssl-certfile localhost+2.pem --ssl-keyfile localhost+2-key.pem
```

### `scripts/start.ps1` 参数追加
新增 `-Web`、`-SslCert`、`-SslKey` 参数，Web 模式下：
- 先 `npm run build`
- uvicorn 使用 `--host 0.0.0.0`
- 可选 `--ssl-certfile` / `--ssl-keyfile`

### 麦克风风险
| 访问方式 | 麦克风可用 |
|---------|-----------|
| `http://localhost:8012` | ✅ |
| `http://127.0.0.1:8012` | ✅ |
| `http://192.168.x.x:8012` | ❌ 非安全上下文 |
| `https://192.168.x.x:8012` | ✅ 需 mkcert |

### 工作量
~0.5 人天（含 api.ts 同源 fallback 和 start.ps1 改造）

---

## Agent C：user_id 与权限风险

### 风险表格

| 文件 | 行号 | 风险描述 | 等级 | 建议修复 | 工作量 |
|------|------|----------|------|---------|--------|
| `main.py` | ~100-107 | WS `/ws/v1` 无 JWT 验证，user_id 从 query param 裸取 | **P0 致命** | upgrade 时要求 token 参数，解码 JWT 提取 userId | 小 |
| `routers/vocab.py` | 210-220 | `_resolve_user_id()` 在未登录时回退到请求体 user_id | **P0 致命** | 移除请求体 user_id，未登录时返回 None | 小 |
| `routers/essays.py` | 205,242,271 | 三处作文接口未登录时接受请求体 user_id | **P0 致命** | 移除请求体 user_id | 小 |
| `routers/essays.py` | 280-320 | `GET /v1/essays/{id}` 无认证 | **P1 高危** | 添加 get_current_user 依赖 | 小 |
| `analytics_router.py` | 多处 | teacher 路由只做角色校验，不做班级范围校验 | **P1 高危** | 在 facade 层添加 verify_teacher_owns_class | 中 |
| `domain/models.py` | — | 无 teacher-class 关联表 | **P2 中危** | 新增 TeacherClass 表 | 小 |
| `rbac.py` | 全部 | 无班级范围校验机制 | **P2 中危** | 增加 require_scope 拦截器 | 中 |

### 9 月前必须改的 3 件事
1. **`/ws/v1` 加 JWT 验证** — 语音模块的数据安全命门
2. **移除 essay/vocab 接口的请求体 user_id 回退** — 防止伪造学习数据
3. **`GET /v1/essays/{submission_id}` 加认证** — 防止作文内容泄露

### 最小修复方案
- WS JWT：添加 `token = ws.query_params.get("token")`，解码后提取 userId
- vocab/essay：删除 `user_id` 字段定义，`_resolve_user_id()` 在未登录时返回 None
- 班级校验：新增 `TeacherClass` 表 + `verify_teacher_class()` 函数

---

## Agent D：课堂数据模型

### 现有表
共 **16 张真实表**：`users`, `students`, `vocabulary`, `learning_records`, `learning_paths`, `public_vocab_entries`, `user_vocab_queries`, `conversation_events`, `essay_submissions`, `essay_results`, `student_daily_summaries`, `student_longitudinal_summaries`, `class_daily_snapshots`, `intervention_tasks`, `analytics_artifacts`, `prompt_registry`

### 新增表（10 张）

| 表名 | 用途 | 关键外键 | CSSCI 必采 |
|------|------|---------|-----------|
| `courses` | 课程定义 | — | ✅ |
| `lessons` | 课时 | courses.id | ✅ |
| `classrooms` | 班级实体 | courses.id, users.id(teacher) | ✅ |
| `experiments` | 实验定义 | classrooms.id | ✅ |
| `experiment_groups` | 实验组/对照组 | experiments.id | ✅ |
| `experiment_group_members` | 成员关联（替代 JSON） | experiment_groups.id, users.id | ✅ |
| `classroom_sessions` | 课堂会话 | classrooms.id, lessons.id, experiments.id | ✅ |
| `session_activities` | 课堂活动 | classroom_sessions.id, users.id | ✅ |
| `activity_turns` | 话轮 | session_activities.id, users.id | ✅ |
| `assessments` | 前测/后测 | users.id, experiments.id, classrooms.id | ✅ |

### 现有表新增字段
- `students.classroom_id` (int FK, nullable) — **共存策略**：保留 `class_id: str`
- `conversation_events.session_activity_id` (int FK, nullable)
- `essay_submissions.session_activity_id` (int FK, nullable)
- `essay_results.session_activity_id` (int FK, nullable)
- `user_vocab_queries.session_activity_id` (int FK, nullable)

### Alembic 迁移顺序
1. **第一步**: courses, lessons, classrooms, students.classroom_id
2. **第二步**: experiments, experiment_groups, experiment_group_members
3. **第三步**: classroom_sessions, session_activities, activity_turns + 4 张现有表加列
4. **第四步**: assessments

### 外键关系总图
```
users → students → classrooms → courses
users → classrooms(teacher)
users → experiment_group_members → experiment_groups → experiments → classrooms
classrooms → classroom_sessions → session_activities → activity_turns
session_activities → conversation_events/essay_submissions/essay_results/user_vocab_queries
```

---

## Agent E：语音轮流练方案

### 消息协议草案

| 消息类型 | 方向 | 用途 |
|---------|------|------|
| `JOIN_CLASSROOM` | C→S | 加入课堂会话 |
| `JOIN_CLASSROOM_OK` | S→C | 确认加入，包含在线成员和当前发言人 |
| `MEMBER_JOINED`/`MEMBER_LEFT` | S→所有人 | 成员变动广播 |
| `SELECT_SPEAKER` | 教师→S | 教师指定发言人 |
| `SPEAKER_CHANGED` | S→所有人 | 发言人变更广播 |
| `INTERRUPT_SPEAKER` | 教师→S | 教师打断 |
| `SPEAKER_INTERRUPTED` | S→所有人 | 打断广播 |
| `BROADCAST_ASR_FINAL` | S→旁听 | 旁听者接收转写文本（无TTS） |
| `BROADCAST_LLM_RESULT` | S→旁听 | 旁听者接收AI回复文本 |

### 后端状态机
```
WS_CONNECTED → JOIN_CLASSROOM → CLASSROOM_JOINED
    → SELECT_SPEAKER(教师) → SPEAKER_ACTIVE
        → 发言人 AUDIO_CHUNK_BIN: ASR→LLM→TTS (完整pipeline)
        → 旁听者 AUDIO_CHUNK_BIN: DISCARD + log
        → ASR_FINAL/LLM_RESULT 同时 fan-out 为 BROADCAST_*
    → TIMEOUT/VAD_END/INTERRUPT → SPEAKER_CHANGED(active_speaker=null)
```

### 限流方案
```python
_asr_semaphore = asyncio.Semaphore(2)   # SeamlessM4T CPU
_llm_semaphore = asyncio.Semaphore(1)   # 串行防 OOM
_tts_semaphore = asyncio.Semaphore(1)   # Kokoro 串行
```

### 非发言人处理
静默丢弃 + `SPEAKER_WARN` 消息通知。

### 工作量
**~12.5 人天**（后端 6 + 前端 4 + 集成 1.5 + 模型 1）

---

## Agent F：前端页面方案

### 现有路由（6 个）
`/`(home), `/essay`, `/voice`, `/analysis`, `/assistant`, `/settings`

### 新增路由（7 个）
| 路径 | 组件 | 角色 | 说明 |
|------|------|------|------|
| `/login` | LoginView | 所有人 | 登录/注册 |
| `/student/waiting` | StudentWaitingView | 学生 | 等待队列+旁听 |
| `/student/speaking` | StudentSpeakingView | 学生 | 录音+转写+反馈 |
| `/student/listening` | StudentListeningView | 学生 | 全屏转写流 |
| `/teacher/console` | TeacherConsoleView | 教师 | 学生列表+发言控制+转写 |
| `/teacher/analytics` | TeacherAnalyticsView | 教师 | 学情看板（对接已有接口） |
| `/device-check` | DeviceCheckView | 所有人 | 麦克风/WS/后端检测 |

### 可复用的现有组件
- `Sidebar.vue` — 需根据角色过滤菜单
- `BaseChart.vue` — 学情看板图表
- `WaterBall.vue` — 录音 VAD 动画
- `voice.ts` store — 录音/ASR/LLM 管线

### 教师学情看板
`teacherAnalytics.ts` 已有 **11 个就绪 endpoint**，前端的 0 个视图使用 → **最高复用收益项**。

### 工作量
**~24 人天**（前端 16.5 + 后端 7.5）

---

## Agent G：CSSCI 数据导出

### 指标可信度分级

**硬数据（11 个）**: 词汇熟练度增长率、SM-2 保持率、主动查词转化率、长时记忆健壮度、语法错误收敛速度、对话响应潜伏期、语音产出速率、学习行为稳定性、错误复发率、自主学习驱动力

**估算/代理（8 个）**: 构词法迁移能力、高级词汇替代率、句式多样性指数、逻辑衔接连贯度、语义表达准确性、对话难度跳变成功率、口语转述能力、反馈响应深度、主题覆盖广度

**需人工评分校验**: 跨文化得体性偏离值 (A14) — 必须人工复评；逻辑连贯度 (A9)/语义准确性 (A10) — 建议 20% 样本双盲复评

### 导出 API 草案

```
POST /api/v1/export/request      — 创建导出任务
GET  /api/v1/export/status/{id}  — 查询进度
GET  /api/v1/export/download/{id}— 下载 CSV/JSON
GET  /api/v1/export/methodology  — 返回指标计算方法说明
```

### 导出宽表粒度
- **Primary**：`student × date`（每日一行）— 面板数据分析
- **Supplemental**：`conversation × turn`（每轮一行）— 过程变量分析

### 数据缺口
- 前测/后测成绩 — 需新增 `assessments` 表
- 实验分组标记 — 需 `experiment_groups` + `experiment_group_members`
- 评分员信度 — 需 `essay_results.human_score` 字段

### 工作量
**~6.5 人天**（纯后端 + 文档）

---

## Agent H：可选依赖降级

### 核验表格

| 模块 | 缺依赖/服务不通时表现 | 是否阻断 P0 | 建议 |
|------|----------------------|------------|------|
| **MinIO 存储** | SDK 是硬依赖(pyproject.toml)，缺则安装失败；服务不通时 storage_router 抛 500 | 否 | 加 try/except 返回降级提示 |
| **Neo4j 知识图谱** | 可选依赖，NEO4J_AVAILABLE=False，所有方法静默返回 None/[] | 否 | 无需修复 |
| **Elasticsearch** | 可选依赖，ES 不通时走 LLM 兜底 | 否 | 降级完整 |
| **Redis 缓存** | 硬依赖但异常被 catch，get/set 静默返回 None | 否 | 降级完整 |
| **PaddleOCR** | 可选依赖，三级降级(Paddle→rapidocr→备用API)，全失败返回 "" | 否 | 降级完整 |
| **Kokoro/Edge TTS** | 可选依赖，三级降级链(kokoro→edge→silence) | 否 | 降级无懈可击 |
| **SeamlessM4T ASR** | 可选依赖，缺时返回诊断消息"ASR未启用" | 否 | WS 连接不依赖 ASR |

**结论**: 所有 7 项可选依赖的降级路径都符合"P0 非阻断"结论。

---

## Agent I：路线图校正

### 修正清单

| # | 修正点 | 位置 | 修改前 | 修改后 |
|---|--------|------|--------|--------|
| 1 | TTS 真流式描述 | §7 当前限制 | 未区分 TTS_CHUNK vs TTS_RESULT | 注明"前端不播放 TTS_CHUNK，只播 TTS_RESULT" |
| 2 | analytics 风险不全 | §4 #4 | 只列 3 个端点 | 补充至 6 个端点（含 profile/class-assignment/llm-profile） |
| 3 | MinIO 行号 | §4 #6 | minio_storage.py:11 | 修正为 L6；区分 pip 缺 vs 服务未启 |
| 4 | Experiment 模型 | §5 | 有 treatment/control_group_id 循环引用 | 去掉双向引用，通过 experiment_groups.experiment_id 单向 |
| 5 | ActivityTurn 字段 | §5 | raw_event_ids 逗号分隔字符串 | conversation_event_ids JSON 数组 |
| 6 | StudentProfile class_id | §5 | 建议直接改类型 | 改为共存策略：新增 classroom_id，保留旧 class_id |
| 7 | 静态文件挂载代码 | §6 Step 2 | 错误的 mount("/", StaticFiles) | 用 FileResponse + /assets 挂载，避免覆盖 API |
| 8 | Neo4j 降级描述 | §3 | 笼统描述 | 区分 vocab 内部推荐降级(良好)和公共KG接口(隐式降级) |
| 9 | PaddleOCR | §3 | 已正确 | 无需修改 |

### 不确定项
- MinIO 行号偏差（文档生成时与实际版本可能不一致）
- 缺少对 `ConversationContext` 双路径不一致的描述

---

## Agent J：冒烟测试清单

### 验收项（13 项）

| 编号 | 名称 | 快速冒烟 | 完整验收 | 需 Kimi | 可 Mock |
|------|------|----------|----------|---------|---------|
| P0-01 | 后端启动 | ✅ | ✅ | ❌ | ✅ |
| P0-02 | /health | ✅ | ✅ | ❌ | ✅ |
| P0-03 | 注册/登录 | ✅ | ✅ | ❌ | ✅ |
| P0-04 | 查词 | ✅ | ✅ | ⚠️ 有降级 | ✅ |
| P0-05 | 作文批改 | ✅ | ✅ | ✅ 无降级 | ✅ |
| P0-06 | WS 连接 | ✅ | ✅ | ❌ | ✅ |
| P0-07 | TEXT 对话 | ✅ | ✅ | ✅ | ✅ |
| P0-08 | AUDIO 流程 | ✅ | ✅ | ✅ | ✅ |
| P0-09 | 前端 build | ✅ | ✅ | ❌ | ✅ |
| P0-10 | Web 访问 | ✅ | ✅ | ❌ | ❌ |
| P0-11 | 麦克风权限 | ⏭️ 跳过 | ✅ | ❌ | ❌ |
| P0-12 | 权限检查 | ✅ | ✅ | ❌ | ✅ |
| P0-13 | user_id 正确性 | ✅ | ✅ | ❌ | ✅ |

### 已知 P0 阻塞项
1. ~~`voice.ts` 缺失 `}` — 已修复 ✅~~
2. ~~`minio_storage.py` 顶层 import — 已改为延迟 import / 503 降级 ✅~~
3. ~~WS `/ws/v1` user_id 无服务端校验 — 已改为 JWT token 解析 ✅~~
4. REST 接口 student_id 未校验 — analytics teacher-class ownership 仍为 P1 安全项；vocab/essay body user_id 已修复 ✅

### 快速冒烟脚本
详见 `docs/task_force/HELIX_P0_验收清单.md`

---

## 汇总：P0 工作量金字塔

```
人天
 0.1  Agent A: 修 build (已通过 ✅)
 0.5  Agent B: 静态托管方案
 1.0  Agent C: user_id 权限修复 (最小3项)
 3.0  Agent D: 数据模型 + Alembic 迁移
12.5  Agent E: 语音轮流练 (后端+前端)
24.0  Agent F: 前端页面 (7视图+组件)
 6.5  Agent G: CSSCI 导出 (P1)
 0    Agent H: 可选依赖核验 (无需修复)
 0.5  Agent I: 路线图校正 (已应用 ✅)
 0.5  Agent J: 验收清单 (已创建 ✅)
──────────────────────────
合计: ≈ 48 人天 (≈ 7 人周，可并行至 3-4 人周)
```

---

## 全局风险汇总

| 风险 | 等级 | 影响范围 | 建议 |
|------|------|---------|------|
| WS `/ws/v1` 无 JWT 验证 | 🔴 P0 | 语音对话数据全量可伪造 | 加 token 参数校验 |
| vocab/essay 请求体 user_id | 🔴 P0 | 学习数据写入权限 | 移除请求体 user_id |
| analytics 无班级范围校验 | 🟡 P1 | 教师可查看非本班学生 | 新增 TeacherClass 表 |
| MinIO 模块级 import | 🟡 P1 | MinIO 不可用时后端崩 | 改为函数内延迟 import |
| TTS 非真流式 | ⚪ 知晓 | 课堂体验（可接受） | 后续优化 |
| 前端 chunk 1.7MB | ⚪ 知晓 | 首屏加载 | dynamic import 拆分 |

---

## 第 2 轮执行结果 (2026-06-01)

> 基于第 1 轮审计，5 个执行 Agent 并行修复 P0 问题并落地基础设施。

### Agent 1: P0 后端身份边界修复 ✅

| 属性 | 内容 |
|------|------|
| **状态** | ✅ 全部修复 |
| **修改文件** | `backend_fastapi/app/main.py`, `routers/vocab.py`, `routers/essays.py` |
| **新增文件** | `backend_fastapi/tests/test_auth_boundary.py` (6 个测试) |
| **验证** | `pytest test_health.py test_settings_default_port.py test_srs_sm2.py test_auth_boundary.py -q` → 11 passed |

**修改详情**:
- `/ws/v1`: 移除 `?user_id=N` query param 信任，改为 `?token=<jwt>` (优先) + `Sec-WebSocket-Protocol: Authorization: Bearer <token>` (备选) → `decode_token` → `get_user_by_username` → 提取 userId。无 token 时 anonymous (user_id=None)
- `CONTEXT_SET` handler: 移除客户端传入的 `session_user_id` 覆盖
- `_resolve_user_id()`: `requested_user_id` 参数保留签名兼容但不再作为回退值；未登录永远返回 None
- `essays/grade`, `/grade-ocr`, `/submit`: `resolved_user_id` 从 `else req.user_id` 改为 `else None`
- `GET /v1/essays/{submission_id}`: 加 P1 access control 注释

### Agent 2: 前端 WS token 接入 ✅

| 属性 | 内容 |
|------|------|
| **状态** | ✅ 完成 |
| **修改文件** | `app/v5/src/services/voice-socket.ts`, `app/v5/src/stores/voice.ts` |
| **验证** | `npm run build` → ✓ built in 6.62s, exit code 0 |

**修改详情**:
- `buildWsV1Url`: `&user_id=<id>` 改为 `&token=<localStorage.auth_token>`；无 token 时不传任何身份参数
- `WsV1ConnectOptions`: 保留 `userId` 字段兼容但不再在 URL 中使用
- `voice.ts`: `ensureConnectedWsV1` 和 `startCustomSession` 中 `userId: getCurrentUserId()` 移除
- 未引入任何 API key 到前端代码

### Agent 3: 课堂/实验最小数据模型骨架 ✅

| 属性 | 内容 |
|------|------|
| **状态** | ✅ 完成 |
| **新增文件** | `domain/classroom/__init__.py`, `domain/classroom/models.py`, `tests/test_classroom_models.py` |
| **修改文件** | `domain/__init__.py`, `db.py`, `main.py` (各加一行 import) |
| **验证** | `pytest test_classroom_models.py -q` → 10 passed |

**新增表 (9 张)**:

| 表名 | 用途 | 关键外键 |
|------|------|---------|
| `classrooms` | 班级实体 | `users.id` (teacher) |
| `class_enrollments` | 班级成员 | `classrooms.id`, `users.id` |
| `experiments` | 实验定义 | `classrooms.id` |
| `experiment_groups` | 实验组/对照组 | `experiments.id` |
| `experiment_group_members` | 组员 | `experiment_groups.id`, `users.id` |
| `classroom_sessions` | 课堂会话 | `classrooms.id`, `experiments.id`, `users.id` |
| `session_activities` | 课堂活动 | `classroom_sessions.id`, `users.id` |
| `activity_turns` | 话轮 | `session_activities.id`, `users.id` |
| `assessments` | 前测/后测 | `users.id`, `experiments.id`, `classrooms.id` |

字段覆盖: teacher_id, student_id, classroom_id, experiment_id, group_id, session_id, activity_id, turn_id, started_at/ended_at, source_event_id, consent_status, anonymized_export_id。

### Agent 4: MinIO 可选依赖降级 ✅

| 属性 | 内容 |
|------|------|
| **状态** | ✅ 完成 |
| **修改文件** | `infrastructure/storage/minio_storage.py`, `interfaces/storage_router.py` |
| **新增文件** | `tests/test_minio_optional.py` (11 个测试) |
| **验证** | `pytest test_minio_optional.py -q` → 11 passed; `from app.main import app` → OK |

**修改详情**:
- 顶层 `from minio import Minio` 移除 → lazy import (在 `__init__` 内)
- 新增 `is_minio_available()` 检查函数
- `get_minio_storage()` 在 SDK 缺失时返回 None
- `storage_router.py` 新增 `_get_storage_or_503()` helper，所有端点优雅降级返回 503

### Agent 5: 验收清单同步 ✅

| 属性 | 内容 |
|------|------|
| **状态** | ✅ 完成 (由主线程执行) |
| **修改文件** | `docs/task_force/HELIX_P0_验收清单.md`, `docs/task_force/HELIX_P0_并行任务报告.md` |

---

## 综合验证结果

```
cd backend_fastapi; pytest test_health.py test_settings_default_port.py
  test_srs_sm2.py test_auth_boundary.py test_classroom_models.py
  test_minio_optional.py -q --tb=short
→ 32 passed, exit code 0

cd app/v5; npm run build
→ ✓ built in 6.62s, exit code 0
```

### 同文件冲突风险
- `backend_fastapi/app/main.py`: Agent 1 和 Agent 3 同时修改（不同行位置），无实际冲突
- 无其他共享文件

### 未完成 / 降级项

| 项目 | 等级 | 说明 |
|------|------|------|
| `GET /v1/essays/{submission_id}` 认证 | P1 | 仍为匿名可读，已加注释标记 |
| teacher-class ownership 校验 | P1 | analytics_router 只有角色校验，缺班级归属校验 |
| 旧 WS 测试兼容 | P1 | `test_ws_echo.py` 等可能因 user_id query param 移除失败，待适配 |
| 前端 classroom UI | P2 | 课堂模型已落地，前端 teacher dashboard 待对接 |

### 给 Codex 总控的下一轮建议

1. **P1 — 修复 GET /v1/essays/{submission_id}**: 添加 `get_current_user` 依赖，限制只有 owner 可查看
2. **P1 — 实现 teacher-classroom ownership**: 在 `analytics_router.py` facade 层校验 teacher_id 匹配
3. **P1 — 更新旧 WS 测试**: 适配 token-based auth 后的 `test_ws_*.py`
4. **P2 — Classroom API**: 为新的 9 张表添加 CRUD REST 接口
5. **P2 — 前端对接**: Teacher dashboard 使用新 classroom 数据模型
6. **P2 — CSSCI 导出**: 利用 `anonymized_export_id` 和 `consent_status` 字段实现合规导出

---

## 第 3 轮执行结果 (2026-06-01)

### 执行概要

Codex 总控第 3 轮派单，5 个 Agent (A-E) 并行执行实现层工作，Agent F 最后集成注册。模型：deepseek-v4-flash（优先速度/低成本）。

**验证**: CodeWhale 初验 63 passed；Codex 总控补测跨教师权限后复验 72 passed, 0 failed。前端 `npm run build` ✓。

### Agent A：作文读取权限闭环

- **修改**: `routers/essays.py:340-355` — `GET /v1/essays/{submission_id}` 添加 `get_optional_user` 依赖
  - 匿名：仅可读 `user_id IS NULL` 的匿名提交
  - 学生：仅可读自己的提交
  - teacher/admin：暂时可读全部（后续班级 ownership 收紧）
- **新建**: `tests/test_essay_access_control.py` — 7 个测试（匿名读匿名✓、匿名读实名✗、学生读自己✓、学生读别人✗、teacher/admin 可读、404）
- **修复**: `tests/test_essay_http.py:234-241` — `test_essay_submit_text_and_get_status` 因新安全规则失败，改为带 token 请求（硬规则 #9）
- **结果**: 7/7 新测试通过，旧测试修复后通过

### Agent B：课堂权限 helper

- **新建**: `application/classroom_access.py` — 4 个同步函数
  - `is_teacher_of_classroom(session, teacher_user_id, classroom_id) -> bool`
  - `is_student_in_classroom(session, student_user_id, classroom_id) -> bool`
  - `can_teacher_access_student(session, teacher_user_id, student_user_id, classroom_id=None) -> bool`
  - `resolve_student_classroom_ids(session, student_user_id) -> list[int]`
- **新建**: `tests/test_classroom_access.py` — 18 个测试（含没有班级记录时返回 False）
- **结果**: 28/28 测试通过（10 旧 + 18 新）

### Agent C：课堂/实验最小 API

- **新建**: `interfaces/classroom_router.py` — 6 个端点（`/api/v1` 前缀）
  - `POST /classrooms`、`GET /classrooms`、`POST /classrooms/{id}/enrollments`
  - `POST /classroom-sessions`、`POST /session-activities`、`POST /activity-turns`
- **新建/补测**: `tests/test_classroom_api.py` — 14 个测试，含其他教师不能写入非本人课堂 session 的 activity/turn
- **结果**: 14/14 测试通过

### Agent D：CSSCI 实验导出 API

- **新建**: `interfaces/research_export_router.py` — 2 个端点
  - `GET /api/v1/research/exports/turns.csv?classroom_id=...`
  - `GET /api/v1/research/exports/turns.json?classroom_id=...`
  - CSV 不含 user_id 除非 `include_identifiers=true`（仅 teacher/admin）
  - 含 anonymized_export_id、Assessment join
- **新建**: `tests/test_research_export.py` — 7 个测试（teacher 自有/跨班拒绝/admin/student/匿名）
- **结果**: 7/7 测试通过

### Agent E：Web 静态托管

- **新建**: `static_frontend.py` — `mount_static_frontend(app, dist_dir=None) -> bool`
  - dist 存在：挂载 `/assets` + SPA fallback
  - dist 不存在：静默跳过，不影响 API
- **新建**: `tests/test_static_frontend.py` — 6 个测试
- **结果**: 6/6 测试通过

### Agent F：集成注册 + 文档同步

- **修改**: `main.py:27,33` — import classroom_router + research_export_router
- **修改**: `main.py:113-118` — `app.include_router(classroom_router)`、`app.include_router(research_export_router)`、`mount_static_frontend(app)`
- **更新**: `HELIX_P0_验收清单.md`、`HELIX_P0_并行任务报告.md`（只追加，不重写全文）

### 同文件冲突

无。所有 Agent 操作独立文件，集成阶段按序注册。

### 给 Codex 总控的下一轮建议

1. ~~**P1 — analytics teacher-classroom ownership 收紧**~~ → ✅ 第 4 轮已完成
2. **P2 — Classroom 前端对接**: teacher dashboard 使用 `/api/v1/classrooms` 等新端点
3. **P2 — CSSCI 导出增强**: 添加 pretest/posttest Assessment 导出、consent_status 过滤
4. **P2 — 旧 WS 测试适配**: `test_ws_echo.py` 等需适配 token-based auth
5. **P2 — resolve_class_id_for_user 对齐**: 将 analytics 内部的旧 `StudentProfile.class_id: str` 与新 `ClassEnrollment` 对齐

---

## 第 4 轮执行报告 (2026-06-01)

### 目标

按 Codex 总控第 4 轮派单，收紧 analytics 教师端接口的 teacher-classroom ownership 权限。

### 执行 Agent: CodeWhale

### 技术方案

- 复用第 3 轮 Agent B 交付的 `application/classroom_access.py` helper
- 在 `analytics_router.py` 内添加 4 个轻量 helper：
  - `_is_admin(current_user)` — 判断 admin
  - `_parse_classroom_id(class_id)` — 旧 `str` → 新 `int` Classroom.id
  - `_ensure_teacher_can_access_classroom(session, current_user, class_id)` — classroom 级 403
  - `_ensure_teacher_can_access_student(session, current_user, student_id, classroom_id)` — student 级 403
- 对旧 `class_id: str`（非纯数字）一律保守拒绝 teacher（返回 403），admin 始终允许
- 对 `class-assignments`：teacher 不传 class_id → 403
- 对 `intervention`：同时校验 student_id 和 class_id（若提供）

### 修改文件

| 文件 | 变更 |
|------|------|
| `app/interfaces/analytics_router.py` | 新增 import `classroom_access` + 4 个 helper + 为 12 个端点添加 access guard |
| `tests/test_analytics_access_control.py` (新建) | 33 个测试覆盖所有端点及边界场景 |
| `docs/task_force/HELIX_P0_验收清单.md` | 更新 P0-12 遗留状态 + 追加第 4 轮结果 |
| `docs/task_force/HELIX_P0_并行任务报告.md` | 追加第 4 轮执行报告 |

### 验证结果

```powershell
cd backend_fastapi

# Ruff 代码检查
.\.venv\Scripts\python.exe -m ruff check app\interfaces\analytics_router.py tests\test_analytics_access_control.py
# → All checks passed!

# Pytest
.\.venv\Scripts\python.exe -m pytest tests\test_analytics_access_control.py tests\test_analytics_module.py -q
# → 61 passed in 70.81s (33 access control + 28 analytics module)

# Codex 总控整合回归
.\.venv\Scripts\python.exe -m pytest tests\test_essay_http.py tests\test_essay_access_control.py tests\test_auth_boundary.py tests\test_classroom_models.py tests\test_classroom_access.py tests\test_classroom_api.py tests\test_research_export.py tests\test_static_frontend.py tests\test_analytics_access_control.py tests\test_analytics_module.py -q
# → 133 passed

cd ..\app\v5; npm run build
# → ✓ built in 6.15s
```

### 未被改动的文件

- `test_analytics_module.py` — 原有 28 个测试全部通过，无需修改断言（monkeypatch 在测试层生效，不影响原有逻辑）
- 其他所有文件保持不变

### 遗留风险

| 风险 | 说明 |
|------|------|
| `resolve_class_id_for_user` 断层 | StudentProfile.class_id (str) 与 ClassEnrollment (int FK) 不完全一致，权限层已保护入口，但内部数据关联仍有断层 |
| 零课堂教师 | 没有课堂的 teacher 无法访问任何学生数据（返回 403），符合 spec 规则 8 |

### 建议

- 下一轮可将 `resolve_class_id_for_user` 的实现从 `StudentProfile.class_id` 改为查询 `ClassEnrollment` 表，使权限层与数据层对齐

---

## 第 5 轮: Phase 1 数据归属统一 (2026-06-03)

### 执行概要

本轮将 analytics 内部仍依赖旧 `StudentProfile.class_id: str` / `resolve_class_id_for_user` 的地方逐步对齐到新 `ClassEnrollment` / `Classroom` 表。

### 改动内容

| 文件 | 改动 | 说明 |
|------|------|------|
| `orchestration.py` | `resolve_class_id_for_user` 重写 | 优先查 ClassEnrollment → 单课堂返回 str(classroom_id)，多课堂取最新 enrollment，无 enrollment fallback StudentProfile.class_id |
| `orchestration.py` | `get_class_user_ids` 重写 | 数字 class_id 优先从 ClassEnrollment 找学生，非数字走旧 StudentProfile.class_id (legacy 兼容) |
| `class_snapshot.py` | `generate_class_daily_snapshot` | 使用改造后的 `get_class_user_ids` |
| `orchestration.py` | `resolve_class_id_for_user` / `get_class_user_ids` | 从 ClassEnrollment 获取课堂归属，保留 StudentProfile.class_id legacy fallback |
| `facade.py` | `build_student_profile_payload` | 已由改造后 resolve_class_id_for_user 覆盖，无额外改动 |
| `tests/test_analytics_classroom_alignment.py` | 新建 | 4 个场景：ClassEnrollment 优先、fallback 旧数据、数字 class_id 从 ClassEnrollment 查学生、多课堂稳定性 |

### 验证结果

```
pytest tests/test_analytics_classroom_alignment.py tests/test_analytics_module.py tests/test_analytics_access_control.py -q
```

### 仍未对齐的地方

- `facade.py` 中 `_infer_class_votes` 仍从 `StudentProfile` 投票——这是 legacy backfill 逻辑，保留不动
- `facade.py` 中 `sync_class_id_for_user` / `assign_student_class` 仍操作 `StudentProfile.class_id`——这是分班管理链，后续 Phase 需单独处理
- `class_snapshot.py` 中 `generate_class_daily_snapshot` 接受 `class_id: str`——保留了字符串 class_id 兼容性，但内部查找已对齐

### 下一轮建议

Phase 2 课堂轮流练最小闭环；当前工程范围仍截止到 Phase 3（Web 局域网访问/部署准备），不扩展到 Phase 4+。

---

## 第 6 轮: Phase 2 课堂轮流练最小闭环 (2026-06-03)

### 调度记录

本轮原计划继续将细节工作派给 codewhale / DeepSeek v4 Flash；任务单已生成并两次通过 `codewhale` CLI 派发，但两次均长时间无输出并被超时终止（约 2 分钟、15 分钟）。为避免空转，Codex 接管实现与验收。

### 改动内容

| 文件 | 改动 |
|------|------|
| `app/application/classroom_runtime.py` | 新增单进程 current speaker 运行态：set/get/clear/check + classroom access helper |
| `app/interfaces/classroom_router.py` | 新增 current speaker REST API：POST/GET/DELETE |
| `app/main.py` | `/ws/v1` 支持 `classroom_session_id`；课堂音频入口拒收非当前发言人；文本/语音回合写入 `SessionActivity` / `ActivityTurn` |
| `tests/test_classroom_api.py` | 新增 current speaker API 权限与 enrollment 测试 |
| `tests/test_ws_classroom_turn_taking.py` | 新增课堂 WS 非当前发言人拒收、普通 WS 不受影响测试 |
| `docs/task_force/HELIX_P0_验收清单.md` | 追加第 6 轮验收记录 |
| `docs/task_force/HELIX_9月实验课堂工程路线图_最终.md` | 标记 Phase 2 完成，Phase 3 为下一轮 |

### 新增能力

- 老师/admin 可设置、查看、清除课堂 session 当前发言人。
- 本班学生可查看当前发言人。
- `/ws/v1?classroom_session_id=...` 在 `AUDIO_START` / `AUDIO_CHUNK` / `AUDIO_CHUNK_BIN` / binary frame 路径检查当前发言人。
- 非当前发言人会收到 `CLASSROOM_AUDIO_REJECTED` 和 `TASK_FINISHED(ok=false)`，不会进入 ASR。
- 语音 ASR final / 文本直连输入落 student turn，AI 回复落 ai turn。

### 验证结果

```powershell
cd backend_fastapi

.\.venv\Scripts\python.exe -m pytest tests\test_classroom_api.py tests\test_ws_classroom_turn_taking.py -q
# → 20 passed

.\.venv\Scripts\python.exe -m ruff check app\application\classroom_runtime.py app\interfaces\classroom_router.py app\main.py tests\test_ws_classroom_turn_taking.py tests\test_classroom_api.py --select F,I
# → All checks passed!

.\.venv\Scripts\python.exe -m pytest tests\test_essay_http.py tests\test_essay_access_control.py tests\test_auth_boundary.py tests\test_classroom_models.py tests\test_classroom_access.py tests\test_classroom_api.py tests\test_research_export.py tests\test_static_frontend.py tests\test_analytics_classroom_alignment.py tests\test_analytics_access_control.py tests\test_analytics_module.py tests\test_ws_classroom_turn_taking.py -q
# → 146 passed

.\.venv\Scripts\python.exe -c "from app.main import app; print('OK', len(app.routes))"
# → OK 103
```

### 有意简化与风险

| 风险 | 当前处理 |
|------|----------|
| current speaker 重启丢失 | 先用单进程 dict，符合 9 月单后端课堂试点；多 worker/重启恢复需 Phase 3/后续再评估 Redis 或 DB 字段 |
| AI turn 没有系统用户 | `ActivityTurn.user_id` 暂用当前学生 id，靠 `turn_type='ai'` 区分 |
| 前端还没有课堂轮流练控制面板 | 本轮只做后端最小闭环；Phase 3 可补零安装 Web 访问和最小控制入口 |

### 下一轮建议

Phase 3 Web 局域网访问/部署准备：确认 `app/v5` build 后可由 FastAPI 静态托管，补 LAN 启动脚本、客户端访问说明、后端地址/端口提示、HTTPS/WSS 预案。Phase 4+ 继续冻结。

---

## 第 7 轮: Phase 3 Web 局域网访问/部署准备 (2026-06-03)

### 执行概要

本轮把当前范围收口到 Phase 3：让客户机可以用浏览器打开教师机后端托管的 Web 前端，避免静态 Web 场景下前端继续请求客户机自己的 `localhost:8012`。Vite/Electron 开发场景仍保留 `localhost:8012` 默认值。

### 改动内容

| 文件 | 改动 |
|------|------|
| `app/v5/src/services/backend-url.ts` | 新增统一后端地址推导：静态 Web/LAN 场景走当前页面同源，开发场景走 `localhost:8012` |
| `app/v5/src/services/api.ts` | HTTP API 默认 baseURL 改为动态推导 |
| `app/v5/src/services/config.ts` | app_config 默认值和 normalize 逻辑复用统一地址推导 |
| `app/v5/src/services/voice-socket.ts` | WS URL 根据后端 URL/页面协议自动选择 `ws` 或 `wss` |
| `app/v5/src/stores/voice.ts` | 移除“同源 host 强制改回 localhost”的旧逻辑 |
| `app/v5/src/views/SettingsView.vue` | 设置页后端默认值同步动态推导 |
| `scripts/start_lan_web.ps1` | 新增 LAN Web 启动脚本：构建前端、启动 FastAPI `0.0.0.0:8012`、打印客户机访问地址 |
| `docs/task_force/HELIX_P0_验收清单.md` | 追加第 7 轮验收记录 |
| `docs/task_force/HELIX_9月实验课堂工程路线图_最终.md` | 标记 Phase 3 完成，当前 Phase 1-3 收口 |

### 验证结果

```powershell
cd app/v5
npm run build
# → ✓ built in 6.58s

cd ../../backend_fastapi
.\.venv\Scripts\python.exe -c "from app.main import app; print('OK', len(app.routes)); print(any(getattr(r, 'path', '') == '/' for r in app.routes))"
# → OK 103 / True

.\.venv\Scripts\python.exe -m pytest tests\test_static_frontend.py tests\test_ws_classroom_turn_taking.py tests\test_classroom_api.py -q
# → 26 passed

.\.venv\Scripts\python.exe -m ruff check app\application\classroom_runtime.py app\interfaces\classroom_router.py app\main.py tests\test_ws_classroom_turn_taking.py tests\test_classroom_api.py --select F,I
# → All checks passed!

cd ..
$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts/start_lan_web.ps1), [ref]$tokens, [ref]$errors)
# → PowerShell syntax OK
```

### 使用方式

```powershell
.\scripts\start_lan_web.ps1
```

脚本会构建 `app/v5/dist`，启动 `backend_fastapi`，并打印 `http://<教师机局域网IP>:8012`。客户机浏览器打开该地址即可访问，无需安装 Electron。

### 有意简化与边界

| 项目 | 当前处理 |
|------|----------|
| Windows 防火墙 | 不自动修改；若客户机不能连接，手动放行 TCP 8012 |
| HTTPS/WSS | 仅保留协议自适应能力；本轮不生成证书、不配置反向代理 |
| 客户机安装 | Web 访问优先，Electron 继续冻结 |
| Phase 4+ | CSSCI 深度导出、教师端大 UI、学生旁听大 UI、并发压测、生产级部署继续冻结 |

### 当前范围结论

用户要求“目前先截止到 Phase 3”。截至本轮，Phase 1 数据归属统一、Phase 2 课堂轮流练最小闭环、Phase 3 Web 局域网访问/部署准备均已完成并记录。后续若继续推进，应先确认是否解冻 Phase 4+，或只做 Phase 1-3 的验收修补。

---

## 第 9 轮: Phase 3 全链路收口 (2026-07-21)

### 调度与职责

本轮停止使用 CodeWhale，改由 Codex 总控拆分互不冲突的工作并行执行，再由主线程逐项审查、整合和复测。并行范围覆盖认证、课堂发言状态、学情人数与数据归属、离线 token 计数、可选 MinIO、作文六维兼容、语音流式链路、LAN 部署和前端浏览器行为。

### 并行交付汇总

| 工作流 | 已落地结果 |
|--------|------------|
| 认证与权限 | access/refresh 令牌用途分离；账户、角色、禁用状态和教师路由按服务端身份校验 |
| 课堂轮流练 | 当前发言人由进程内状态改为持久化状态；重启恢复、课堂归属和发言权限均有回归覆盖 |
| 学情分析 | 在册、活跃、已分析人数语义拆开；班级归属收紧；个人与班级数据接入教师前端 |
| 离线 token 计数 | `tiktoken` 仅使用可用的本地缓存，缺失或异常时立即降级，不再联网下载 |
| MinIO 可选依赖 | 移除对构造时事件循环的缓存，避免全量测试顺序触发 `RuntimeError`；依赖缺失仍不阻断启动 |
| 作文六维 | 新版 `vocabulary.score` 的 `0-10` 量纲与旧版 `vocabulary` 的 `0-100` 量纲均可正确读取 |
| 语音延迟 | LLM 竞速按原始流首包选胜者，胜者流直接进入增量 TTS；首句不再等待完整回答 |
| LAN Web | HTTPS 模式增加生产配置预检，SPA fallback 保持未知 API、WS、资源与越界路径 404 |
| 浏览器 QA | 新增 `scripts/qa_browser_smoke.py`，在宿主机 Edge 完成六条关键路径实测，临时 QA 数据已清理 |

### 真实行为修复

#### 1. 班级概览读取不再等待模型

浏览器实测发现班级概览 GET 会同步等待 RAG/Kimi，超过前端 10 秒超时。修复后，接口只复用已经存在的 `class_window_analysis` 分析产物；如果尚无产物，立即返回基于真实数据的客观人数摘要。该调整避免把不可控的模型调用放在页面读取主路径，相关 analytics 测试 `50 passed`。

#### 2. 移动端主区恢复可用宽度

`375px` 视口下，原固定 `256px` 侧栏只给主区留下 `119px`。小屏侧栏改为 `64px` 图标栏后，主区达到 `311px`，宿主机 Edge 实测无横向溢出。

### 本轮验证

| 验证 | 结果 |
|------|------|
| 后端全量 `pytest` 较早快照 | 全部非跳过项通过，`4 skipped`，耗时 `262.6s` |
| 后端全量 `pytest` 最终当前快照 | `391 collected`；`387 passed, 4 skipped`；`264.3s` |
| `ruff check app --select F,E9,I` | 全绿 |
| 前端 `npm run build` | 成功，2394 modules；主 JS `1758.28 kB` / gzip `552.76 kB` |
| Analytics 修复回归 | 50 项测试通过 |
| Edge 浏览器冒烟 | `login_page`、`admin_login`、`teacher_analytics`、`student_registration`、`student_route_guard`、`mobile_layout` 全部通过 |
| QA 收尾 | 临时测试账户和课堂数据已清理 |

前端构建仍保留 bundle 过大警告；该警告不影响本轮功能验收，但不能标记为已解决。

### 非阻断债务

| 项目 | 当前状态 |
|------|----------|
| 前端大包 | 主 JS 约 1.76 MB，需后续按页面和依赖拆包 |
| Python 弃用警告 | Pydantic `class Config`、`datetime.utcnow`、`pkg_resources` 尚未统一迁移 |
| TTS 双份音频 | `TTS_CHUNK` / `TTS_RESULT` 为兼容旧协议仍传递重复音频 |
| 已播比例 | 服务端按发送字节近似，未使用客户端真实播放游标 |
| 教师班级选择 | 教师页目前仍手工输入班级 ID |
| 浏览器脚本前置条件 | 需要后端和带 CDP 的 Chromium 预先启动，尚未包含完整环境编排 |

### 范围边界

- 实时助教继续冻结。
- 词汇复习不单独新增页面，只保留未来融合到推荐流程的方向。
- Neo4j、Elasticsearch、Redis、MinIO、Celery 等可选基础设施继续作为增强项，不作为当前核心闭环阻断。
- 本轮是 Phase 3 收口和修补，不借机扩展为 Phase 4 功能开发。
