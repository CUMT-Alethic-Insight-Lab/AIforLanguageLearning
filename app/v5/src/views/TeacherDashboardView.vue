<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import BaseChart from '../components/BaseChart.vue';
import {
  TeacherAnalyticsService,
  type ChartData,
  type ClassOverview,
  type StudentListItem,
  type WeeklyReport,
} from '../services/teacherAnalytics';

const route = useRoute();
const classId = computed(() => (route.params.class_id as string) || 'class_default');

const isLoading = ref(false);
const overview = ref<ClassOverview | null>(null);
const students = ref<StudentListItem[]>([]);
const weekly = ref<WeeklyReport | null>(null);
const activeTab = ref<'overview' | 'students' | 'weekly'>('overview');
const recentDays = ref(3);
const assignmentStudentId = ref('');
const assignmentClassId = ref('');
const assignmentNote = ref('');
const assignmentLoading = ref(false);
const assignmentMessage = ref('');
const assignmentError = ref('');
const rowClassInputs = ref<Record<number, string>>({});

const buildChartOption = (chart: ChartData) => {
  const common = {
    backgroundColor: 'transparent',
    title: { text: chart.title, textStyle: { color: '#fff', fontSize: 14 } },
    tooltip: { trigger: chart.type === 'pie' ? 'item' : 'axis' },
    legend: { textStyle: { color: '#cbd5e1' } },
  };

  if (chart.type === 'pie') {
    return {
      ...common,
      series: [{
        type: 'pie',
        radius: ['42%', '70%'],
        data: chart.labels.map((label, index) => ({
          name: label,
          value: chart.datasets[0]?.data[index] ?? 0,
        })),
      }],
    };
  }

  if (chart.type === 'radar') {
    const maxVal = Math.max(...chart.datasets.flatMap(ds => ds.data), 100);
    return {
      ...common,
      radar: {
        indicator: chart.labels.map(label => ({ name: label, max: maxVal })),
        axisName: { color: '#cbd5e1' },
      },
      series: [{
        type: 'radar',
        data: chart.datasets.map(ds => ({
          value: ds.data,
          name: ds.label,
          areaStyle: { color: 'rgba(99,102,241,0.18)' },
        })),
      }],
    };
  }

  return {
    ...common,
    xAxis: {
      type: 'category',
      data: chart.labels,
      axisLabel: { color: '#cbd5e1', rotate: chart.labels.length > 5 ? 30 : 0 },
      axisLine: { lineStyle: { color: '#475569' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#cbd5e1' },
      splitLine: { lineStyle: { color: '#334155' } },
    },
    series: chart.datasets.map(ds => ({
      name: ds.label,
      type: chart.type,
      data: ds.data,
      smooth: chart.type === 'line',
      itemStyle: chart.type === 'bar' ? { borderRadius: [6, 6, 0, 0] } : undefined,
    })),
  };
};

const abilityPieOption = computed(() => overview.value?.charts?.ability_pie ? buildChartOption(overview.value.charts.ability_pie) : null);
const trendLineOption = computed(() => overview.value?.charts?.trend_line ? buildChartOption(overview.value.charts.trend_line) : null);
const radarOption = computed(() => overview.value?.charts?.class_radar ? buildChartOption(overview.value.charts.class_radar) : null);
const riskBarOption = computed(() => overview.value?.charts?.risk_bar ? buildChartOption(overview.value.charts.risk_bar) : null);

const loadDashboard = async () => {
  isLoading.value = true;
  try {
    const dashboard = await TeacherAnalyticsService.getClassDashboard(
      classId.value,
      undefined,
      recentDays.value,
      activeTab.value === 'weekly',
    );
    overview.value = dashboard.overview;
    students.value = dashboard.students;
    weekly.value = dashboard.weekly;
    rowClassInputs.value = Object.fromEntries(
      dashboard.students.map((student) => [student.user_id, student.class_id || classId.value]),
    );
    if (activeTab.value === 'weekly' && !dashboard.weekly) {
      weekly.value = await TeacherAnalyticsService.getWeeklyReport(classId.value);
    }
  } catch (error) {
    console.error('Failed to load teacher dashboard:', error);
  } finally {
    isLoading.value = false;
  }
};

const loadWeekly = async () => {
  const dashboard = await TeacherAnalyticsService.getClassDashboard(classId.value, undefined, recentDays.value, true);
  weekly.value = dashboard.weekly;
};

const submitClassAssignment = async (studentId: number, targetClassId: string, note = '') => {
  assignmentLoading.value = true;
  assignmentError.value = '';
  assignmentMessage.value = '';
  try {
    const result = await TeacherAnalyticsService.updateStudentClassAssignment(studentId, {
      class_id: targetClassId.trim() || null,
      note,
      sync_related_records: true,
    });
    assignmentMessage.value = `学生 ${result.user_id} 已更新为 ${result.class_id ?? '未分班'}`;
    assignmentStudentId.value = '';
    assignmentNote.value = '';
    await loadDashboard();
  } catch (error) {
    assignmentError.value = '分班/调班失败，请检查学生 ID 或后端状态';
    console.error('Failed to update class assignment:', error);
  } finally {
    assignmentLoading.value = false;
  }
};

const submitManualAssignment = async () => {
  const studentId = Number(assignmentStudentId.value);
  if (!studentId) {
    assignmentError.value = '请输入有效的学生 ID';
    return;
  }
  const targetClass = assignmentClassId.value.trim() || classId.value;
  await submitClassAssignment(studentId, targetClass, assignmentNote.value.trim());
};

const riskTagColor = (tag: string): string => ({
  '词汇薄弱': 'bg-rose-500/15 text-rose-200 border-rose-800',
  '稳定性差': 'bg-amber-500/15 text-amber-200 border-amber-800',
  '响应迟缓': 'bg-orange-500/15 text-orange-200 border-orange-800',
  '语法退步': 'bg-violet-500/15 text-violet-200 border-violet-800',
}[tag] || 'bg-slate-800 text-slate-300 border-slate-600');

watch(() => route.params.class_id, loadDashboard);
watch(recentDays, loadDashboard);
watch(activeTab, async (value) => {
  if (value === 'weekly') {
    await loadWeekly();
  }
});

onMounted(loadDashboard);
</script>

<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-white">班级学情面板</h2>
        <p class="text-slate-400 text-sm mt-1">班级: {{ classId }} | 日期: {{ overview?.date }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <select v-model="recentDays" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
          <option :value="3">最近3天分析</option>
          <option :value="5">最近5天分析</option>
          <option :value="7">最近7天分析</option>
        </select>
        <div class="flex space-x-2 bg-slate-800 p-1 rounded-lg">
          <button
            v-for="tab in ['overview', 'students', 'weekly'] as const"
            :key="tab"
            @click="activeTab = tab"
            class="px-4 py-2 rounded-md text-sm transition-colors"
            :class="activeTab === tab ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'"
          >
            {{ tab === 'overview' ? '当日+近况' : tab === 'students' ? '学生列表' : '周报' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="isLoading" class="flex justify-center items-center h-64 text-slate-400">
      加载中...
    </div>

    <div v-else-if="activeTab === 'overview' && overview" class="space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="text-slate-400 text-sm">班级人数</div>
          <div class="text-3xl font-bold text-white mt-2">{{ overview.total_students }}</div>
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="text-slate-400 text-sm">活跃人数</div>
          <div class="text-3xl font-bold text-emerald-400 mt-2">{{ overview.active_students }}</div>
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="text-slate-400 text-sm">风险人数</div>
          <div class="text-3xl font-bold text-rose-400 mt-2">{{ overview.risk_count }}</div>
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="text-slate-400 text-sm">平均词汇增长</div>
          <div class="text-3xl font-bold text-indigo-400 mt-2">{{ overview.avg_vocab_growth?.toFixed(2) ?? '—' }}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-80">
          <BaseChart v-if="abilityPieOption" :options="abilityPieOption" />
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-80">
          <BaseChart v-if="riskBarOption" :options="riskBarOption" />
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-80">
          <BaseChart v-if="trendLineOption" :options="trendLineOption" />
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-80">
          <BaseChart v-if="radarOption" :options="radarOption" />
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-white">教师分班 / 调班</h3>
            <span class="text-xs text-slate-400">会同步修正 analytics 链路中的 `class_id`</span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <input
              v-model="assignmentStudentId"
              type="number"
              min="1"
              placeholder="学生 ID"
              class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
            >
            <input
              v-model="assignmentClassId"
              type="text"
              :placeholder="`目标班级，默认 ${classId}`"
              class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
            >
            <button
              class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white rounded-lg px-4 py-2 text-sm"
              :disabled="assignmentLoading"
              @click="submitManualAssignment"
            >
              {{ assignmentLoading ? '处理中...' : '提交分班' }}
            </button>
          </div>
          <textarea
            v-model="assignmentNote"
            rows="2"
            placeholder="可选备注，例如：转入新班、按教师调整"
            class="mt-3 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
          />
          <div v-if="assignmentMessage" class="mt-3 text-sm text-emerald-300">{{ assignmentMessage }}</div>
          <div v-if="assignmentError" class="mt-2 text-sm text-rose-300">{{ assignmentError }}</div>
        </div>

        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <h3 class="text-lg font-semibold text-white mb-4">当天班级客观摘要</h3>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div class="flex justify-between">
              <span class="text-slate-400">词汇增长均值</span>
              <span class="text-white">{{ overview.trend_7d.vocab_growth_avg?.toFixed(3) ?? '—' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-400">语法收敛均值</span>
              <span class="text-white">{{ overview.trend_7d.grammar_decay_avg?.toFixed(3) ?? '—' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-400">近7日数据点</span>
              <span class="text-white">{{ overview.trend_7d.data_points }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-400">共性错误指数</span>
              <span class="text-white">{{ overview.trend_7d.common_error_index?.toFixed(3) ?? '—' }}</span>
            </div>
          </div>
        </div>

        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-white">最近{{ recentDays }}天班级分析</h3>
            <span class="text-xs text-slate-400">
              {{ overview.recent_analysis?.window_start }} - {{ overview.recent_analysis?.window_end }}
            </span>
          </div>
          <div class="text-slate-200 whitespace-pre-wrap leading-7">
            {{ overview.recent_analysis?.content ?? '暂无近况分析' }}
          </div>
          <div v-if="overview.recent_analysis?.evidence?.length" class="mt-4 space-y-2">
            <div
              v-for="(item, index) in overview.recent_analysis.evidence.slice(0, 4)"
              :key="index"
              class="bg-slate-900/60 rounded-lg p-3 text-sm text-slate-300"
            >
              {{ item.summary || item.content || JSON.stringify(item) }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="activeTab === 'students'" class="space-y-4">
      <div class="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-900 text-slate-400">
            <tr>
              <th class="px-4 py-3">学生ID</th>
              <th class="px-4 py-3">用户名</th>
              <th class="px-4 py-3">当前班级</th>
              <th class="px-4 py-3">风险标签</th>
              <th class="px-4 py-3">最近评分</th>
              <th class="px-4 py-3">最后活跃</th>
              <th class="px-4 py-3">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-700">
            <tr v-for="student in students" :key="student.user_id" class="hover:bg-slate-700/40 transition-colors">
              <td class="px-4 py-3 text-white">{{ student.user_id }}</td>
              <td class="px-4 py-3 text-white">{{ student.username ?? '—' }}</td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <input
                    v-model="rowClassInputs[student.user_id]"
                    type="text"
                    class="w-28 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                  >
                  <button
                    class="text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50"
                    :disabled="assignmentLoading"
                    @click="submitClassAssignment(student.user_id, rowClassInputs[student.user_id] || '', 'dashboard_inline_update')"
                  >
                    调班
                  </button>
                </div>
              </td>
              <td class="px-4 py-3">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="tag in student.risk_tags"
                    :key="tag"
                    class="px-2 py-0.5 text-xs rounded border"
                    :class="riskTagColor(tag)"
                  >
                    {{ tag }}
                  </span>
                  <span v-if="student.risk_tags.length === 0" class="text-slate-500 text-xs">无风险</span>
                </div>
              </td>
              <td class="px-4 py-3 text-white">{{ student.latest_score?.toFixed(1) ?? '—' }}</td>
              <td class="px-4 py-3 text-slate-400">{{ student.last_active_date ?? '—' }}</td>
              <td class="px-4 py-3">
                <router-link :to="`/teacher/student/${student.user_id}`" class="text-indigo-300 hover:text-indigo-200 text-xs">
                  查看画像
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="students.length === 0" class="p-8 text-center text-slate-500">暂无学生数据</div>
      </div>
    </div>

    <div v-else class="space-y-4">
      <div class="bg-slate-800 rounded-xl p-6 border border-slate-700">
        <h3 class="text-lg font-semibold text-white mb-4">班级周报</h3>
        <div class="text-slate-200 whitespace-pre-wrap leading-7">
          {{ weekly?.content ?? '加载中...' }}
        </div>
        <div v-if="weekly?.evidence?.length" class="mt-5 space-y-2">
          <div class="text-xs text-slate-400">证据摘要</div>
          <div
            v-for="(item, index) in weekly.evidence.slice(0, 5)"
            :key="index"
            class="bg-slate-900/60 rounded-lg p-3 text-sm text-slate-300"
          >
            {{ item.title || item.content || JSON.stringify(item) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
