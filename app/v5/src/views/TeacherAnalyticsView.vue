<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  TeacherAnalyticsService,
  type ClassOverview,
  type DimensionTimePoint,
  type StudentDashboard,
  type StudentListItem,
} from '../services/teacherAnalytics';

const classId = ref('');
const overview = ref<ClassOverview | null>(null);
const students = ref<StudentListItem[]>([]);
const error = ref('');
const isLoading = ref(false);
const selectedStudentId = ref<number | null>(null);
const studentDashboard = ref<StudentDashboard | null>(null);
const studentError = ref('');
const studentReportNotice = ref('');
const isStudentLoading = ref(false);

const selectedStudent = computed(
  () => students.value.find((student) => student.user_id === selectedStudentId.value) || null,
);
const profile = computed(() => studentDashboard.value?.profile || null);
const report = computed(() => studentDashboard.value?.report || null);
const recentTrend = computed(() => (profile.value?.time_series || []).slice(-7).reverse());
const longitudinal = computed(() => profile.value?.longitudinal_summary || null);
const hasProfileData = computed(
  () =>
    Boolean(profile.value?.latest_summary || profile.value?.llm_narrative) ||
    (profile.value?.time_series.length || 0) > 0,
);

const agentNames: Record<string, string> = {
  foundation: '基础托底',
  middle: '能力提升',
  top: '突破拓展',
  overview: '综合建议',
};

const errorMessage = (e: any, scope: 'class' | 'student') => {
  const status = Number(e?.response?.status || 0);
  if (status === 400) return '请求范围无效，请确认班级 ID 和学生归属';
  if (status === 401) return '登录已过期，请重新登录教师或管理员账号';
  if (status === 403) return scope === 'class' ? '无权访问该班级' : '无权查看该学生在当前班级的数据';
  if (status === 404) return scope === 'class' ? '未找到该班级或对应学情' : '未找到该学生或指定日期的学情';
  if (status === 409) return '该学生在当前班级没有可归属的 Agent 报告，请检查班级归属';
  return scope === 'class' ? '加载班级学情失败，请稍后重试' : '加载个人学情失败，请稍后重试';
};

const httpStatus = (e: any) => Number(e?.response?.status || 0);

const formatNumber = (value: number | null | undefined, digits = 1) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return Number(value).toFixed(digits).replace(/\.0$/, '');
};

const formatTrendMetric = (point: DimensionTimePoint, key: keyof DimensionTimePoint) => {
  const value = point[key];
  return typeof value === 'number' ? formatNumber(value) : '--';
};

const flattenRiskFlags = (flags: string[][]) => [...new Set(flags.flat())];

const clearStudent = () => {
  selectedStudentId.value = null;
  studentDashboard.value = null;
  studentError.value = '';
  studentReportNotice.value = '';
};

const load = async () => {
  error.value = '';
  overview.value = null;
  students.value = [];
  clearStudent();
  if (!classId.value.trim()) {
    error.value = '请输入班级 ID';
    return;
  }
  isLoading.value = true;
  try {
    const id = classId.value.trim();
    const [nextOverview, nextStudents] = await Promise.all([
      TeacherAnalyticsService.getClassOverview(id),
      TeacherAnalyticsService.getClassStudents(id),
    ]);
    overview.value = nextOverview;
    students.value = nextStudents;
  } catch (e: any) {
    error.value = errorMessage(e, 'class');
  } finally {
    isLoading.value = false;
  }
};

const selectStudent = async (student: StudentListItem) => {
  selectedStudentId.value = student.user_id;
  studentDashboard.value = null;
  studentError.value = '';
  studentReportNotice.value = '';
  isStudentLoading.value = true;
  try {
    studentDashboard.value = await TeacherAnalyticsService.getStudentDashboard(
      student.user_id,
      classId.value.trim(),
      14,
    );
  } catch (e: any) {
    const status = httpStatus(e);
    if (status === 404 || status === 409) {
      try {
        const fallbackProfile = await TeacherAnalyticsService.getStudentProfile(
          student.user_id,
          classId.value.trim(),
          14,
        );
        studentDashboard.value = {
          student_id: student.user_id,
          profile: fallbackProfile,
          report: {
            user_id: student.user_id,
            date: overview.value?.date || '',
            agent_reports: [],
          },
        };
        studentReportNotice.value =
          status === 409
            ? '该学生在当前班级没有可归属的 Agent 报告'
            : '指定日期尚未生成 Agent 报告';
      } catch (profileError: any) {
        studentError.value = errorMessage(profileError, 'student');
      }
    } else {
      studentError.value = errorMessage(e, 'student');
    }
  } finally {
    isStudentLoading.value = false;
  }
};
</script>

<template>
  <div class="h-full overflow-y-auto p-5 md:p-8">
    <div class="mb-6 flex items-end gap-3">
      <label class="block w-64">
        <span class="text-sm text-gray-300">班级 ID</span>
        <input
          v-model="classId"
          class="mt-2 w-full rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-indigo-500"
          placeholder="例如 1"
          type="text"
          @keyup.enter="load"
        />
      </label>
      <button class="rounded-md bg-indigo-600 px-4 py-2 text-white disabled:opacity-60" :disabled="isLoading" @click="load">
        {{ isLoading ? '加载中...' : '加载学情' }}
      </button>
    </div>

    <div v-if="error" class="mb-6 rounded-md border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-200">
      {{ error }}
    </div>

    <div v-if="overview" class="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <div class="text-sm text-gray-400">总人数</div>
        <div class="mt-2 text-2xl font-semibold text-white">{{ overview.total_students }}</div>
        <div class="mt-1 text-xs text-gray-500">兼容口径，当前等于在册人数</div>
      </div>
      <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <div class="text-sm text-gray-400">在册学生</div>
        <div class="mt-2 text-2xl font-semibold text-white">{{ overview.enrolled_students }}</div>
        <div class="mt-1 text-xs text-gray-500">当前班级学生角色去重</div>
      </div>
      <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <div class="text-sm text-gray-400">当天活跃</div>
        <div class="mt-2 text-2xl font-semibold text-white">{{ overview.active_students }}</div>
        <div class="mt-1 text-xs text-gray-500">当天产生真实学习行为</div>
      </div>
      <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <div class="text-sm text-gray-400">当天已分析</div>
        <div class="mt-2 text-2xl font-semibold text-white">{{ overview.analyzed_students }}</div>
        <div class="mt-1 text-xs text-gray-500">已有班级归属一致的日摘要</div>
      </div>
    </div>

    <div v-if="overview" class="mb-6 flex flex-wrap gap-x-6 gap-y-2 border-y border-gray-800 py-3 text-sm text-gray-400">
      <span>统计日期 <strong class="font-medium text-gray-200">{{ overview.date }}</strong></span>
      <span>风险学生 <strong class="font-medium text-amber-300">{{ overview.risk_count }}</strong></span>
      <span>词汇增长均值 <strong class="font-medium text-gray-200">{{ formatNumber(overview.avg_vocab_growth) }}</strong></span>
      <span>语法变化均值 <strong class="font-medium text-gray-200">{{ formatNumber(overview.avg_grammar_decay) }}</strong></span>
    </div>

    <div v-if="overview" class="grid min-h-0 grid-cols-1 gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
      <section class="overflow-hidden rounded-lg border border-gray-700 bg-gray-800">
        <div class="border-b border-gray-700 px-4 py-3 text-sm font-medium text-gray-200">学生列表</div>
        <div v-if="students.length === 0" class="px-4 py-8 text-sm text-gray-400">该班级暂无在册学生</div>
        <div v-else class="max-h-[680px] divide-y divide-gray-700 overflow-y-auto">
          <button
            v-for="student in students"
            :key="student.user_id"
            type="button"
            class="block w-full px-4 py-3 text-left transition-colors hover:bg-gray-700"
            :class="selectedStudentId === student.user_id ? 'bg-indigo-950/60' : ''"
            @click="selectStudent(student)"
          >
            <div class="flex items-center justify-between gap-3">
              <span class="truncate text-sm font-medium text-white">{{ student.username || `学生 #${student.user_id}` }}</span>
              <span class="shrink-0 text-xs text-gray-400">{{ student.latest_score === null ? '暂无评分' : formatNumber(student.latest_score) }}</span>
            </div>
            <div class="mt-1 flex items-center justify-between gap-3 text-xs text-gray-500">
              <span>#{{ student.user_id }}</span>
              <span>{{ student.last_active_date || '暂无活动' }}</span>
            </div>
            <div v-if="student.risk_tags.length" class="mt-2 flex flex-wrap gap-1">
              <span v-for="tag in student.risk_tags.slice(0, 2)" :key="tag" class="rounded bg-amber-950 px-1.5 py-0.5 text-xs text-amber-300">
                {{ tag }}
              </span>
            </div>
          </button>
        </div>
      </section>

      <section class="min-w-0">
        <div v-if="!selectedStudentId" class="rounded-lg border border-gray-700 bg-gray-800 px-5 py-12 text-center text-sm text-gray-400">
          从左侧选择学生查看个人学情
        </div>

        <div v-else-if="isStudentLoading" class="rounded-lg border border-gray-700 bg-gray-800 px-5 py-12 text-center text-sm text-gray-300">
          正在加载个人学情...
        </div>

        <div v-else-if="studentError" class="rounded-md border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-200">
          {{ studentError }}
        </div>

        <div v-else-if="studentDashboard && profile" class="space-y-5">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-white">{{ profile.username || selectedStudent?.username || `学生 #${studentDashboard.student_id}` }}</h2>
              <p class="mt-1 text-sm text-gray-400">
                #{{ studentDashboard.student_id }} · 当前班级 {{ classId.trim() }} · 近 14 天
              </p>
            </div>
            <div class="text-right text-xs text-gray-500">
              <div>有摘要 {{ profile.data_quality?.days_with_summary ?? profile.time_series.length }} 天</div>
              <div v-if="profile.profile?.level" class="mt-1">水平 {{ profile.profile.level }}</div>
            </div>
          </div>

          <div v-if="!hasProfileData" class="rounded-lg border border-gray-700 bg-gray-800 px-5 py-10 text-center text-sm text-gray-400">
            该学生在当前班级和时间范围内暂无个人学情数据
          </div>

          <template v-else>
            <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 class="text-sm font-medium text-gray-200">风险与优势</h3>
                <div class="mt-3">
                  <div class="text-xs text-gray-500">风险</div>
                  <div v-if="longitudinal?.risk_flags.length" class="mt-2 flex flex-wrap gap-2">
                    <span v-for="flag in longitudinal.risk_flags" :key="flag" class="rounded bg-red-950 px-2 py-1 text-xs text-red-300">{{ flag }}</span>
                  </div>
                  <div v-else class="mt-2 text-sm text-gray-400">暂无显著风险</div>
                </div>
                <div class="mt-4">
                  <div class="text-xs text-gray-500">优势</div>
                  <div v-if="longitudinal?.strength_flags.length" class="mt-2 flex flex-wrap gap-2">
                    <span v-for="flag in longitudinal.strength_flags" :key="flag" class="rounded bg-emerald-950 px-2 py-1 text-xs text-emerald-300">{{ flag }}</span>
                  </div>
                  <div v-else class="mt-2 text-sm text-gray-400">暂无明显优势标签</div>
                </div>
              </div>

              <div class="rounded-lg border border-gray-700 bg-gray-800 p-4">
                <h3 class="text-sm font-medium text-gray-200">阶段判断</h3>
                <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-gray-300">
                  {{ longitudinal?.llm_summary || profile.llm_narrative || '已有数据，但尚未生成阶段性文字分析。' }}
                </p>
              </div>
            </div>

            <div class="overflow-hidden rounded-lg border border-gray-700 bg-gray-800">
              <div class="border-b border-gray-700 px-4 py-3 text-sm font-medium text-gray-200">近期趋势</div>
              <div v-if="recentTrend.length === 0" class="px-4 py-8 text-sm text-gray-400">暂无可展示的趋势数据</div>
              <div v-else class="overflow-x-auto">
                <table class="w-full min-w-[720px] text-sm">
                  <thead class="bg-gray-900/60 text-left text-xs text-gray-400">
                    <tr>
                      <th class="px-4 py-2 font-medium">日期</th>
                      <th class="px-4 py-2 font-medium">词汇增长</th>
                      <th class="px-4 py-2 font-medium">记忆保持</th>
                      <th class="px-4 py-2 font-medium">语法变化</th>
                      <th class="px-4 py-2 font-medium">口语速度</th>
                      <th class="px-4 py-2 font-medium">响应延迟(ms)</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-700 text-gray-300">
                    <tr v-for="point in recentTrend" :key="point.date">
                      <td class="px-4 py-2.5 text-gray-400">{{ point.date }}</td>
                      <td class="px-4 py-2.5">{{ formatTrendMetric(point, 'vocab_growth_rate') }}</td>
                      <td class="px-4 py-2.5">{{ formatTrendMetric(point, 'sm2_retention_rate') }}</td>
                      <td class="px-4 py-2.5">{{ formatTrendMetric(point, 'grammar_error_decay_slope') }}</td>
                      <td class="px-4 py-2.5">{{ formatTrendMetric(point, 'speech_wpm') }}</td>
                      <td class="px-4 py-2.5">{{ formatTrendMetric(point, 'response_latency_avg_ms') }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>

          <div class="overflow-hidden rounded-lg border border-gray-700 bg-gray-800">
            <div class="border-b border-gray-700 px-4 py-3 text-sm font-medium text-gray-200">Agent 建议</div>
            <div v-if="!report?.agent_reports.length" class="px-4 py-8 text-sm text-gray-400">
              {{ studentReportNotice || '当前班级与日期暂无 Agent 建议' }}
            </div>
            <div v-else class="divide-y divide-gray-700">
              <div v-for="agent in report.agent_reports" :key="agent.agent_type" class="p-4">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <h3 class="text-sm font-medium text-white">{{ agentNames[agent.agent_type] || agent.agent_type }}</h3>
                  <span v-if="flattenRiskFlags(agent.risk_flags).length" class="text-xs text-amber-300">
                    {{ flattenRiskFlags(agent.risk_flags).length }} 项风险依据
                  </span>
                </div>
                <ul v-if="agent.insights.length" class="mt-3 space-y-1 text-sm text-gray-300">
                  <li v-for="insight in agent.insights" :key="insight">{{ insight }}</li>
                </ul>
                <div v-if="agent.suggestions.length" class="mt-3 border-l-2 border-indigo-500 pl-3">
                  <div class="text-xs text-gray-500">建议</div>
                  <p v-for="suggestion in agent.suggestions" :key="suggestion" class="mt-1 text-sm text-indigo-200">{{ suggestion }}</p>
                </div>
                <div v-if="agent.intervention_tasks.length" class="mt-3 space-y-2">
                  <div v-for="task in agent.intervention_tasks" :key="`${task.title}-${task.due_date}`" class="bg-gray-900 px-3 py-2 text-sm">
                    <div class="font-medium text-gray-200">{{ task.title }}</div>
                    <div v-if="task.description" class="mt-1 text-xs text-gray-400">{{ task.description }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
