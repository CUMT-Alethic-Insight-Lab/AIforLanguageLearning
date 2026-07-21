# HELIX P0 验收清单

> 适用于 9 月课堂版每次提交前的最小冒烟验收
> 生成日期: 2026-06-01
> 工作目录: `E:\projects\AiforForiegnLanguageLearning`

> **第 2 轮 P0 修复 (2026-06-01)**: WS JWT 身份验证、vocab/essays user_id 防伪造、前端 WS token 接入、
> 课堂数据模型骨架 (9 张表)、MinIO 可选依赖降级 — 全部通过验收。详见 [并行任务报告](#helix-p0-并行任务综合报告)。
>
> **第 5 轮 Phase 1 数据归属统一 (2026-06-03)**: `resolve_class_id_for_user` / `get_class_user_ids` 从旧 `StudentProfile.class_id` (str) 对齐到新 `ClassEnrollment` 表，
> 班级快照 `generate_class_daily_snapshot` 同步对齐。详见 [并行任务报告 第 5 轮](#第-5-轮-phase-1-数据归属统一-2026-06-03)。
>
> **第 6 轮 Phase 2 课堂轮流练最小闭环 (2026-06-03)**: 新增 current speaker API、课堂 WS 音频拒收事件、课堂 `SessionActivity` / `ActivityTurn` 最小落库。
> 集成回归 146 个相关测试通过；下一轮进入 Phase 3 Web 局域网访问/部署准备，Phase 4+ 继续冻结。
>
> **第 7 轮 Phase 3 Web 局域网访问/部署准备 (2026-06-03)**: 前端静态 Web/LAN 场景默认同源后端，保留 Vite/Electron 开发默认 `localhost:8012`；
> 新增 `scripts/start_lan_web.ps1`。当前要求的 Phase 1-3 已收口，Phase 4+ 继续冻结。

---

## 前置条件

### 环境要求

| 项目 | 要求 | 备注 |
|------|------|------|
| Python | >= 3.10 | 建议虚拟环境 `backend_fastapi/.venv/` |
| Node.js | >= 18 | 用于前端构建和开发 |
| 后端依赖 | `pip install -e ".[dev]"` | 见 `backend_fastapi/pyproject.toml` |
| 前端依赖 | `cd app/v5 && npm install` | 见 `app/v5/package.json` |
| 数据库 | SQLite (默认 `data/app.db`) | 可选: PostgreSQL / Redis / ES / Neo4j |
| LLM | LM Studio 或 Kimi API | 默认 `http://127.0.0.1:1234/v1` |
| ASR (可选) | SeamlessM4T (CPU) | 降级后返回提示文本 |

### 端口占用

| 服务 | 默认端口 | 环境变量 |
|------|---------|---------|
| FastAPI 后端 | 8012 | `AIFL_PORT` / `PORT` |
| Vite 前端开发 | 5173 | 硬编码于 `vite.config.ts` |
| Redis | 6379 | `AIFL_REDIS_URL` |
| Elasticsearch | 9200 | `AIFL_ES_URL` |
| Neo4j | 7687 | `AIFL_NEO4J_URL` |
| MinIO | 9000 | `AIFL_MINIO_ENDPOINT` |

### 快速启动

```powershell
# 后端
cd backend_fastapi
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8012

# 前端 (开发模式, 另一个终端)
cd app/v5
npm run dev

# 或一键启动
.\scripts\start.ps1
```

---

## 验收项

每条验收项包含:
- **命令/操作**: 执行的具体步骤
- **预期结果**: 明确的成功标准
- **失败时看**: 日志位置和常见排查方向
- **现有测试参考**: 项目中已有的 pytest 用例

---

### P0-01 后端启动

| 属性 | 内容 |
|------|------|
| **命令** | `cd backend_fastapi && uvicorn app.main:app --reload --host 127.0.0.1 --port 8012` |
| **预期** | 终端输出 `Uvicorn running on http://127.0.0.1:8012`，无 ImportError |
| **失败时看** | 终端 stderr；检查 `.venv` 是否激活；检查 `pyproject.toml` 依赖是否安装 |
| **关键依赖** | `fastapi`, `uvicorn[standard]`, `sqlmodel`, `pydantic-settings` |
| **绕开方案** | 如果 `kokoro-onnx` / `minio` 等可选依赖报错，检查 `main.py` 中是否有顶层 import → 需改为函数内延迟 import |
| **现有测试** | `backend_fastapi/tests/test_health.py` |

---

### P0-02 /health 健康检查

| 属性 | 内容 |
|------|------|
| **命令** | `curl http://127.0.0.1:8012/health` |
| **预期** | HTTP 200, 返回 `{"ok": true, "env": "development"}` |
| **失败时看** | 后端进程是否存活；端口是否正确 (`AIFL_PORT`), 防火墙是否放行 |
| **curl 等价** | `Invoke-RestMethod http://127.0.0.1:8012/health` (PowerShell) |
| **现有测试** | `test_health.py::test_health_ok` |

---

### P0-03 用户注册 & 登录

| 属性 | 内容 |
|------|------|
| **命令** | `POST /api/auth/register` → `POST /api/auth/login` |
| **注册请求** | `{"username": "test_student", "email": "test@example.com", "password": "Test1234"}` |
| **注册预期** | HTTP 200, `{"success": true, "data": {"accessToken": "...", "user": {"id": 1, "username": "test_student", "role": "student"}}}` |
| **登录请求** | `{"username": "test_student", "password": "Test1234"}` |
| **登录预期** | HTTP 200, `success: true`, 返回 `accessToken` 和 `user` |
| **失败时看** | 检查 `users` 表是否创建；JWT 密钥配置 (`AIFL_JWT_SECRET`)；密码强度规则 |
| **现有测试** | `test_auth_http.py::test_auth_login_admin_ok` |

---

### P0-04 查词 (词汇模块)

| 属性 | 内容 |
|------|------|
| **命令** | `POST /v1/vocab/lookup` |
| **请求** | `{"term": "hello", "source": "manual"}` (可附带 `Authorization: Bearer <token>`) |
| **预期** | HTTP 200, 返回 `term`, `definition`, `meaning`, `cefr_level`, `recommendations` |
| **失败时看** | LLM 服务是否就绪 (默认 `http://127.0.0.1:1234/v1`)；`PublicVocabEntry` 表是否有种子数据；ES 是否可连 (不必须) |
| **无 LLM 绕开** | LLM 不可用时依赖 `PublicVocabEntry` 本地词库 + 启发式 CEFR 分级 |
| **现有测试** | `test_vocab_http.py::test_vocab_lookup_http_uses_public_vocab` |

---

### P0-05 作文文本批改

| 属性 | 内容 |
|------|------|
| **命令** | `POST /v1/essays/grade` |
| **请求** | `{"text": "I has a pen. I like learn English.", "language": "en", "session_id": "test"}` |
| **预期** | HTTP 200, 返回 `submission_id`, `score` (0-100), `result.grade` (如 "B+"), `result.dimensions` (content/structure/language/grammar) |
| **失败时看** | LLM 是否可用 (`AIFL_LLM_BASE_URL`)；`run_grading_pipeline` 流水线是否抛异常 |
| **无 LLM 绕开** | 当前无降级方案，LLM 不可用时此验收项失败 |
| **现有测试** | `test_essay_http.py::test_essay_grade_and_get_via_http` |

---

### P0-06 WebSocket /ws/v1 连接

| 属性 | 内容 |
|------|------|
| **命令** | anonymous: `ws://127.0.0.1:8012/ws/v1?session_id=test&conversation_id=conv_test` |
|          | 认证: `ws://127.0.0.1:8012/ws/v1?session_id=test&conversation_id=conv_test&token=<jwt>` |
| **预期** | 连接成功, 立即收到服务端消息: `{"type": "TASK_STARTED", "seq": 1, ...}` |
|          | 有 token 时 `session_user_id` 从 JWT 解码；无 token 时为 None (anonymous) |
| **失败时看** | 后端日志；`main.py` 中 `@app.websocket("/ws/v1")` handler 是否有异常 |
| **浏览器操作** | F12 Console: `new WebSocket("ws://127.0.0.1:8012/ws/v1?session_id=test&conversation_id=conv&token=YOUR_JWT")` |
| **现有测试** | `test_ws_echo.py::test_ws_echo`, `test_auth_boundary.py::test_ws_uses_token_not_query_param_user_id` |
| **P0 修复** | ✅ 2026-06-01: WS 身份从 `?user_id=N` 改为 token-based (JWT decode → username → User.id) |

---

### P0-07 TEXT 模式对话

| 属性 | 内容 |
|------|------|
| **命令** | 在已连接的 WebSocket 上发送 TEXT 消息 |
| **请求** | `{"type": "TEXT", "request_id": "req1", "payload": {"text": "hello"}}` |
| **预期** | 依次收到: `TASK_STARTED` → `LLM_TOKEN` (可选) → `LLM_RESULT` → `TTS_RESULT` → `TASK_FINISHED` |
| **失败时看** | LLM 是否可用 (`stream_chat` 是否 yield) |
| **现有测试** | `test_ws_dialogue_experience.py` (integration, 需 `AIFL_RUN_INTEGRATION=1`) |

---

### P0-08 AUDIO_START / AUDIO_END 基本流程

| 属性 | 内容 |
|------|------|
| **命令** | 在已连接的 WebSocket 上发送 AUDIO 事件序列 |
| **请求序列** | ① `AUDIO_START` (payload: `{sample_rate:16000, channels:1, encoding:"pcm_s16le"}`) → ② `AUDIO_CHUNK` (payload: `{data_b64: <base64_audio>}`) → ③ `AUDIO_END` |
| **预期** | 依次收到: `TASK_STARTED` → `ASR_FINAL` → `LLM_RESULT` → `TTS_CHUNK` (一个或多个) → `TTS_RESULT` → `TASK_FINISHED` |
| **ASR 不可用时** | 预期收到 `ASR_FINAL` 空文本后跳过 LLM/TTS, 直接返回 `TASK_FINISHED` 和提示文本 |
| **失败时看** | ASR 后端 (`try_create_seamless_transcriber`) 是否初始化成功；`settings.enable_asr` 是否为 true |
| **现有测试** | `test_ws_voice_audio.py::test_ws_voice_audio_min_flow`, `test_ws_voice_audio_binary.py::test_ws_voice_audio_binary_chunk_min_flow` |

---

### P0-09 前端 npm run build

| 属性 | 内容 |
|------|------|
| **命令** | `cd app/v5 && npm run build` |
| **预期** | 编译成功, 输出到 `app/v5/dist/` 和 `app/v5/dist-electron/`；无 tsc/vite 报错 |
| **失败时看** | 检查 `vue-tsc -b` 的类型错误；检查 `vite build` 的语法错误 |
| **当前状态** | ✅ **已通过** (2026-06-01 验证) |
| **检查点** | `dist/index.html` 存在且可引用正确的 js/css 资源 (base path: `./`) |

---

### P0-10 Web 访问页面

| 属性 | 内容 |
|------|------|
| **命令** | 浏览器打开 `http://localhost:5173` (Vite 开发模式) |
| **预期** | 页面正常渲染, 无白屏/JS 报错；控制台无 404 (资源加载正常) |
| **失败时看** | Vite 终端输出；浏览器 F12 Network/Console；确保 `npm install` 已完成 |
| **生产构建检查** | 用 `npx serve dist` 或 `python -m http.server 8080` 验证 `dist/` 是否可访问 |

---

### P0-11 麦克风权限检查

| 属性 | 内容 |
|------|------|
| **命令** | 打开前端设置页 → 检查音频输入设备列表 |
| **预期** | 能列出可用的音频输入设备 (麦克风) 名称和 ID |
| **检查点** | `navigator.mediaDevices.enumerateDevices()` 返回 `audioinput` 类型设备 |
| **浏览器限制** | HTTPS 或 localhost 下才可用；LAN HTTP 下 `getUserMedia()` 不可用，需 mkcert/自签证书 |
| **失败时看** | 检查浏览器是否授予麦克风权限；查看 `SettingsView.vue` 的 `enumerateDevices` 调用 |

---

### P0-12 教师 / 学生权限检查

| 属性 | 内容 |
|------|------|
| **命令** | 注册两个用户 (student/teacher), 比较 API 访问差异 |
| **步骤** | ① 注册/登录 student 用户 → 获取 token → 访问受限 API → 预期 403 |
| | ② 注册/登录 teacher/admin 用户 → 获取 token → 访问受限 API → 预期 200 |
| **受限 API 示例** | `GET /api/admin/config` (需 Admin), `GET /api/analytics/teacher/dashboard` (需 Teacher) |
| **角色体系** | student(1) < teacher(2) < admin(3) 三级层级, 高级别覆盖低级别 |
| **现有测试** | `test_auth_http.py`（含 403 场景待补） |
| **新增基础设施** | ✅ 2026-06-01: Classroom/ClassEnrollment/Experiment 等 9 张表已落地 (`domain/classroom/models.py`) |
| **P1 遗留** | ~~teacher-classroom ownership 校验~~ → ✅ 第 4 轮已修复: analytics_router 所有 12 个端点均加入 classroom ownership 权限校验 |
| **失败时看** | `infrastructure/rbac.py` 中的 `has_role` 和 `require_role` 逻辑；`User.role` 字段默认值 `"student"` |

---

### P0-13 数据写入正确的 user_id

| 属性 | 内容 |
|------|------|
| **命令** | 以认证用户身份执行词汇/作文操作, 验证数据库记录 |
| **词汇检查** | `POST /v1/vocab/lookup` (带 `Authorization: Bearer <token>`) → 查 `UserVocabQuery` 表, `user_id` 应为 token 对应用户的 ID |
| | 未登录时不应接受请求体 `user_id` (已修复: `_resolve_user_id` 在未登录时返回 None) |
| **作文检查** | `POST /v1/essays/grade` (带 token) → 查 `EssaySubmission` 表, `user_id` 应为 token 对应用户的 ID |
| **WS 检查** | WebSocket 带 `?token=<jwt>` 参数 → 查 `ConversationEvent` 的 user_id 字段, 应为 JWT 解码出的用户 ID |
| | WebSocket **不带** token → `user_id` 字段应为 None (anonymous), 不接受 `?user_id=N` 查询参数 |
| **预期** | 所有学习记录表的 `user_id` 字段均来自服务端验证, 禁止客户端伪造 |
| **失败时看** | `routers/vocab.py` 中 `_resolve_user_id()` 逻辑；`main.py` 中 WS token 解析 (`decode_token` + `get_user_by_username`) |
| **现有测试** | `test_vocab_http.py::test_vocab_lookup_persists_user_linked_metadata`, `test_essay_http.py::test_essay_grade_persists_learning_record_when_user_present` |
| | `test_auth_boundary.py` (新增 6 个: 伪造 body/query user_id 防护 + token 验证) |
| **P0 修复** | ✅ 2026-06-01: vocab `_resolve_user_id` 不再接受请求体 user_id；essays grade/grade-ocr/submit 同；WS 改为 decode_token

---

## 快速冒烟脚本 (单次执行)

```powershell
# 1. 健康检查
$base = "http://127.0.0.1:8012"
$health = Invoke-RestMethod "$base/health"
Write-Host "Health: $($health.ok)" -ForegroundColor $(if($health.ok){'Green'}else{'Red'})

# 2. 注册+登录
$reg = Invoke-RestMethod "$base/api/auth/register" -Method POST -Body '{"username":"smoke_test","email":"smoke@test.com","password":"Smoke1234"}' -ContentType "application/json"
$login = Invoke-RestMethod "$base/api/auth/login" -Method POST -Body '{"username":"smoke_test","password":"Smoke1234"}' -ContentType "application/json"
$token = $login.data.accessToken
Write-Host "Login: $($login.success)" -ForegroundColor $(if($login.success){'Green'}else{'Red'})
Write-Host "Role: $($login.data.user.role)" -ForegroundColor Cyan

# 3. 查词
$vocab = Invoke-RestMethod "$base/v1/vocab/lookup" -Method POST -Body '{"term":"hello","source":"manual"}' -ContentType "application/json"
Write-Host "Vocab: $($vocab.term) CEFR=$($vocab.cefr_level)" -ForegroundColor Cyan

# 4. 作文批改
$essay = Invoke-RestMethod "$base/v1/essays/grade" -Method POST -Body '{"text":"I has a pen.","language":"en","session_id":"smoke"}' -ContentType "application/json"
Write-Host "Essay: score=$($essay.score) grade=$($essay.result.grade)" -ForegroundColor Cyan

# 5. 前端构建
cd app/v5
npm run build
if ($LASTEXITCODE -eq 0) { Write-Host "Build: OK" -ForegroundColor Green }
else { Write-Host "Build: FAILED" -ForegroundColor Red }
```

---

## 测试分类总表

| 编号 | 验收项 | 快速冒烟 | 完整验收 | 需要外部服务 | 可以 Mock |
|------|--------|----------|----------|-------------|----------|
| P0-01 | 后端启动 | ✅ | ✅ | ❌ | ✅ |
| P0-02 | /health | ✅ | ✅ | ❌ | ✅ |
| P0-03 | 注册登录 | ✅ | ✅ | ❌ | ✅ |
| P0-04 | 查词 | ✅ | ✅ | ⚠️ LLM (有降级) | ✅ |
| P0-05 | 作文批改 | ✅ | ✅ | ⚠️ LLM (无降级) | ✅ |
| P0-06 | WS 连接 | ✅ | ✅ | ❌ | ✅ |
| P0-07 | TEXT 对话 | ✅ | ✅ | ✅ LLM | ✅ |
| P0-08 | AUDIO 流程 | ✅ | ✅ | ✅ LLM+ASR | ✅ |
| P0-09 | 前端 build | ✅ | ✅ | ❌ | ✅ |
| P0-10 | Web 访问 | ✅ | ✅ | ❌ | ❌ |
| P0-11 | 麦克风权限 | ⏭️ 跳过 | ✅ | ❌ (浏览器 API) | ❌ |
| P0-12 | 权限检查 | ✅ | ✅ | ❌ | ✅ |
| P0-13 | user_id 正确性 | ✅ | ✅ | ❌ | ✅ |

> **快速冒烟**: 每个 commit 前执行的基础检查 (约 2 分钟)
> **完整验收**: 新部署 / release 前执行的全量检查 (约 10 分钟)
> **Mock 策略**: LLM / ASR / TTS 均可通过 `monkeypatch` 替换为桩函数 (参见现有测试)

---

## 现有 pytest 测试覆盖对照

| 验收项 | 对应测试文件 | 测试函数 |
|--------|-------------|---------|
| P0-02 /health | `test_health.py` | `test_health_ok` |
| P0-03 注册登录 | `test_auth_http.py` | `test_auth_login_admin_ok`, `test_auth_login_rejects_wrong_password` |
| P0-04 查词 | `test_vocab_http.py`, `test_ws_vocab_lookup.py` | 多个测试 |
| P0-05 作文批改 | `test_essay_http.py`, `test_ws_essay_grade.py` | 多个测试 |
| P0-06 WS 连接 | `test_ws_echo.py` | `test_ws_echo` |
| P0-07 TEXT 对话 | `test_ws_dialogue_experience.py` | `test_dialogue_experience_japanese_airport` (integration) |
| P0-08 AUDIO 流程 | `test_ws_voice_audio.py`, `test_ws_voice_audio_binary.py`, `test_ws_voice_tts_chunk.py`, `test_ws_voice_barge_in.py` | 多个测试 |
| P0-12 权限 | `test_auth_http.py` | 部分覆盖, 缺 403 场景 |
| P0-13 user_id | `test_vocab_http.py`, `test_essay_http.py` | `test_vocab_lookup_persists_user_linked_metadata`, `test_essay_grade_persists_learning_record_when_user_present` |

---

## 附录：关键配置项速查

| 配置名 | 环境变量 | 默认值 |
|--------|----------|--------|
| 端口 | `AIFL_PORT` / `PORT` | `8012` |
| 数据库 | `AIFL_DATABASE_URL` / `DATABASE_URL` | `sqlite:///./data/app.db` |
| LLM 地址 | `AIFL_LLM_BASE_URL` / `LLM_BASE_URL` | `http://127.0.0.1:1234/v1` |
| LLM 模型 | `AIFL_LLM_MODEL` / `LLM_MODEL` | `qwen/qwen3.5-9b` |
| Kimi API Key | `AIFL_KIMI_API_KEY` / `KIMI_API_KEY` | `""` |
| JWT Secret | `AIFL_JWT_SECRET` / `JWT_SECRET` | `your-super-secret-key-change-this-in-production` |
| ASR 开关 | `AIFL_ENABLE_ASR` / `ENABLE_ASR` | `true` |
| ASR 后端 | `AIFL_ASR_BACKEND` / `ASR_BACKEND` | `seamless` |
| TTS 后端 | `AIFL_TTS_BACKEND` / `TTS_BACKEND` | `kokoro` |

### 日志位置

| 组件 | 日志路径 | 说明 |
|------|---------|------|
| 后端 | `backend_fastapi/logs/` | structlog 输出 |
| 后端 stdout | 终端窗口 | uvicorn 访问日志 |
| 前端 Vite | 终端窗口 | HMR / 编译错误 |
| 数据库 | `backend_fastapi/data/app.db` | SQLite 文件 |
| 运行时配置 | `backend_fastapi/data/runtime_config.json` | 热更新持久化 |

---

## 总控复验命令 (Codex 一键验收)

```powershell
# === 第 1 组: 后端基础测试 + P0 安全边界测试 ===
cd E:\projects\AiforForiegnLanguageLearning\backend_fastapi
.\.venv\Scripts\python.exe -m pytest tests\test_health.py tests\test_settings_default_port.py tests\test_srs_sm2.py tests\test_auth_boundary.py tests\test_classroom_models.py tests\test_minio_optional.py -q --tb=short

# 预期: 32+ passed, exit code 0
# test_health.py: 1 passed
# test_settings_default_port.py: 1 passed
# test_srs_sm2.py: 3 passed
# test_auth_boundary.py: 6 passed (P0 身份边界)
# test_classroom_models.py: 10 passed (课堂数据模型)
# test_minio_optional.py: 11 passed (MinIO 降级)

# === 第 2 组: 前端构建 ===
cd E:\projects\AiforForiegnLanguageLearning\app\v5
npm run build

# 预期: vue-tsc -b && vite build 通过, exit code 0
# 输出 dist/ 和 dist-electron/

# === 第 3 组: 主模块导入 (MinIO 可选) ===
cd E:\projects\AiforForiegnLanguageLearning\backend_fastapi
.\.venv\Scripts\python.exe -c "from app.main import app; print('OK: app imported successfully')"

# 预期: 打印 "OK: app imported successfully", exit code 0
# 即使在未安装 minio 的环境中也能通过

# === 第 4 组: WS token 验证 (需要后端运行) ===
# 启动后端: uvicorn app.main:app --reload --host 127.0.0.1 --port 8012
# 获取 token:
$login = Invoke-RestMethod http://127.0.0.1:8012/api/auth/login -Method POST -Body '{"username":"admin","password":"Admin1234"}' -ContentType "application/json"
$token = $login.data.accessToken

# 测试 WS 认证连接 (用 python websockets 库或手动)
# ws://127.0.0.1:8012/ws/v1?session_id=test&conversation_id=conv&token=$token
```

### 快速冒烟 (约 30 秒)

```powershell
cd E:\projects\AiforForiegnLanguageLearning
cd backend_fastapi; .\.venv\Scripts\python.exe -m pytest tests\test_health.py tests\test_auth_boundary.py -q --tb=line ; cd ..
cd app\v5; npm run build 2>&1 | Select-String "built in" ; cd ..
```
预期输出: `32 passed` (或更多) + `✓ built in X.XXs`

---

## 本轮修改汇总 (2026-06-01 第 2 轮)

| 改动 | 文件 | 说明 |
|------|------|------|
| `/ws/v1` token auth | `main.py` | 支持 `?token=<jwt>` + `Sec-WebSocket-Protocol` header |
| vocab user_id 修复 | `routers/vocab.py` | `_resolve_user_id` 未登录时不再接受请求体 user_id |
| essays user_id 修复 | `routers/essays.py` | `grade/grade-ocr/submit` 三处不再回退到 `req.user_id` |
| 前端 WS token | `voice-socket.ts`, `voice.ts` | `buildWsV1Url` 改用 `&token=` 参数 |
| 课堂模型 | `domain/classroom/` | 9 张 SQLModel 表: Classroom, Experiment, Session 等 |
| MinIO 降级 | `minio_storage.py` | top-level import → lazy import + `is_minio_available()` |
| 安全测试 | `test_auth_boundary.py` | 6 个新测试覆盖 P0 身份边界 |
| 模型测试 | `test_classroom_models.py` | 10 个新测试覆盖 FK 约束和 create_all |
| MinIO 测试 | `test_minio_optional.py` | 11 个新测试覆盖降级路径 |

---

## 第 3 轮执行结果 (2026-06-01)

### 验证命令

```powershell
# 总体验证（72 passed, 0 failed）
cd backend_fastapi
.\.venv\Scripts\python.exe -m pytest tests\test_essay_http.py tests\test_essay_access_control.py tests\test_auth_boundary.py tests\test_classroom_models.py tests\test_classroom_access.py tests\test_classroom_api.py tests\test_research_export.py tests\test_static_frontend.py -q
# → Codex 总控复验：72 passed

cd app\v5; npm run build
# → ✓ built in 6.71s
```

### 修改文件清单

| Agent | 文件 | 说明 |
|-------|------|------|
| A | `routers/essays.py:340-355` | GET 添加 access control（匿名→仅匿名提交，学生→仅自己，teacher/admin→全部） |
| A | `tests/test_essay_access_control.py` | 7 个测试覆盖所有访问场景 |
| _ | `tests/test_essay_http.py:234-241` | 修复 `test_essay_submit_text_and_get_status` 匿名 GET 需 token |
| B | `application/classroom_access.py` | 4 个 helper：`is_teacher_of_classroom`、`is_student_in_classroom`、`can_teacher_access_student`、`resolve_student_classroom_ids` |
| B | `tests/test_classroom_access.py` | 18 个测试覆盖正常/边界/不存在场景 |
| C | `interfaces/classroom_router.py` | 6 个端点：classrooms CRUD、enrollments、sessions、activities、turns |
| C | `tests/test_classroom_api.py` | 14 个测试覆盖 teacher/admin/student 角色，含跨教师写入拒绝 |
| D | `interfaces/research_export_router.py` | CSV/JSON 导出端点（turns 数据，含 anonymized id、assessment join） |
| D | `tests/test_research_export.py` | 7 个测试覆盖权限和导出格式 |
| E | `static_frontend.py` | `mount_static_frontend(app)` → dist 存在时挂载 /assets + SPA fallback |
| E | `tests/test_static_frontend.py` | 6 个测试覆盖 mount 成功/跳过/静态文件/fallback |
| F | `main.py:27,33,113-118` | 注册 classroom_router、research_export_router、调用 mount_static_frontend |

### 无同文件冲突

所有 Agent 操作互不重叠的文件，集成阶段按序注册路由无冲突。

---

## 第 4 轮执行结果 (2026-06-01)

### 目标

收紧 analytics 教师端接口的 teacher-classroom ownership 权限，复用 `application/classroom_access.py` 的权限 helper。

### 验证命令

```powershell
cd backend_fastapi

# 代码检查
.\.venv\Scripts\python.exe -m ruff check app\interfaces\analytics_router.py tests\test_analytics_access_control.py
# → All checks passed!

# 测试 (61 passed, 0 failed)
.\.venv\Scripts\python.exe -m pytest tests\test_analytics_access_control.py tests\test_analytics_module.py -q
# → 61 passed (33 access control + 28 analytics module)

# Codex 总控整合回归（第 1-4 轮关键测试）
.\.venv\Scripts\python.exe -m pytest tests\test_essay_http.py tests\test_essay_access_control.py tests\test_auth_boundary.py tests\test_classroom_models.py tests\test_classroom_access.py tests\test_classroom_api.py tests\test_research_export.py tests\test_static_frontend.py tests\test_analytics_access_control.py tests\test_analytics_module.py -q
# → 133 passed

cd ..\app\v5; npm run build
# → ✓ built in 6.15s
```

### 修改文件清单

| 文件 | 说明 |
|------|------|
| `app/interfaces/analytics_router.py` | 新增 4 个 access control helper：`_is_admin`、`_parse_classroom_id`、`_ensure_teacher_can_access_classroom`、`_ensure_teacher_can_access_student`；为全部 12 个端点添加权限检查 |
| `tests/test_analytics_access_control.py` (新增) | 33 个测试覆盖：teacher 访问自己/他人课堂学生、admin 全通、legacy class_id 保守拒绝、class-assignments 必传 class_id、intervention 跨课堂阻止、零课堂教师拒绝 |

### 保护的端点

| 端点 | 权限规则 |
|------|---------|
| `GET /class/{class_id}/dashboard` | teacher 必须 own 该 classroom；非数字 class_id → teacher 403, admin 允许 |
| `GET /class/{class_id}/overview` | 同上 |
| `GET /class/{class_id}/students` | 同上 |
| `GET /class/{class_id}/weekly` | 同上 |
| `GET /student/{student_id}/dashboard` | teacher 必须与该学生有共同课堂（跨所有课堂扫描） |
| `GET /student/{student_id}/profile` | 同上 |
| `GET /student/{student_id}/report` | 同上 |
| `POST /student/{student_id}/llm-profile` | 同上 |
| `POST /student/{student_id}/class-assignment` | teacher 必须可访问学生 + own 目标 class_id |
| `POST /intervention` | teacher 必须可访问学生（+ 若传 class_id 须 own 该课堂） |
| `GET /intervention/{task_id}` | teacher 必须可访问该 intervention 关联的学生 |
| `GET /class-assignments` | teacher 必须传 class_id 且 own 该课堂；admin 可不传 |

### 第 5 轮: Phase 1 数据归属统一 (2026-06-03)

- ✅ `resolve_class_id_for_user` 已优先从 `ClassEnrollment` 查询学生所属课堂，fallback 到旧 `StudentProfile.class_id`
- ✅ `get_class_user_ids` 已改造：数字 class_id 优先走 ClassEnrollment，非数字走旧 StudentProfile.class_id (legacy 兼容)
- ✅ `generate_class_daily_snapshot` 已使用改造后的 `get_class_user_ids`
- ✅ 新增 `test_analytics_classroom_alignment.py` 覆盖 4 个场景
- ✅ `test_analytics_module.py` 全部通过

### 仍未覆盖的 analytics 风险

- `StudentProfile.class_id` (str) 与新 `ClassEnrollment.classroom_id` (int) 的字符转数字映射在旧 class_id（如 `"class_101"`）场景下不兼容 —— 当前策略：数字优先走 ClassEnrollment，非数字保留旧行为
- 旧 `class_id: str` 参数（如 `"class_101"`）在 teacher 端一律返回 403，保守安全
- `facade.py` 中 `build_student_profile_payload` 的 `class_id` 读取链 (`profile.class_id` + `latest.class_id`) 已由 `resolve_class_id_for_user` 覆盖

---

## 第 6 轮: Phase 2 课堂轮流练最小闭环 (2026-06-03)

### 执行概要

本轮把课堂轮流练从“有数据模型/API 骨架”推进到最低可用控制线：老师指定当前发言学生，非当前学生音频在 `/ws/v1` 入口被拒收，课堂回合写入 `SessionActivity` / `ActivityTurn`。

### 新增 API / 事件

| 类型 | 名称 | 说明 |
|------|------|------|
| REST | `POST /api/v1/classroom-sessions/{session_id}/current-speaker` | 老师/admin 设置当前发言学生；校验学生已入班 |
| REST | `GET /api/v1/classroom-sessions/{session_id}/current-speaker` | 老师/admin/本班学生查看当前发言人 |
| REST | `DELETE /api/v1/classroom-sessions/{session_id}/current-speaker` | 老师/admin 清除当前发言人 |
| WS | `CLASSROOM_AUDIO_REJECTED` | 非当前发言人、匿名、未入班、无当前发言人等场景的明确拒收事件 |

### 验证命令

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

### 有意简化

- 当前发言人保存在单进程内存 dict，适合 9 月单后端课堂试点；重启或多 worker 不共享，Phase 3/部署时如需要再切 Redis。
- `ActivityTurn.turn_type='ai'` 的 `user_id` 暂记为当前学生 id，用 `turn_type` 区分 AI 回复，避免引入系统用户。
- 本轮不做前端大 UI、不做 CSSCI 深度导出、不做并发压测。

### 下一轮建议

Phase 3 Web 局域网访问/部署准备：确认前端从客户机可零安装访问后端静态托管页面，补 LAN 启动脚本、配置展示、HTTPS/WSS 预案。Phase 4+ 继续冻结。

---

## 第 7 轮: Phase 3 Web 局域网访问/部署准备 (2026-06-03)

### 执行概要

本轮解决客户机浏览器零安装访问的主干问题：前端由 FastAPI 静态托管时，HTTP API 和 WS 默认走当前页面同源；Vite/Electron 开发场景仍默认连接 `localhost:8012`。

### 改动内容

| 文件 | 说明 |
|------|------|
| `app/v5/src/services/backend-url.ts` | 新增后端 URL/WS host 统一推导：静态 Web 同源，开发环境 `localhost:8012` |
| `app/v5/src/services/api.ts` | HTTP API 默认值改为动态推导 |
| `app/v5/src/services/config.ts` | app_config 默认值和 normalize 复用统一推导 |
| `app/v5/src/services/voice-socket.ts` | WS URL 根据后端/页面协议自动选择 `ws` / `wss` |
| `app/v5/src/stores/voice.ts` | 移除把同源 host 强制改回 localhost 的旧逻辑 |
| `app/v5/src/views/SettingsView.vue` | 设置页后端默认值同步动态推导 |
| `scripts/start_lan_web.ps1` | 构建前端并用 FastAPI 在 `0.0.0.0:8012` 托管，打印客户机访问地址 |

### 验证命令

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

脚本会构建 `app/v5/dist`，启动 `backend_fastapi`，并打印 `http://<教师机局域网IP>:8012`。客户机浏览器打开该地址即可访问。

### 有意简化

- 本轮不自动修改 Windows 防火墙；若客户机不能连接，手动放行 TCP 8012。
- 本轮不生成 HTTPS 证书；HTTPS/WSS 只保留协议自适应能力，后续按实验室网络环境决定是否上 mkcert 或反向代理。
- Phase 4+（CSSCI 深度导出、教师端大 UI、并发压测、生产级部署）继续冻结。

---

## 第 8 轮: Phase 3 局域网 Web 部署可靠性收口 (2026-07-21)

> 本节取代上一节中“默认 HTTP”和“HTTPS 仅作预案”的启动说明。前端功能代码未改动。

### 当前部署边界

| 项目 | 当前行为 |
|------|----------|
| 客户机安装 | 客户机只需浏览器，不安装 Electron、Node.js 或 Python |
| 默认模式 | HTTPS；证书或私钥未提供、文件无效或二者不匹配时退出，不回落 HTTP |
| 生产认证 | HTTPS 模式强制 `AIFL_APP_ENV=production`；默认 JWT 密钥或默认管理员密码会在构建前退出 |
| 开发模式 | 仅通过 `-Mode HttpDevelopment` 显式开启；LAN 客户机麦克风会被浏览器拦截 |
| 前端构建 | 默认执行 `npm run build`；`-SkipBuild` 也会检查 `dist/index.html`、`dist/assets` 和 JS bundle |
| 网络监听 | 默认 `0.0.0.0:8012`；启动前和构建后各检查一次端口占用 |
| 日志安全 | Uvicorn 使用 warning 级别并关闭 access log，避免 WS 查询串中的 token 出现在终端 |
| 静态托管 | 前端路由回退 `index.html`；未知 API、WS 路径、缺失 `.js/.css` 和越界路径保持 404 |
| 失败退出码 | 配置/TLS=`2`，依赖/dist=`3`，端口占用=`4`，前端构建=`10`，后端启动失败沿用 Uvicorn 退出码 |

### 可复制验证命令

以下命令均从仓库根目录执行。

```powershell
# 1. PowerShell 7 语法检查
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path .\scripts\start_lan_web.ps1),
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) { $errors | Format-List; exit 1 }

# 2. 开发 HTTP：完整构建 + 配置校验，但不启动服务
pwsh -NoProfile -File .\scripts\start_lan_web.ps1 `
    -Mode HttpDevelopment `
    -HostAddress 127.0.0.1 `
    -BackendPort 18012 `
    -ValidateOnly

# Windows PowerShell 5.1 若受执行策略限制，使用同等的显式一次性绕过
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_lan_web.ps1 `
    -Mode HttpDevelopment `
    -HostAddress 127.0.0.1 `
    -BackendPort 18012 `
    -SkipBuild `
    -ValidateOnly

# 3. Python 静态托管边界测试与代码检查
cd .\backend_fastapi
.\.venv\Scripts\python.exe -m pytest tests\test_static_frontend.py -q
.\.venv\Scripts\python.exe -m ruff check app\static_frontend.py tests\test_static_frontend.py
cd ..

# 4. 查看部署端口是否已被占用
Get-NetTCPConnection -State Listen -LocalPort 8012 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

### HTTPS 课堂启动

证书必须覆盖客户机实际访问的主机名或教师机 LAN IP，并且证书签发方必须已受每台客户机信任。
启动前还必须通过环境变量或 `backend_fastapi/.env` 配置非默认
`AIFL_JWT_SECRET`；若保留管理员自动注入，还必须配置非默认
`AIFL_SEED_ADMIN_PASSWORD`。关闭自动注入时可设置 `AIFL_SEED_ADMIN_ENABLED=false`。
脚本只验证配置是否安全，不打印这些值。

```powershell
# 仅校验证书、dist、端口和运行环境，不启动
pwsh -NoProfile -File .\scripts\start_lan_web.ps1 `
    -CertificatePath C:\helix-certs\helix-lan.pem `
    -PrivateKeyPath C:\helix-certs\helix-lan-key.pem `
    -ValidateOnly

# 正式启动：构建前端并监听所有网卡
pwsh -NoProfile -File .\scripts\start_lan_web.ps1 `
    -CertificatePath C:\helix-certs\helix-lan.pem `
    -PrivateKeyPath C:\helix-certs\helix-lan-key.pem

# 已由发布流程构建过 dist 时可跳过重新构建，但完整性检查仍会执行
pwsh -NoProfile -File .\scripts\start_lan_web.ps1 `
    -CertificatePath C:\helix-certs\helix-lan.pem `
    -PrivateKeyPath C:\helix-certs\helix-lan-key.pem `
    -SkipBuild
```

也可以预先设置 `AIFL_HTTPS_CERTFILE`、`AIFL_HTTPS_KEYFILE` 后直接运行脚本。脚本不会输出这两个环境变量的值。不要把 JWT、Kimi API key 或其他 token 作为脚本参数。

### 显式 HTTP 开发启动

```powershell
# 仅供 localhost 或无需麦克风的开发检查；不会自动切换到 HTTPS
pwsh -NoProfile -File .\scripts\start_lan_web.ps1 `
    -Mode HttpDevelopment `
    -HostAddress 127.0.0.1
```

### 本轮实测结果

| 验证 | 结果 |
|------|------|
| PowerShell 7 parser | 通过，无语法错误 |
| Windows PowerShell 5.1 `-ValidateOnly` | 通过；本机需显式 `-ExecutionPolicy Bypass` |
| HTTP 完整构建 + `-ValidateOnly` | 通过；Vite 2394 modules，dist 完整性检查通过 |
| HTTPS 匹配证书/私钥 + `-ValidateOnly` | 通过；临时测试证书已清理 |
| 默认 HTTPS 但缺少证书参数 | 按预期退出 `2`，未回落 HTTP |
| 端口已占用 | 按预期退出 `4`，未执行构建或启动 |
| `pytest test_static_frontend.py test_health.py` | 19 passed |
| ruff | All checks passed |
| 真实服务冒烟 | `/health=200`、`/=200`、未知 `/api=404`，关闭后测试端口已释放 |

前端构建仍有一个非阻断警告：主 JS bundle 约 1.75 MB（gzip 约 550 KB），后续可做按页面拆包；不影响本轮 LAN 启动可靠性验收。

### 必须人工验证

- 在一台真实客户机用脚本打印的 `https://<教师机地址>:8012` 打开页面，确认无证书警告；忽略证书警告不算通过。
- 在客户机浏览器控制台确认 `window.isSecureContext === true`，并实际授权麦克风、完成一次录音和 WSS 对话。
- 用学生和教师账号分别登录，确认同源 API、静态资源与页面刷新均正常；Network 面板不得出现把 API 404 返回为 `text/html` 的情况。
- 在 30-60 台客户机环境前，统一下发受信任根证书或使用学校已有证书体系。自签证书若逐台手工信任，不满足课堂“零操作”目标。
- 手动放行 Windows 防火墙入站 TCP 8012，并从不同网段/VLAN 的客户机验证连通性；脚本不会改防火墙。
- 启动后执行 `Invoke-RestMethod https://<教师机地址>:8012/health`，应返回 `ok=true`。不得用 `-SkipCertificateCheck` 作为正式验收结果。

---

## 第 9 轮: Phase 3 全链路收口与浏览器实测 (2026-07-21)

### 收口结论

本轮继续在 Phase 3 边界内补齐真实闭环，重点处理离线运行、账户与课堂数据归属、语音首包延迟、LAN 安全启动和前端真实行为。较早代码快照的后端全量 `pytest` 已全绿，结果为 `4 skipped`、耗时 `262.6s`；最终当前快照再次全绿，共收集 `391` 项，结果为 `387 passed, 4 skipped`，耗时 `264.3s`。

### 已完成修复

| 主干 | 本轮结果 |
|------|----------|
| 离线运行 | `tiktoken` 本地词表不可用时直接使用近似计数，不再尝试公网下载 |
| 可选存储 | MinIO 调用改为当前事件循环内执行，修复无当前事件循环时的构造失败；MinIO 仍不阻断核心启动 |
| 作文六维 | `vocabulary.score` 按新六维 `0-10` 读取，同时兼容旧版数值 `0-100`；缺失或无效分数回退文本估算 |
| 认证边界 | access/refresh 令牌用途分离，校验账户、角色和禁用状态；前端同步清理旧会话并保护教师路由 |
| 课堂轮流练 | 当前发言人状态持久化，后端重启后仍可恢复；发言入口继续校验课堂归属和当前发言人 |
| 学情分析 | 区分在册、活跃、已分析人数，收紧教师与课堂归属，个人和班级前端接入真实接口 |
| 语音链路 | LLM 原始流直接驱动增量 TTS，首个完整句可在模型继续生成时开始合成和发送 |
| LAN Web | HTTPS 启动前检查生产密钥、管理员口令、证书和 dist；SPA 回退不再吞掉未知 API、WS、静态资源及越界路径的 404 |

### 验证证据

| 验证项 | 已确认结果 |
|--------|------------|
| 后端全量 `pytest`（较早快照） | 全部非跳过项通过，`4 skipped`，`262.6s` |
| 最终当前快照全量 `pytest` | `391 collected`；`387 passed, 4 skipped`；`264.3s` |
| `ruff check app --select F,E9,I` | All checks passed |
| `npm run build` | 成功；2394 modules；主 JS `1758.28 kB`，gzip `552.76 kB` |
| Analytics 回归 | 班级概览修复后 50 项相关测试通过 |
| 宿主机 Edge 浏览器冒烟 | `login_page`、`admin_login`、`teacher_analytics`、`student_registration`、`student_route_guard`、`mobile_layout` 全部通过 |
| QA 数据清理 | 浏览器实测创建的临时账户和课堂数据已清理 |

浏览器冒烟入口为 `scripts/qa_browser_smoke.py`。该脚本用于可重复验收，不替代后端单元与集成测试。

### 浏览器实测发现与修复

1. 班级概览 GET 原先同步等待 RAG/Kimi，导致前端 10 秒超时。现在只复用已有 `class_window_analysis` 产物；没有产物时立即返回客观人数摘要，不在读取接口中临时调用模型。
2. 移动端固定 `256px` 侧栏会把 `375px` 视口的主区压到 `119px`。现在小屏使用 `64px` 图标栏，主区为 `311px`，实测无横向溢出。

### 剩余非阻断债务

- 前端主包仍偏大，Vite 保留 bundle 过大警告；后续需要按页面和重型依赖拆包。
- 仍有 Pydantic `class Config`、`datetime.utcnow`、`pkg_resources` 弃用警告。
- `TTS_CHUNK` 与 `TTS_RESULT` 暂时发送双份音频数据，属于兼容旧前端的协议债务。
- 服务端“已播比例”仍按已发送音频字节近似，不等于客户端真实播放进度。
- 教师学情页仍需手工输入班级 ID，尚未接课堂选择器。
- `scripts/qa_browser_smoke.py` 运行前需要后端服务和带 CDP 的 Chromium 已启动；当前不是单命令端到端环境编排器。

### Phase 3 边界保持

- 实时助教继续冻结，不作为本轮闭环条件。
- 词汇复习不新增独立页面，后续只融合到推荐流程。
- Neo4j、Elasticsearch、Redis、MinIO、Celery 等可选基础设施不作为词汇、作文、语音、认证、课堂和学情核心闭环的阻断项。
