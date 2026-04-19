# 教师端学情分析模块 — 前后端集成指南

**文档日期**: 2026年4月18日  
**适用范围**: 前端 (Vue3/ECharts) + 后端 (FastAPI/SQLModel) 集成

---

## 1. 架构设计原则

### 1.1 数据流分层

```
┌─────────────────────────────────────────────────────────────┐
│  前端 (Vue3 + ECharts)                                      │
│  - 纯展示层，不做复杂计算                                    │
│  - 接收后端预格式化的图表数据，直接渲染                        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓ JSON (ChartData格式)
┌─────────────────────────────────────────────────────────────┐
│  后端 API (FastAPI)                                         │
│  - 数据库聚合查询（SQL）→ 零 LLM Token                       │
│  - 图表数据预组装（Python）→ 前端即拿即用                      │
│  - 仅周报/自然语言报告调用 LLM                                │
└─────────────────────────────────────────────────────────────┘
                              ↑↓ SQL
┌─────────────────────────────────────────────────────────────┐
│  数据库 (PostgreSQL/SQLite)                                 │
│  - StudentDailySummary (20维度纵向)                         │
│  - ClassDailySnapshot (10维度横向)                          │
│  - InterventionTask (干预任务)                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Token 消耗控制策略

| 功能 | 数据聚合 | LLM 使用 | Token 策略 |
|------|----------|----------|-----------|
| 班级总览 | SQL 查询 | ❌ 不使用 | 零消耗 |
| 学生列表 | SQL 查询 | ❌ 不使用 | 零消耗 |
| 个人画像 | SQL 查询 | ❌ 不使用 | 零消耗 |
| 20维雷达图 | SQL + Python 标准化 | ❌ 不使用 | 零消耗 |
| 趋势折线图 | SQL 时间序列 | ❌ 不使用 | 零消耗 |
| 分层分析报告 | SQL + 规则引擎 | ❌ 不使用 | 零消耗 |
| **班级周报** | SQL 聚合 | ✅ 仅润色 | **固定模板+变量填充** |

**核心原则**: 能用数据库聚合的绝不用 LLM，能用规则引擎的绝不用 LLM，LLM 只负责"自然语言润色"这一件事。

---

## 2. 前端集成

### 2.1 技术栈

- **框架**: Vue 3 + TypeScript + `<script setup>`
- **图表**: ECharts 5.4.3（已封装 `BaseChart.vue`）
- **样式**: Tailwind CSS（深色模式）
- **路由**: Vue Router（Hash 模式）
- **HTTP**: Axios（已封装 `api.ts`，支持 Bearer Token）

### 2.2 新增文件

```
app/v5/src/
├── services/
│   └── teacherAnalytics.ts          # 教师端 API 服务封装
├── views/
│   ├── TeacherDashboardView.vue     # 班级总览仪表盘
│   └── StudentProfileView.vue       # 学生个人画像
└── router/index.ts                  # 新增 /teacher 路由
```

### 2.3 图表数据格式 (ChartData)

后端返回的统一图表数据结构，与 `BaseChart.vue` 直接兼容：

```typescript
interface ChartData {
  type: 'radar' | 'line' | 'bar' | 'pie' | 'scatter';
  title: string;
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
  }>;
}
```

**前端渲染逻辑**（已在 `TeacherDashboardView.vue` 和 `StudentProfileView.vue` 中实现）：

```typescript
const buildChartOption = (chart: ChartData) => {
  if (chart.type === 'pie') {
    return {
      series: [{
        type: 'pie',
        data: chart.labels.map((label, i) => ({
          name: label,
          value: chart.datasets[0]?.data[i] ?? 0,
        })),
      }]
    };
  }
  // ... radar, line, bar 同理
};
```

### 2.4 页面路由

| 路由 | 组件 | 权限 | 功能 |
|------|------|------|------|
| `/teacher` | `TeacherDashboardView` | TEACHER+ | 班级总览（饼图+折线图+统计卡片） |
| `/teacher/student/:id` | `StudentProfileView` | TEACHER+ | 学生画像（雷达图+趋势图+Agent报告） |

### 2.5 侧边栏入口

已在 `Sidebar.vue` 中新增：

```typescript
{ name: '教师仪表盘', path: '/teacher', icon: '🎓' }
```

---

## 3. 后端集成

### 3.1 API 响应格式升级

所有涉及图表的接口已新增 `charts` 字段：

**ClassOverviewResponse**:
```json
{
  "class_id": "class_101",
  "total_students": 30,
  "risk_count": 5,
  "charts": {
    "ability_pie": {
      "type": "pie",
      "title": "能力分布",
      "labels": ["底层", "中层", "顶层"],
      "datasets": [{"label": "人数", "data": [6, 18, 6]}]
    },
    "trend_line": {
      "type": "line",
      "title": "7日趋势",
      "labels": ["2026-04-12", "..."],
      "datasets": [
        {"label": "词汇增长", "data": [3.2, 3.5, ...]},
        {"label": "语法收敛", "data": [0.8, 1.2, ...]}
      ]
    }
  }
}
```

**StudentProfileResponse**:
```json
{
  "user_id": 1,
  "charts": {
    "radar_20d": {
      "type": "radar",
      "title": "20维度能力雷达",
      "labels": ["词汇增长", "SM-2保持", "..."],
      "datasets": [{"label": "当前能力", "data": [65, 80, ...]}]
    },
    "trend_0": {
      "type": "line",
      "title": "词汇维度趋势",
      "labels": ["2026-03-20", "..."],
      "datasets": [...]
    }
  }
}
```

### 3.2 数据库聚合查询（零 Token）

**班级总览图表** (`analytics_router.py::class_overview`):

```python
# 能力分布饼图 → 纯 SQL + Python 聚合
ability_dist = _calc_ability_distribution(summaries)
charts["ability_pie"] = ChartData(
    type="pie",
    labels=["底层", "中层", "顶层"],
    datasets=[{"label": "人数", "data": [ability_dist["bottom"], ...]}]
)

# 7日趋势折线图 → SQL 时间序列聚合
for d in range(7):
    day_sums = [s for s in week_summaries if s.summary_date == d_date]
    trend_vocab.append(mean([s.vocab_growth_rate for s in day_sums]))
charts["trend_line"] = ChartData(type="line", ...)
```

**学生雷达图** (`analytics_router.py::student_profile`):

```python
# 20维度标准化 → Python 数值计算（零 LLM）
normalized = []
for i, val in enumerate(radar_data):
    if val is None:
        normalized.append(0)
    elif i in (0, 1, 2, ...):  # 越高越好
        normalized.append(min(100, max(0, float(val) * 20)))
    elif i in (10, 16):  # 越低越好
        normalized.append(min(100, max(0, 100 - float(val))))
    else:  # 计数类
        normalized.append(min(100, float(val) * 10))
```

### 3.3 LLM 使用场景（仅周报）

**班级周报** (`weekly_report.py`):

```python
# Step 1: 数据库聚合（零 Token）
class_data = _aggregate_weekly_class_data(class_id, week_start, session)
student_summaries = _aggregate_weekly_student_summaries(class_id, week_start, session)

# Step 2: LLM 仅做自然语言润色（固定模板+变量填充）
prompt = WEEKLY_REPORT_PROMPT_TEMPLATE.format(
    class_id=class_id,
    class_data=json.dumps(class_data, ensure_ascii=False, indent=2),
    student_summaries=json.dumps(student_summaries[:20], ensure_ascii=False, indent=2),
)

# Step 3: 调用 LLM（带 scene 路由，本地优先）
llm_response = asyncio.run(
    chat_complete(
        system_prompt="你是一位资深外语教学分析师...",
        user_text=prompt,
    )
)
```

**Prompt 长度控制**:
- 模板固定，只填充变量
- 学生摘要限制最多 20 条
- 预期 Token: ~800-1500/次

### 3.4 模型路由策略（本地 vs 云端）

后端 `llm.py` 已实现自动模型发现与路由：

```python
# _resolve_llm_model 优先级：
# 1. 场景模型（runtime_config.models.scene.analytics）
# 2. 主模型（runtime_config.models.primary）
# 3. settings.llm_model
# 4. 自动发现 /models 端点
```

**配置建议**:

| 场景 | 推荐模型 | 配置方式 |
|------|----------|----------|
| 开发/测试 | 本地 LM Studio | `settings.llm_base_url = "http://localhost:1234/v1"` |
| 生产（周报） | 云端 Kimi API | `runtime_config.models.scene.analytics = "kimi-model"` |
| 降级保护 | 自动发现 | 无需配置，自动 fallback |

**运行时切换**（无需重启）:

```bash
# 通过 API 切换周报生成模型
POST /api/v1/model-routing/config
{
  "scene": "analytics",
  "model_id": "moonshot-v1-8k"
}
```

---

## 4. 性能优化

### 4.1 响应时间目标

| 接口 | 目标响应时间 | 优化手段 |
|------|-------------|----------|
| `GET /class/{id}/overview` | < 500ms | SQL 索引 + 预聚合 |
| `GET /student/{id}/profile` | < 800ms | 时间范围限制（默认30天） |
| `GET /class/{id}/weekly` | < 3s | LLM 异步 + 结果缓存 |

### 4.2 缓存策略

```python
# 周报缓存（LearningRecord 表）
existing = session.exec(
    select(LearningRecord)
    .where(LearningRecord.type == "weekly_report")
    .where(LearningRecord.meta_data["class_id"].astext == class_id)
    .where(LearningRecord.created_at >= week_start)
    .where(LearningRecord.created_at <= week_end)
).first()

if existing:
    return existing  # 直接返回缓存，零 LLM 调用
```

### 4.3 数据库索引

已在新表上创建索引：

```sql
-- student_daily_summaries
CREATE INDEX ix_student_daily_summaries_user_id ON student_daily_summaries(user_id);
CREATE INDEX ix_student_daily_summaries_summary_date ON student_daily_summaries(summary_date);
CREATE UNIQUE INDEX uq_student_daily_summary ON student_daily_summaries(user_id, summary_date);

-- class_daily_snapshots
CREATE INDEX ix_class_daily_snapshots_class_id ON class_daily_snapshots(class_id);
CREATE INDEX ix_class_daily_snapshots_snapshot_date ON class_daily_snapshots(snapshot_date);
```

---

## 5. 部署检查清单

### 5.1 后端

- [ ] Alembic 迁移已应用 (`alembic upgrade head`)
- [ ] Celery 定时任务已配置（`crontab(hour=2, minute=0)`）
- [ ] `analytics_router` 已在 `main.py` 注册
- [ ] `domain.analytics.models` 已在 `db.py` 导入

### 5.2 前端

- [ ] `teacherAnalytics.ts` 服务文件已创建
- [ ] `TeacherDashboardView.vue` 和 `StudentProfileView.vue` 已创建
- [ ] 路由已添加 (`/teacher`, `/teacher/student/:id`)
- [ ] 侧边栏已添加入口
- [ ] `BaseChart.vue` 已复用（无需修改）

### 5.3 模型路由

- [ ] 本地 LM Studio 已启动（开发环境）
- [ ] 或 Kimi API Key 已配置（生产环境）
- [ ] `runtime_config.json` 中 `models.scene.analytics` 已设置（可选）

---

## 6. 文件清单

### 后端

```
backend_fastapi/
├── app/
│   ├── domain/analytics/models.py          # 数据模型
│   ├── application/analytics/
│   │   ├── daily_summary.py                # Agent-0
│   │   ├── agents.py                       # Agent-1/2/3
│   │   └── weekly_report.py                # 周报生成
│   ├── interfaces/analytics_router.py      # API路由（含图表数据）
│   ├── infrastructure/messaging/
│   │   ├── celery_app.py                   # 队列路由
│   │   └── analytics_tasks.py              # 定时任务
│   ├── db.py                               # 模型注册
│   └── main.py                             # 路由注册
├── alembic/versions/98ed1e32bf23_*.py      # 迁移脚本
└── tests/test_analytics_module.py          # 测试
```

### 前端

```
app/v5/src/
├── services/teacherAnalytics.ts            # API服务
├── views/
│   ├── TeacherDashboardView.vue            # 班级仪表盘
│   └── StudentProfileView.vue              # 学生画像
├── components/BaseChart.vue                # 图表组件（复用）
├── components/Sidebar.vue                  # 侧边栏（新增入口）
└── router/index.ts                         # 路由配置
```

---

## 7. 后续扩展建议

1. **实时数据**: 接入 WebSocket 推送日度摘要更新
2. **对比分析**: 支持班级间/周期间对比（增加 `compare_class_id` 参数）
3. **导出功能**: 支持 PDF/Excel 导出（后端生成，前端下载）
4. **移动端适配**: 当前为桌面端优化，图表在移动端需调整布局
5. **权限细化**: 支持"班主任只看本班"（增加 `class_id` 到 User 模型）
