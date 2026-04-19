<script setup lang="ts">
/**
 * @fileoverview 学习分析视图组件 (AnalysisView)
 * @description 展示用户的学习进度和能力分析图表。
 *              包含概览统计卡片和基于 ECharts 的可视化图表（雷达图、折线图）。
 *              支持三个标签页切换：overview / vocabulary / progress
 */

import { ref, onMounted, computed } from 'vue';
import { AnalysisService, type LearningStats, type AnalysisResult } from '../services/analysis';
import BaseChart from '../components/BaseChart.vue';

// --- 状态管理 ---

/** 当前激活的标签页 (默认为 'overview') */
const activeTab = ref('overview');

/** 学习统计数据 (顶部卡片) */
const stats = ref<LearningStats>({ vocabulary: 0, essay: 0, dialogue: 0, analysis: 0 });

/** 加载状态 */
const isLoading = ref(false);

/** 词汇量趋势图表配置 (折线图) */
const vocabChartOption = ref<any>(null);

/** 综合能力图表配置 (雷达图) */
const skillsChartOption = ref<any>(null);

/** 各维度分析结果原始数据 */
const analysisResults = ref<Record<string, AnalysisResult>>({});

// --- 图表配置生成 ---

/**
 * 根据后端返回的可视化数据生成 ECharts 配置对象
 * 
 * @param {AnalysisResult['visualization']} viz - 后端返回的可视化数据结构
 * @returns {Object} ECharts 配置对象
 */
const createChartOption = (viz: AnalysisResult['visualization']) => {
  const commonOptions = {
    backgroundColor: 'transparent',
    title: { text: viz.title, textStyle: { color: '#fff' } },
    tooltip: { trigger: 'axis' },
  };

  if (viz.type === 'radar') {
    // 雷达图配置 (用于综合能力展示)
    return {
      ...commonOptions,
      radar: {
        indicator: viz.labels.map(label => ({ name: label, max: 100 })),
        axisName: { color: '#ccc' }
      },
      series: [{
        type: 'radar',
        data: viz.datasets.map(ds => ({
          value: ds.data,
          name: ds.label
        })),
        areaStyle: { color: 'rgba(99, 102, 241, 0.5)' },
        lineStyle: { color: '#6366f1' }
      }]
    };
  } else if (viz.type === 'line') {
    // 折线图配置 (用于趋势展示)
    return {
      ...commonOptions,
      xAxis: { 
        type: 'category', 
        data: viz.labels, 
        axisLabel: { color: '#ccc' } 
      },
      yAxis: { 
        type: 'value', 
        axisLabel: { color: '#ccc' }, 
        splitLine: { lineStyle: { color: '#333' } } 
      },
      series: viz.datasets.map(ds => ({
        name: ds.label,
        type: 'line',
        data: ds.data,
        smooth: true,
        itemStyle: { color: '#6366f1' }
      }))
    };
  }
  return {};
};

/**
 * 加载分析图表数据
 * 
 * 分别请求 'Overall' (综合) 和 'Vocabulary' (词汇) 的分析数据，
 * 并生成对应的图表配置。
 */
const loadAnalysis = async () => {
  try {
    // 加载综合能力分析 (雷达图)
    const overallResult = await AnalysisService.analyze('Overall');
    analysisResults.value['Overall'] = overallResult;
    if (overallResult.visualization) {
      skillsChartOption.value = createChartOption(overallResult.visualization);
    }

    // 加载词汇量趋势分析 (折线图)
    const vocabResult = await AnalysisService.analyze('Vocabulary');
    analysisResults.value['Vocabulary'] = vocabResult;
    if (vocabResult.visualization) {
      vocabChartOption.value = createChartOption(vocabResult.visualization);
    }
  } catch (e) {
    console.error('Failed to load analysis charts', e);
  }
};

// --- 计算属性：各 Tab 展示数据 ---

const overallInsights = computed(() => {
  const result = analysisResults.value['Overall'];
  return result?.insights || [];
});

const vocabInsights = computed(() => {
  const result = analysisResults.value['Vocabulary'];
  return result?.insights || [];
});

const overallScore = computed(() => {
  const result = analysisResults.value['Overall'];
  return result?.score ?? 0;
});

// --- 生命周期 ---

onMounted(async () => {
  try {
    isLoading.value = true;
    // 并行加载统计数据和图表数据
    const [statsData] = await Promise.all([
      AnalysisService.getStats(),
      loadAnalysis()
    ]);
    stats.value = statsData;
  } catch (e) {
    console.error('Failed to load stats', e);
  } finally {
    isLoading.value = false;
  }
});
</script>

<template>
  <div class="p-8 h-full overflow-y-auto">
    <div class="flex justify-between items-center mb-8">
      <h2 class="text-2xl font-bold text-white">学习分析</h2>
      <div class="flex space-x-2 bg-gray-800 p-1 rounded-lg">
        <button 
          v-for="tab in ['overview', 'vocabulary', 'progress']" 
          :key="tab"
          @click="activeTab = tab"
          class="px-4 py-2 rounded-md text-sm transition-colors capitalize"
          :class="activeTab === tab ? 'bg-indigo-600 text-white' : 'text-gray-400 hover:text-white'"
        >
          {{ tab === 'overview' ? '概览' : tab === 'vocabulary' ? '词汇' : '进度' }}
        </button>
      </div>
    </div>

    <!-- Tab: Overview -->
    <div v-if="activeTab === 'overview'">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">词汇记录</div>
          <div class="text-3xl font-bold text-white">{{ stats.vocabulary }} <span class="text-sm text-gray-500 font-normal">个</span></div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">作文批改</div>
          <div class="text-3xl font-bold text-white">{{ stats.essay }} <span class="text-sm text-gray-500 font-normal">篇</span></div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">语音对话</div>
          <div class="text-3xl font-bold text-white">{{ stats.dialogue }} <span class="text-sm text-gray-500 font-normal">次</span></div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">智能分析</div>
          <div class="text-3xl font-bold text-white">{{ stats.analysis }} <span class="text-sm text-gray-500 font-normal">次</span></div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700 h-80 flex items-center justify-center">
          <BaseChart v-if="vocabChartOption" :options="vocabChartOption" class="w-full h-full" />
          <div v-else class="text-gray-500">加载中...</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700 h-80 flex items-center justify-center">
          <BaseChart v-if="skillsChartOption" :options="skillsChartOption" class="w-full h-full" />
          <div v-else class="text-gray-500">加载中...</div>
        </div>
      </div>

      <!-- Insights -->
      <div v-if="overallInsights.length" class="mt-8 bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 class="text-lg font-semibold text-white mb-4">智能建议</h3>
        <ul class="space-y-2">
          <li v-for="(insight, idx) in overallInsights" :key="idx" class="text-gray-300 text-sm flex items-start">
            <span class="text-indigo-400 mr-2">•</span>
            {{ insight }}
          </li>
        </ul>
      </div>
    </div>

    <!-- Tab: Vocabulary -->
    <div v-else-if="activeTab === 'vocabulary'">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">累计查询词汇</div>
          <div class="text-4xl font-bold text-indigo-400">{{ stats.vocabulary }}</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">作文涉及词汇</div>
          <div class="text-4xl font-bold text-purple-400">{{ stats.essay * 12 }}</div>
          <div class="text-xs text-gray-500 mt-1">估算值（基于平均每篇 12 个新词）</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">词汇掌握度</div>
          <div class="text-4xl font-bold text-green-400">{{ Math.min(100, Math.round(overallScore * 10)) }}%</div>
        </div>
      </div>

      <div class="bg-gray-800 rounded-xl p-6 border border-gray-700 h-96 flex items-center justify-center mb-6">
        <BaseChart v-if="vocabChartOption" :options="vocabChartOption" class="w-full h-full" />
        <div v-else class="text-gray-500">加载中...</div>
      </div>

      <div v-if="vocabInsights.length" class="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 class="text-lg font-semibold text-white mb-4">词汇学习建议</h3>
        <ul class="space-y-2">
          <li v-for="(insight, idx) in vocabInsights" :key="idx" class="text-gray-300 text-sm flex items-start">
            <span class="text-indigo-400 mr-2">•</span>
            {{ insight }}
          </li>
        </ul>
      </div>
      <div v-else class="bg-gray-800 rounded-xl p-6 border border-gray-700 text-gray-400 text-sm">
        暂无词汇学习建议。多查询和复习词汇，系统会为你生成个性化建议。
      </div>
    </div>

    <!-- Tab: Progress -->
    <div v-else-if="activeTab === 'progress'">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">总学习活动</div>
          <div class="text-3xl font-bold text-white">{{ stats.vocabulary + stats.essay + stats.dialogue + stats.analysis }}</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">作文完成率</div>
          <div class="text-3xl font-bold text-white">{{ stats.essay > 0 ? '100%' : '0%' }}</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">语音活跃度</div>
          <div class="text-3xl font-bold text-white">{{ stats.dialogue }} 次</div>
        </div>
        <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <div class="text-gray-400 text-sm mb-2">分析参与度</div>
          <div class="text-3xl font-bold text-white">{{ stats.analysis }} 次</div>
        </div>
      </div>

      <div class="bg-gray-800 rounded-xl p-6 border border-gray-700 h-96 flex items-center justify-center mb-6">
        <BaseChart v-if="skillsChartOption" :options="skillsChartOption" class="w-full h-full" />
        <div v-else class="text-gray-500">加载中...</div>
      </div>

      <!-- 学习里程碑 -->
      <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <h3 class="text-lg font-semibold text-white mb-4">学习里程碑</h3>
        <div class="space-y-4">
          <div class="flex items-center">
            <div class="w-10 h-10 rounded-full flex items-center justify-center mr-4" :class="stats.vocabulary >= 10 ? 'bg-green-500/20 text-green-400' : 'bg-gray-700 text-gray-500'">
              {{ stats.vocabulary >= 10 ? '✓' : '○' }}
            </div>
            <div>
              <div class="text-white text-sm">词汇初学者</div>
              <div class="text-gray-500 text-xs">查询 10 个以上词汇</div>
            </div>
          </div>
          <div class="flex items-center">
            <div class="w-10 h-10 rounded-full flex items-center justify-center mr-4" :class="stats.essay >= 1 ? 'bg-green-500/20 text-green-400' : 'bg-gray-700 text-gray-500'">
              {{ stats.essay >= 1 ? '✓' : '○' }}
            </div>
            <div>
              <div class="text-white text-sm">作文新手</div>
              <div class="text-gray-500 text-xs">完成 1 篇作文批改</div>
            </div>
          </div>
          <div class="flex items-center">
            <div class="w-10 h-10 rounded-full flex items-center justify-center mr-4" :class="stats.dialogue >= 5 ? 'bg-green-500/20 text-green-400' : 'bg-gray-700 text-gray-500'">
              {{ stats.dialogue >= 5 ? '✓' : '○' }}
            </div>
            <div>
              <div class="text-white text-sm">对话达人</div>
              <div class="text-gray-500 text-xs">完成 5 次语音对话</div>
            </div>
          </div>
          <div class="flex items-center">
            <div class="w-10 h-10 rounded-full flex items-center justify-center mr-4" :class="stats.analysis >= 3 ? 'bg-green-500/20 text-green-400' : 'bg-gray-700 text-gray-500'">
              {{ stats.analysis >= 3 ? '✓' : '○' }}
            </div>
            <div>
              <div class="text-white text-sm">分析专家</div>
              <div class="text-gray-500 text-xs">进行 3 次学习分析</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
