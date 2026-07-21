<script setup lang="ts">
import type { VocabularyResult } from '../types/vocabulary';

defineProps<{
  data: VocabularyResult;
}>();

const emit = defineEmits<{
  (e: 'lookup-recommendation', word: string): void;
}>();

const handleRecommendationClick = (word: string) => {
  const term = String(word || '').trim();
  if (!term) return;
  emit('lookup-recommendation', term);
};

const relationLabel = (type?: string | null) => {
  if (!type) return '';
  const labels: Record<string, string> = {
    synonym: '同义词',
    antonym: '反义词',
    cognate: '同根词',
    similar_form: '形近词',
    review_due: '待复习'
  };
  return labels[type] || type;
};
</script>

<template>
  <div class="text-gray-300 font-mono text-sm leading-relaxed whitespace-pre-wrap">
    <!-- Header -->
    <div class="mb-6 border-b border-gray-700 pb-4">
      <h1 class="text-3xl font-bold text-white mb-2">{{ data.word }}</h1>
      <div class="flex flex-wrap gap-3 text-indigo-300">
        <span v-if="data.phonetics">/{{ data.phonetics }}/</span>
        <span v-else-if="data.pronunciation">/{{ data.pronunciation }}/</span>
        
        <span v-if="data.pos && Array.isArray(data.pos)" class="italic">{{ data.pos.join(', ') }}</span>
        <span v-else-if="data.pos" class="italic">{{ data.pos }}</span>
      </div>
      <div
        v-if="data.cefrLevel || data.difficultyLevel || data.schoolStage || (data.examTags && data.examTags.length)"
        class="mt-4 flex flex-wrap items-center gap-2"
      >
        <span
          v-if="data.cefrLevel"
          class="px-2 py-1 rounded bg-indigo-900/40 border border-indigo-700 text-xs text-indigo-200"
        >
          CEFR: {{ data.cefrLevel }}
        </span>
        <span
          v-if="typeof data.difficultyLevel === 'number'"
          class="px-2 py-1 rounded bg-gray-800 border border-gray-700 text-xs text-gray-200"
        >
          难度级别: L{{ data.difficultyLevel }}
        </span>
        <span
          v-if="data.schoolStage"
          class="px-2 py-1 rounded bg-gray-800 border border-gray-700 text-xs text-gray-200"
        >
          学段: {{ data.schoolStage }}
        </span>
        <span
          v-for="tag in (data.examTags || [])"
          :key="tag"
          class="px-2 py-1 rounded bg-teal-900/30 border border-teal-700 text-xs text-teal-200"
        >
          {{ tag }}
        </span>
      </div>
    </div>

    <!-- Content Sections -->
    <div class="space-y-6">
      <!-- Definitions (Complex) -->
      <div v-if="data.definitions && data.definitions.length">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Definitions</h3>
        <div v-for="(def, i) in data.definitions" :key="i" class="mb-3 pl-4 border-l-2 border-gray-700">
          <p class="text-white mb-1">{{ i + 1 }}. {{ def.meaning }}</p>
          <p class="text-gray-500 italic text-xs">{{ def.example }}</p>
          <p v-if="(def as any).exampleTranslation" class="text-gray-400 text-xs mt-1">{{ (def as any).exampleTranslation }}</p>
        </div>
      </div>
      <!-- Definitions (Simple/Legacy) -->
      <div v-else-if="data.meaning">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Definition</h3>
        <div class="mb-3 pl-4 border-l-2 border-gray-700">
          <p class="text-white mb-1">{{ data.meaning }}</p>
        </div>
      </div>

      <!-- Examples (Simple/Legacy) -->
      <div v-if="data.examples && data.examples.length">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Examples</h3>
        <div v-for="(ex, i) in data.examples" :key="i" class="mb-2 pl-4 border-l-2 border-gray-700">
           <!-- Handle both string[] and object[] -->
          <p class="text-gray-300 italic text-sm">{{ typeof ex === 'string' ? ex : (ex.en || ex) }}</p>
        </div>
      </div>

      <!-- Forms -->
      <div v-if="data.forms">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Morphology</h3>
        <div class="grid grid-cols-2 gap-x-8 gap-y-2 pl-4 text-xs">
          <template v-if="data.forms.verb">
            <div><span class="text-gray-500">Past:</span> {{ data.forms.verb.past }}</div>
            <div><span class="text-gray-500">P.P.:</span> {{ data.forms.verb.past_participle }}</div>
          </template>
          <template v-if="data.forms.noun">
            <div><span class="text-gray-500">Plural:</span> {{ data.forms.noun.plural }}</div>
          </template>
          <template v-if="data.forms.adj">
            <div><span class="text-gray-500">Comp:</span> {{ data.forms.adj.comparative }}</div>
            <div><span class="text-gray-500">Super:</span> {{ data.forms.adj.superlative }}</div>
          </template>
        </div>
      </div>

      <!-- Roots & Affixes -->
      <div v-if="data.roots || (data.affixes && data.affixes.length)">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Etymology</h3>
        <div class="pl-4 space-y-3">
          <div v-if="data.roots">
            <p><span class="text-indigo-400">{{ data.roots.root }}</span> ({{ data.roots.origin }}): {{ data.roots.meaning }}</p>
            <div v-if="data.roots.cognates" class="mt-1 flex flex-wrap gap-2">
              <span v-for="cog in data.roots.cognates" :key="cog.word" class="bg-gray-800 px-2 py-0.5 rounded text-xs border border-gray-700">
                {{ cog.word }} <span class="text-gray-500">({{ cog.meaning }})</span>
              </span>
            </div>
          </div>
          <div v-if="data.affixes">
            <div v-for="aff in data.affixes" :key="aff.part" class="flex gap-2 text-xs">
              <span class="text-indigo-400 font-bold">{{ aff.part }}</span>
              <span class="text-gray-500">-></span>
              <span>{{ aff.meaning }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Synonyms -->
      <div v-if="data.synonyms && data.synonyms.length">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Synonyms</h3>
        <div class="pl-4 space-y-2">
          <div v-for="syn in data.synonyms" :key="syn.word" class="text-sm">
            <span class="text-indigo-300 font-bold">{{ syn.word }}</span>
            <span class="text-gray-500 mx-2">-</span>
            <span class="text-gray-300">{{ syn.meaning }}</span>
            <p class="text-xs text-gray-500 mt-0.5 ml-4 border-l border-gray-700 pl-2">{{ syn.distinction }}</p>
          </div>
        </div>
      </div>

      <!-- Phrases -->
      <div v-if="data.phrases && data.phrases.length">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Collocations</h3>
        <div class="pl-4 space-y-3">
          <div v-for="ph in data.phrases" :key="ph.phrase">
            <p class="text-indigo-200">{{ ph.phrase }}</p>
            <p class="text-xs text-gray-400">{{ ph.meaning }}</p>
            <p class="text-xs text-gray-500 italic mt-1">"{{ ph.example }}"</p>
          </div>
        </div>
      </div>

      <!-- Recommendations -->
      <div v-if="data.recommendations && data.recommendations.length">
        <h3 class="text-white font-bold mb-2 uppercase tracking-wider text-xs">Recommended Next Words</h3>
        <div class="pl-4 space-y-2">
          <div
            v-for="item in data.recommendations"
            :key="`${item.word}-${item.relation_type || 'none'}`"
            class="text-sm"
          >
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                class="text-indigo-300 font-bold hover:text-indigo-200 underline underline-offset-2"
                @click="handleRecommendationClick(item.word)"
              >
                {{ item.word }}
              </button>
              <span v-if="item.relation_type" class="text-[10px] px-2 py-0.5 rounded bg-gray-800 border border-gray-700 text-gray-400">
                {{ relationLabel(item.relation_type) }}
              </span>
              <span v-if="typeof item.score === 'number'" class="text-[10px] text-gray-500">
                score: {{ item.score.toFixed(2) }}
              </span>
            </div>
            <p v-if="item.reason" class="text-xs text-gray-500 mt-0.5 ml-1">
              {{ item.reason }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
