# Phase 4 核心功能交接文档 — 教师端学情分析模块（Teacher Analytics）

**交接日期**: 2026年4月18日  
**负责成员**: 成员 D（教师端/学情分析）  
**前置条件**: Phase 3 基础设施加固已完成，PostgreSQL + Redis + MinIO 本地服务已启动

---

## 1. 工作范围

负责实现教师端学情分析的核心能力，采用 **4-Agent 协作架构**：

| Agent | 职责 | 关注学生群体 |
|-------|------|-------------|
| **Agent-0 历史总结** | 每天凌晨为每个学生生成纵向历史信息摘要 | 全部学生 |
| **Agent-1 底层托底** | 关注学习困难学生，识别基础缺口，设计最小有效干预 | 底层（后20%） |
| **Agent-2 中层突破** | 关注中下层到中上层学生，识别进步趋势和集中错误 | 中下层→中上层（中间60%） |
| **Agent-3 顶层突破** | 关注高水平学生，识别瓶颈，设计高阶能力培养方案 | 顶层（前20%） |

**核心交付**：
1. **个人历史纵向分析** — 20+ 评价维度，覆盖词汇、作文、口语、综合学习倾向
2. **班级近期横向分析** — 10+ 维度，按生态位分层评价（底层/中层/顶层）
3. **底层托底策略** — 5+ 维度，基础能力缺口识别与干预
4. **顶层突破策略** — 5+ 维度，瓶颈识别与高阶能力培养
5. **教师端 API** — 班级总览、学生画像、风险预警、干预建议

---

## 2. 当前基座状态（已就绪，可直接使用）

### 2.1 数据模型

**文件**: `backend_fastapi/app/models.py`

| 模型 | 用途 | 关键字段 |
|------|------|----------|
| `VocabularyItem` | 个人词汇学习记录 | `word`, `mastery_level`, `next_review_at`, `user_id` |
| `EssaySubmission` | 作文提交记录 | `ocr_text`, `language`, `session_id`, `conversation_id` |
| `EssayResult` | 作文批改结果 | `score`, `result` (JSON: dimensions, feedback, suggestions) |
| `ConversationEvent` | 对话事件记录 | `seq`, `type`, `payload` (JSON), `conversation_id` |
| `UserVocabQuery` | 查词历史 | `term`, `source`, `result`, `session_id` |
| `StudentProfile` | 学生基础画像 | `level`, `goals`, `interests`, `user_id` |
| `LearningRecord` | 通用学习记录 | `type`, `content`, `meta_data` (JSON) |

**文件**: `backend_fastapi/app/domain/models.py`

| 模型 | 用途 |
|------|------|
| `User` | 用户基础信息（`username`, `email`, `role`, `created_at`） |
| `StudentProfile` | 学生档案（`level`, `goals` JSON, `interests` JSON） |
| `LearningPath` | 学习路径（`title`, `milestones` JSON, `progress`, `status`） |

### 2.2 基础设施封装

- **PostgreSQL 18** — 本地已启动（端口 5432），所有业务数据存储
- **Redis 8.6** — 本地已启动（端口 6379），用于缓存和 Celery broker
- **Celery** — 已配置 Redis broker，支持异步任务（`grade_essay_task`, `generate_daily_vocab_task`）
- **LLM 服务** — `llm.py` 已封装 Kimi API 调用
- **SM-2 算法** — `domain/srs/sm2.py` 已迁移，可直接计算复习间隔

### 2.3 现有路由

- `backend_fastapi/app/interfaces/admin_router.py` — 基础 admin API（用户列表、角色管理）
- `backend_fastapi/app/routers/learning.py` — 学习相关路由，可扩展

---

## 3. 评价维度清单（基于实际可收集数据）

### 3.1 A. 个人历史纵向维度（20个）

#### A1. 词汇学习维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 1 | **词汇熟练度增长率** | `VocabularyItem` | 当前 `mastery_level` 均值 / 初始均值 | 越高越好 |
| 2 | **SM-2 复习遗忘抑制比** | `VocabularyItem` | 实际复习成功次数 / 应复习次数 (`next_review_at` 到期) | 越高越好 |
| 3 | **主动查词转化率** | `UserVocabQuery` + `VocabularyItem` | 搜索后进入词库且 `mastery_level > 3` 的词数 / 总搜索词数 | 越高越好 |
| 4 | **构词法迁移能力** | Neo4j KG + `EssayResult` | 作文中使用未学过但含已学词根的新词比例 | 越高越好 |
| 5 | **长时记忆健壮度** | `VocabularyItem` | 进入"一年以上复习周期"的单词绝对数量 | 越高越好 |

#### A2. 作文能力维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 6 | **语法错误收敛速度** | `EssayResult.result.dimensions.grammar` | 连续5篇作文中 grammar 核心扣分项的下降斜率 | 越高越好 |
| 7 | **高级词汇替代率** | `EssayResult.result.suggestions` | 采纳 LLM 建议替换为高级词汇的次数 / 总建议次数 | 越高越好 |
| 8 | **句式多样性指数 (MSL)** | `EssayResult.corrected_text` | 平均句长及复合句（从句）在全篇中的占比 | 适中最好 |
| 9 | **逻辑衔接连贯度** | `EssayResult.result.dimensions.structure` | LLM 对连接词使用及段落推导的评分趋势 | 越高越好 |
| 10 | **语义表达准确性** | `EssayResult.result.dimensions.language` | 词不达意、中式英语错误在纵向时间轴上的占比变化 | 越低越好 |

#### A3. 口语对话维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 11 | **对话响应潜伏期** | `ConversationEvent` (ASR Start → LLM End) | WebSocket 记录的用户平均停顿/思考时长 | 越低越好 |
| 12 | **语音产出速率 (WPM)** | `ConversationEvent` (ASR Text / Time) | 每分钟有效单词产出数 | 越高越好 |
| 13 | **对话难度跳变成功率** | `ConversationEvent` + 场景设定 | 从 `beginner` 提升至 `intermediate` 后的首轮得分表现 | 越高越好 |
| 14 | **跨文化得体性偏离值** | `ConversationEvent.payload` (LLM 文化评估) | 对话中违反文化习俗的频次 | 越低越好 |
| 15 | **口语解释/转述能力** | `ConversationEvent` | 遇到生词时，使用简单已知词汇进行 Paraphrase 的次数 | 越高越好 |

#### A4. 综合学习倾向维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 16 | **学习行为稳定性** | Redis / `LearningRecord` | 每日活跃时长与复习任务完成的时间标准差 | 越低越稳 |
| 17 | **错误复发率 (Regression)** | `EssayResult` + `VocabularyItem` | 已掌握（`mastery > 4`）的知识点在后续测试中再次出错的概率 | 越低越好 |
| 18 | **反馈响应深度** | `EssayResult.result.suggestions` | 用户根据修改建议在下一篇作文中主动避坑的重合度 | 越高越好 |
| 19 | **主题覆盖广度** | Celery 异步生成的词库标签 | 个人词库涵盖的 LLM 主题标签数量 | 越高越好 |
| 20 | **自主学习驱动力** | `UserVocabQuery` + 词库生成模块 | 非老师布置任务，用户主动生成主题词汇并学习的次数 | 越高越好 |

### 3.2 B. 班级中下到中上层趋势维度（10个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 1 | **中下层进步斜率 (Lift)** | 班级聚合数据 | 中下层（前40%-70%）学生总分的月度增长百分比 | 越高越好 |
| 2 | **群体性错误共性指数** | `EssayResult.result.feedback` (LLM 聚类) | 班级内超过30%学生共同犯下的 Top 5 语法/词汇错误 | 预警标记 |
| 3 | **中层学生难度耐受力** | `ConversationEvent` (Dynamic Difficulty) | 中层学生在 `intermediate` 难度下的平均对话轮数上限 | 越高越好 |
| 4 | **学习路径收敛度** | `VocabularyItem` 更新路径 | 中游学生学习曲线是否向"优生曲线"靠拢（DTW 算法比较） | 越高越好 |
| 5 | **能力等级分布位移** | 用户画像聚合引擎 | 班级能力分布从正态分布向右偏态的移动距离 | 向右为好 |
| 6 | **协作/竞争活跃度** | 教师端横向总结 | 班级内高频搜索词与高频错误修正的相互影响度 | 越高越好 |
| 7 | **知识图谱连通性** | Neo4j | 班级整体掌握的词汇在知识图谱中的连通分量大小 | 越高越好 |
| 8 | **中上层"瓶颈期"时长** | DKT 预测模型 | 成绩处于 [80, 85] 区间学生进入停滞状态的平均天数 | 越短越好 |
| 9 | **反馈采纳群体倾向** | `EssayResult` | 中游学生对"结构建议"与"语法建议"的不同接受程度比例 | 指导教学权重 |
| 10 | **任务完成韧性** | Celery 任务状态量化 | 面对高难度异步任务后的持续学习保持率 | 越高越好 |

### 3.3 C. 底层学生托底维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 1 | **最小有效干预点** | `VocabularyItem` (`mastery_level`) | 连续3个单词 `mastery < 2` 时触发的知识点回溯预警 | 及时性 |
| 2 | **基础词汇缺口率** | Neo4j + 核心词库 | 针对当前场景，学生掌握的基础必备词比例 | 越低越险 |
| 3 | **学习动机衰减预警** | Redis 活跃度 + 响应延迟 | 连续复习天数下降且对话响应时间异常变长 | 越低越稳 |
| 4 | **L1 语言依赖度** | ASR + LLM 识别 | 对话中出现中文母语求助的频率 | 关注下降趋势 |
| 5 | **挫败感触发阈值** | `ConversationEvent` (对话终止事件) | 连续 N 次 LLM 纠错后用户直接关闭 WebSocket 的概率 | 越低越好 |

### 3.4 D. 顶层学生突破维度（5个）

| # | 维度名称 | 数据来源 | 计算方式 | 评价方向 |
|---|----------|----------|----------|----------|
| 1 | **修辞与风格多样性** | `EssayResult` (高级 NLP 分析) | 是否开始使用比喻、拟人、倒装等高阶修辞手段 | 越高越好 |
| 2 | **跨文化深度思辨值** | 对话模块 (LLM 内容分析) | 对话中涉及文化价值观冲突、社会现象讨论的广度与深度 | 越高越好 |
| 3 | **高阶词汇语义穿透** | ES + Neo4j | 对多义词在高难度、罕见语境下的正确使用比例 | 越高越好 |
| 4 | **自主策略调整能力** | `VocabularyItem.updated_at` | 根据遗忘情况自主调整学习强度或主动添加补充资料的行为 | 越高越好 |
| 5 | **语用逻辑严密性** | `EssayResult.result.dimensions.content` | 长篇作文中论证链条的完整性与反驳论点的逻辑质量 | 越高越好 |

---

## 4. 4-Agent 协作架构设计

### 4.1 Agent-0: 历史总结引擎（每日批处理）

**职责**: 每天凌晨为每个学生生成纵向历史信息摘要

**输入**: 
- 过去24小时的所有学习事件（`VocabularyItem` 更新、`EssayResult` 新增、`ConversationEvent` 新增）
- 历史聚合数据（Redis 缓存）

**输出**: 
- 每个学生一份 `StudentDailySummary` JSON，包含上述 20 个纵向维度的当日值和趋势
- 存储到 PostgreSQL `learning_summaries` 表或 Redis 缓存

**触发方式**: Celery 定时任务（`@app.on_after_configure.connect` 配置 `crontab(hour=2, minute=0)`）

### 4.2 Agent-1: 底层托底助手

**职责**: 识别学习困难学生，设计最小有效干预

**输入**: Agent-0 生成的 `StudentDailySummary`

**输出**: 
- 底层学生风险报告（基础缺口、动机衰减、挫败感预警）
- 个性化干预建议（简化任务、增加鼓励、基础词汇补习）

**关注指标**: C1-C5（托底维度）+ A1, A16（基础词汇、学习稳定性）

### 4.3 Agent-2: 中层突破助手

**职责**: 关注中下层到中上层学生，识别进步趋势和集中错误

**输入**: Agent-0 生成的 `StudentDailySummary` + 班级聚合数据

**输出**: 
- 中层学生进步报告（进步斜率、难度耐受力、瓶颈期识别）
- 班级共性错误分析（群体性错误共性指数）
- 教学重点建议（针对集中错误的专项练习）

**关注指标**: B1-B10（班级趋势维度）+ A6-A10（作文能力）、A11-A15（口语能力）

### 4.4 Agent-3: 顶层突破助手

**职责**: 关注高水平学生，识别瓶颈，设计高阶能力培养方案

**输入**: Agent-0 生成的 `StudentDailySummary`

**输出**: 
- 顶层学生瓶颈报告（修辞多样性、跨文化思辨、语义穿透）
- 高阶能力培养建议（辩论练习、文化深度讨论、学术写作）

**关注指标**: D1-D5（顶层突破维度）+ A19, A20（自主学习、主题覆盖）

---

## 5. 需要完成的工作

### 5.1 数据层

**文件建议**: `backend_fastapi/app/domain/analytics/models.py`

1. 新建数据模型：
   - `StudentDailySummary` — 学生每日纵向摘要（20个维度字段 + `user_id`, `date`, `created_at`）
   - `ClassDailySnapshot` — 班级每日横向快照（10个维度字段 + `class_id`, `date`）
   - `InterventionTask` — 干预任务（`student_id`, `agent_type`, `suggestion`, `status`, `due_date`）

2. Alembic 迁移脚本生成

### 5.2 Agent-0: 历史总结引擎

**文件建议**: `backend_fastapi/app/application/analytics/daily_summary.py`

1. 实现 `generate_student_daily_summary(user_id, date)` 函数
2. 从 PostgreSQL 查询当日数据，计算 20 个纵向维度
3. 将结果写入 `StudentDailySummary` 表
4. Celery 定时任务配置（每天凌晨 2:00 执行）

### 5.3 Agent-1/2/3: 分层分析引擎

**文件建议**: `backend_fastapi/app/application/analytics/agents.py`

1. 实现三个 Agent 类：
   - `BottomTierAgent.analyze(summaries)` → 底层风险报告
   - `MiddleTierAgent.analyze(summaries, class_snapshot)` → 中层突破报告
   - `TopTierAgent.analyze(summaries)` → 顶层瓶颈报告

2. 每个 Agent 输出结构化 JSON，包含：
   - `risk_students`: 风险学生列表
   - `insights`: 分析洞察
   - `suggestions`: 教学建议
   - `intervention_tasks`: 干预任务列表

### 5.4 教师端 API

**文件建议**: `backend_fastapi/app/interfaces/analytics_router.py`

**路由设计**:

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/analytics/class/{class_id}/overview` | 班级总览（能力分布、活跃趋势、风险人数） |
| GET | `/api/v1/analytics/class/{class_id}/students` | 学生列表（带风险标签、最近评分） |
| GET | `/api/v1/analytics/student/{student_id}/profile` | 学生个人画像（20个纵向维度时间序列） |
| GET | `/api/v1/analytics/student/{student_id}/report` | 学生分析报告（Agent-1/2/3 输出） |
| POST | `/api/v1/analytics/intervention` | 创建干预任务 |
| GET | `/api/v1/analytics/intervention/{task_id}` | 查询干预任务状态 |
| GET | `/api/v1/analytics/class/{class_id}/weekly` | 班级周报（LLM 生成自然语言总结） |

### 5.5 班级周报生成

**实现方式**: 
1. 每周日凌晨聚合一周数据
2. 调用 `llm.chat_complete()` 生成自然语言周报
3. Prompt 模板包含：班级整体表现、进步学生、风险学生、教学建议
4. 存储到 `LearningRecord` 表（`type = "weekly_report"`）

---

## 6. 依赖关系

| 依赖模块 | 状态 | 说明 |
|----------|------|------|
| PostgreSQL | ✅ 就绪 | 本地已启动，端口 5432 |
| Redis | ✅ 就绪 | 本地已启动，端口 6379 |
| Celery | ✅ 就绪 | Redis broker 已配置 |
| LLM 调用 | ✅ 就绪 | `llm.py` 已封装 Kimi API |
| SM-2 算法 | ✅ 就绪 | `domain/srs/sm2.py` |
| Neo4j KG | ⚠️ 可选 | 有降级保护，不安装也能运行 |
| 数据模型 | ⚠️ 需新建 | `StudentDailySummary`, `ClassDailySnapshot` |

---

## 7. 验收标准

- [ ] `StudentDailySummary` 表能存储 20 个纵向维度的每日数据
- [ ] `ClassDailySnapshot` 表能存储 10 个横向维度的每日数据
- [ ] Agent-0 每天凌晨自动运行，生成所有学生的日度摘要
- [ ] Agent-1/2/3 能基于日度摘要生成分层分析报告
- [ ] `GET /api/v1/analytics/class/{id}/overview` 返回班级总览（响应 < 2秒）
- [ ] `GET /api/v1/analytics/student/{id}/profile` 返回个人画像时间序列
- [ ] 风险学生识别准确率通过人工抽检（先规则驱动，后模型优化）
- [ ] 每条预警都能给出可解释原因和具体干预建议
- [ ] 班级周报生成后，教师可直接使用，不需大改
- [ ] 新增测试文件 `tests/test_analytics_module.py`，覆盖核心计算逻辑
- [ ] `pytest tests/ -m "not integration"` 仍然全绿

---

## 8. 注意事项与风险

1. **数据冷启动**: 新用户前7天数据不足，纵向维度可能为 null。建议用默认值或"数据收集中"状态占位。
2. **计算性能**: 20个维度 × 全班学生 × 每日计算，数据量大时可能慢。建议用 Redis 缓存中间结果，PostgreSQL 只存最终摘要。
3. **LLM 成本**: 班级周报生成消耗 Token。建议周报模板固定，只填充变量数据，减少 Prompt 长度。
4. **隐私合规**: 学生画像数据敏感，API 必须加 RBAC 权限检查（`require_role("teacher")` 或 `require_role("admin")`）。
5. **Neo4j 降级**: 若 Neo4j 未启动，构词法迁移、知识图谱连通性等维度应返回 null 而非报错。

---

## 9. 参考文档

- `docs/Detailed_System_Architecture.md` 第 4 章（教师端模块详细架构）
- `backend_fastapi/app/models.py`（`EssayResult`, `ConversationEvent`, `VocabularyItem`）
- `backend_fastapi/app/domain/models.py`（`User`, `StudentProfile`, `LearningPath`）
- `backend_fastapi/app/infrastructure/messaging/celery_app.py`（定时任务配置参考）
- `backend_fastapi/app/llm.py`（LLM 调用封装）
- `backend_fastapi/app/infrastructure/rbac.py`（角色权限检查）
