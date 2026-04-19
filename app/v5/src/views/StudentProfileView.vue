<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import BaseChart from '../components/BaseChart.vue';
import {
  TeacherAnalyticsService,
  type ChartData,
  type StudentProfile,
  type StudentReport,
} from '../services/teacherAnalytics';

const route = useRoute();
const studentId = computed(() => Number(route.params.student_id));

const isLoading = ref(false);
const profile = ref<StudentProfile | null>(null);
const report = ref<StudentReport | null>(null);
const selectedDays = ref(14);
const activeTab = ref<'overview' | 'trends' | 'report'>('overview');
const classEditor = ref('');
const classAssignmentLoading = ref(false);
const classAssignmentMessage = ref('');
const classAssignmentError = ref('');

const buildChartOption = (chart: ChartData) => {
  const base = {
    backgroundColor: 'transparent',
    title: { text: chart.title, textStyle: { color: '#fff', fontSize: 14 } },
    tooltip: { trigger: chart.type === 'pie' ? 'item' : 'axis' },
    legend: { textStyle: { color: '#cbd5e1' } },
  };
  if (chart.type === 'radar') {
    const maxVal = Math.max(...chart.datasets.flatMap(ds => ds.data), 100);
    return {
      ...base,
      radar: {
        indicator: chart.labels.map(label => ({ name: label, max: maxVal })),
        axisName: { color: '#cbd5e1' },
        splitArea: { areaStyle: { color: ['rgba(99,102,241,0.05)', 'rgba(99,102,241,0.1)'] } },
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
  if (chart.type === 'pie') {
    return {
      ...base,
      series: [{
        type: 'pie',
        radius: ['42%', '70%'],
        data: chart.labels.map((label, index) => ({ name: label, value: chart.datasets[0]?.data[index] ?? 0 })),
      }],
    };
  }
  return {
    ...base,
    xAxis: {
      type: 'category',
      data: chart.labels,
      axisLabel: { color: '#cbd5e1', rotate: chart.labels.length > 6 ? 35 : 0 },
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

const radarOption = computed(() => {
  const chart = profile.value?.charts?.radar_20d;
  return chart ? buildChartOption(chart) : null;
});

const focusBarOption = computed(() => {
  const chart = profile.value?.charts?.focus_bar;
  return chart ? buildChartOption(chart) : null;
});

const trendOptions = computed(() => {
  return (profile.value?.charts?.trend_lines || []).map((chart) => buildChartOption(chart));
});

const methodologyGroups = computed(() => {
  const methodology = profile.value?.analysis_methodology || {};
  return {
    noLlm: Object.entries(methodology).filter(([, val]) => val.mode === 'no_llm'),
    autoAssist: Object.entries(methodology).filter(([, val]) => val.mode === 'automation_assisted'),
    llmRequired: Object.entries(methodology).filter(([, val]) => val.mode === 'llm_required'),
  };
});

const latestSummaryEntries = computed(() => {
  const latest = profile.value?.latest_summary;
  if (!latest) return [];
  return Object.entries(latest).filter(([key]) => ![
    'metric_methodology',
    'llm_used_for',
    'topics',
    'goals',
    'interests',
  ].includes(key));
});

const loadData = async () => {
  isLoading.value = true;
  try {
    const dashboard = await TeacherAnalyticsService.getStudentDashboard(studentId.value, selectedDays.value);
    profile.value = dashboard.profile;
    report.value = dashboard.report;
    classEditor.value = dashboard.profile.profile?.class_id || '';
  } catch (error) {
    console.error('Failed to load student analytics:', error);
  } finally {
    isLoading.value = false;
  }
};

const saveClassAssignment = async () => {
  classAssignmentLoading.value = true;
  classAssignmentError.value = '';
  classAssignmentMessage.value = '';
  try {
    const result = await TeacherAnalyticsService.updateStudentClassAssignment(studentId.value, {
      class_id: classEditor.value.trim() || null,
      note: 'student_profile_view_update',
      sync_related_records: true,
    });
    classAssignmentMessage.value = `班级已更新为 ${result.class_id ?? '未分班'}`;
    await loadData();
  } catch (error) {
    classAssignmentError.value = '更新班级失败，请稍后重试';
    console.error('Failed to update student class assignment:', error);
  } finally {
    classAssignmentLoading.value = false;
  }
};

const agentTypeLabel = (type: string): string => ({
  bottom: '底层托底',
  middle: '中层突破',
  top: '顶层突破',
  overview: '综合评估',
}[type] || type);

const priorityColor = (priority: string): string => ({
  critical: 'text-red-400',
  high: 'text-orange-400',
  normal: 'text-amber-300',
  low: 'text-slate-400',
}[priority] || 'text-slate-400');

onMounted(loadData);
watch(() => route.params.student_id, loadData);
</script>

<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-white">学生学情</h2>
        <p class="text-sm text-slate-400 mt-1">
          ID: {{ studentId }} | {{ profile?.username ?? '—' }} | 班级: {{ profile?.profile?.class_id ?? '未分班' }}
        </p>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <input
            v-model="classEditor"
            type="text"
            placeholder="设置/调整班级"
            class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
          >
          <button
            class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 text-white rounded-lg px-4 py-2 text-sm"
            :disabled="classAssignmentLoading"
            @click="saveClassAssignment"
          >
            {{ classAssignmentLoading ? '保存中...' : '保存班级' }}
          </button>
          <span v-if="classAssignmentMessage" class="text-sm text-emerald-300">{{ classAssignmentMessage }}</span>
          <span v-if="classAssignmentError" class="text-sm text-rose-300">{{ classAssignmentError }}</span>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <select v-model="selectedDays" @change="loadData" class="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
          <option :value="7">近7天</option>
          <option :value="14">近14天</option>
          <option :value="30">近30天</option>
        </select>
        <div class="flex space-x-2 bg-slate-800 p-1 rounded-lg">
          <button
            v-for="tab in ['overview', 'trends', 'report'] as const"
            :key="tab"
            @click="activeTab = tab"
            class="px-4 py-2 rounded-md text-sm transition-colors"
            :class="activeTab === tab ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'"
          >
            {{ tab === 'overview' ? '当天+窗口' : tab === 'trends' ? '趋势图' : 'Agent报告' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="isLoading" class="flex items-center justify-center h-64 text-slate-400">
      加载中...
    </div>

    <div v-else-if="activeTab === 'overview'" class="space-y-6">
      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-[420px]">
          <BaseChart v-if="radarOption" :options="radarOption" />
          <div v-else class="flex items-center justify-center h-full text-slate-500">暂无当天雷达图</div>
        </div>
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-[420px]">
          <BaseChart v-if="focusBarOption" :options="focusBarOption" />
          <div v-else class="flex items-center justify-center h-full text-slate-500">暂无柱状图数据</div>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-lg font-semibold text-white">当天状态</h3>
            <span class="text-xs text-slate-400">{{ profile?.latest_summary?.date ?? '—' }}</span>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <div v-for="[key, val] in latestSummaryEntries" :key="key" class="bg-slate-900/60 rounded-lg p-3">
              <div class="text-xs text-slate-400">{{ key }}</div>
              <div class="text-white mt-1 break-all">{{ val ?? '—' }}</div>
            </div>
          </div>
          <div v-if="profile?.latest_summary?.topics?.length" class="mt-4">
            <div class="text-xs text-slate-400 mb-2">近期主题</div>
            <div class="flex flex-wrap gap-2">
              <span v-for="topic in profile.latest_summary.topics" :key="topic" class="px-2 py-1 rounded bg-indigo-500/15 text-indigo-200 text-xs">
                {{ topic }}
              </span>
            </div>
          </div>
        </div>

        <div class="bg-slate-800 rounded-xl p-5 border border-slate-700">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-lg font-semibold text-white">近{{ profile?.longitudinal_summary?.window_days ?? selectedDays }}天纵向总结</h3>
            <span class="text-xs text-slate-400">
              {{ profile?.longitudinal_summary?.window_start }} - {{ profile?.longitudinal_summary?.window_end }}
            </span>
          </div>
          <div class="text-slate-200 leading-7 whitespace-pre-wrap">
            {{ profile?.longitudinal_summary?.llm_summary ?? '暂无纵向总结' }}
          </div>
          <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="bg-slate-900/60 rounded-lg p-3">
              <div class="text-rose-300 text-sm font-semibold mb-2">风险信号</div>
              <div class="flex flex-wrap gap-2">
                <span v-for="flag in profile?.longitudinal_summary?.risk_flags || []" :key="flag" class="px-2 py-1 rounded bg-rose-500/15 text-rose-200 text-xs">
                  {{ flag }}
                </span>
                <span v-if="!(profile?.longitudinal_summary?.risk_flags?.length)" class="text-xs text-slate-500">暂无</span>
              </div>
            </div>
            <div class="bg-slate-900/60 rounded-lg p-3">
              <div class="text-emerald-300 text-sm font-semibold mb-2">亮点</div>
              <div class="flex flex-wrap gap-2">
                <span v-for="flag in profile?.longitudinal_summary?.strength_flags || []" :key="flag" class="px-2 py-1 rounded bg-emerald-500/15 text-emerald-200 text-xs">
                  {{ flag }}
                </span>
                <span v-if="!(profile?.longitudinal_summary?.strength_flags?.length)" class="text-xs text-slate-500">暂无</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <div class="text-emerald-300 font-semibold mb-2">无需 LLM</div>
          <div class="space-y-1 text-slate-300">
            <div v-for="[key] in methodologyGroups.noLlm.slice(0, 8)" :key="key">{{ key }}</div>
          </div>
        </div>
        <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <div class="text-amber-300 font-semibold mb-2">自动化辅助</div>
          <div class="space-y-1 text-slate-300">
            <div v-for="[key] in methodologyGroups.autoAssist.slice(0, 8)" :key="key">{{ key }}</div>
          </div>
        </div>
        <div class="bg-slate-800 rounded-xl p-4 border border-slate-700">
          <div class="text-indigo-300 font-semibold mb-2">必须 LLM</div>
          <div class="space-y-1 text-slate-300">
            <div v-for="[key] in methodologyGroups.llmRequired" :key="key">{{ key }}</div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="activeTab === 'trends'" class="space-y-6">
      <div
        v-for="(option, index) in trendOptions"
        :key="index"
        class="bg-slate-800 rounded-xl p-5 border border-slate-700 h-80"
      >
        <BaseChart :options="option" />
      </div>
      <div v-if="trendOptions.length === 0" class="text-center text-slate-500 py-12">
        暂无趋势数据
      </div>
    </div>

    <div v-else class="space-y-4">
      <div
        v-for="(agent, index) in report?.agent_reports || []"
        :key="index"
        class="bg-slate-800 rounded-xl p-5 border border-slate-700"
      >
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-lg font-semibold text-white">{{ agentTypeLabel(agent.agent_type) }}</h3>
          <span class="text-xs text-slate-400">{{ report?.date }}</span>
        </div>
        <div v-if="agent.insights.length" class="mb-4">
          <div class="text-xs text-slate-400 mb-2">洞察</div>
          <div class="space-y-2 text-slate-200 text-sm">
            <div v-for="(insight, insightIndex) in agent.insights" :key="insightIndex">{{ insight }}</div>
          </div>
        </div>
        <div v-if="agent.suggestions.length" class="mb-4">
          <div class="text-xs text-slate-400 mb-2">建议</div>
          <div class="space-y-2 text-indigo-200 text-sm">
            <div v-for="(suggestion, suggestionIndex) in agent.suggestions" :key="suggestionIndex">{{ suggestion }}</div>
          </div>
        </div>
        <div v-if="agent.risk_flags.length" class="mb-4">
          <div class="text-xs text-slate-400 mb-2">风险标记</div>
          <div class="flex flex-wrap gap-2">
            <span v-for="(flags, flagIndex) in agent.risk_flags" :key="flagIndex" class="px-2 py-1 rounded bg-rose-500/15 text-rose-200 text-xs">
              {{ flags.join('；') }}
            </span>
          </div>
        </div>
        <div v-if="agent.evidence?.length" class="mb-4">
          <div class="text-xs text-slate-400 mb-2">证据摘要</div>
          <div class="space-y-2">
            <div v-for="(item, evidenceIndex) in agent.evidence" :key="evidenceIndex" class="bg-slate-900/60 rounded-lg p-3 text-sm text-slate-300">
              {{ item.excerpt || item.content || JSON.stringify(item) }}
            </div>
          </div>
        </div>
        <div v-if="agent.intervention_tasks.length">
          <div class="text-xs text-slate-400 mb-2">干预任务</div>
          <div class="space-y-2">
            <div v-for="(task, taskIndex) in agent.intervention_tasks" :key="taskIndex" class="bg-slate-900/60 rounded-lg p-3 border border-slate-700">
              <div class="flex items-center justify-between">
                <div class="text-white text-sm font-medium">{{ task.title }}</div>
                <span class="text-xs" :class="priorityColor(task.priority)">{{ task.priority }}</span>
              </div>
              <div class="text-slate-400 text-xs mt-1">{{ task.description }}</div>
              <div class="text-slate-500 text-xs mt-1">截止 {{ task.due_date ?? '无' }} | 状态 {{ task.status }}</div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!(report?.agent_reports?.length)" class="text-center text-slate-500 py-12">暂无分析报告</div>
    </div>
  </div>
</template>
