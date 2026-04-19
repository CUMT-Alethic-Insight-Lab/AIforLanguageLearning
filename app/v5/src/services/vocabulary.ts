/**
 * @fileoverview 词汇服务模块 (Vocabulary Service)
 * @description 提供词汇查询相关的业务功能，包括文本查词和 OCR 图片查词。
 *              负责调用后端 API 并对返回的数据进行适配和类型转换。
 */

import api from './api';
import { AuthService } from './auth';
import type { VocabularyResult } from '../types/vocabulary';

type LookupRecommendation = {
  word: string;
  reason?: string;
  score?: number;
  relation_type?: string | null;
};

type LookupDefinition = {
  meaning?: string;
  example?: string;
  example_translation?: string;
};

type NormalizedDefinition = {
  meaning: string;
  example: string;
  exampleTranslation?: string;
};

function getCurrentUserId(): number | undefined {
  try {
    const raw = localStorage.getItem('auth_user');
    if (!raw) return undefined;
    const user = JSON.parse(raw) as { id?: number | string };
    const id = Number(user?.id);
    if (!Number.isFinite(id) || id <= 0) return undefined;
    return id;
  } catch {
    return undefined;
  }
}

function getLookupSessionId(userId?: number): string {
  const key = 'vocab_lookup_session_id';
  const fallback = userId ? `user-${userId}` : 'guest';
  try {
    const existing = String(localStorage.getItem(key) || '').trim();
    if (existing) return existing;
    const next = `v5-${fallback}`;
    localStorage.setItem(key, next);
    return next;
  } catch {
    return `v5-${fallback}`;
  }
}

function parseLegacyDefinition(definition: string): { meaning: string; example: string } {
  const lines = String(definition || '')
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);

  if (lines.length === 0) return { meaning: '', example: '' };
  if (lines.length === 1) return { meaning: lines[0], example: '' };
  return { meaning: lines[0], example: lines[1] };
}

function tryParseJsonPayload(value: unknown): unknown | undefined {
  if (typeof value !== 'string') return undefined;
  let raw = value.trim();
  if (!raw) return undefined;

  for (let i = 0; i < 3; i += 1) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (typeof parsed === 'string') {
        raw = parsed.trim();
        if (!raw) return undefined;
        continue;
      }
      return parsed;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

function normalizeDefinitions(defs?: unknown): NormalizedDefinition[] {
  const out: NormalizedDefinition[] = [];
  const seen = new Set<string>();
  const queue: unknown[] = [defs];

  while (queue.length > 0) {
    const item = queue.shift();
    if (item == null) continue;

    const parsed = tryParseJsonPayload(item);
    if (parsed !== undefined) {
      queue.push(parsed);
      continue;
    }

    if (Array.isArray(item)) {
      queue.push(...item);
      continue;
    }

    if (typeof item !== 'object') continue;

    const row = item as Record<string, unknown>;
    if (row.definitions != null) {
      queue.push(row.definitions);
    }

    const meaning = String(row.meaning ?? '').trim();
    const example = String(row.example ?? '').trim();
    const exampleTranslation = String(row.example_translation ?? row.exampleTranslation ?? '').trim();

    const nestedFromMeaning = tryParseJsonPayload(meaning);
    if (nestedFromMeaning !== undefined && !example && !exampleTranslation) {
      queue.push(nestedFromMeaning);
      continue;
    }

    if (!meaning && !example && !exampleTranslation) continue;

    const key = `${meaning}__${example}__${exampleTranslation}`;
    if (seen.has(key)) continue;
    seen.add(key);

    out.push({
      meaning: meaning || '暂无',
      example,
      exampleTranslation: exampleTranslation || undefined,
    });
  }

  return out;
}

function cleanLookupText(value: string): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const parsed = tryParseJsonPayload(text);
  if (parsed !== undefined) return '';
  return text;
}

function toVocabularyResult(params: {
  word: string;
  meaning?: string;
  example?: string;
  exampleTranslation?: string;
  definition?: string;
  definitions?: LookupDefinition[];
  recommendations?: LookupRecommendation[];
  cefrLevel?: string;
  difficultyLevel?: number;
  examTags?: string[];
  schoolStage?: string;
}): VocabularyResult {
  let meaning = cleanLookupText(String(params.meaning || ''));
  let example = cleanLookupText(String(params.example || ''));
  let exampleTranslation = cleanLookupText(String(params.exampleTranslation || ''));

  const normalizedDefinitions = normalizeDefinitions(params.definitions);
  if (normalizedDefinitions.length > 0) {
    meaning = meaning || normalizedDefinitions[0].meaning;
    example = example || normalizedDefinitions[0].example;
    exampleTranslation = exampleTranslation || String(normalizedDefinitions[0].exampleTranslation || '');
  } else if (!meaning || !example) {
    const parsed = parseLegacyDefinition(String(params.definition || ''));
    meaning = meaning || parsed.meaning;
    example = example || parsed.example;
  }

  const result: VocabularyResult = {
    word: params.word,
    definitions:
      normalizedDefinitions.length > 0
        ? normalizedDefinitions.map((x) => ({ meaning: x.meaning, example: x.example }))
        : [{ meaning: meaning || '暂无', example: example || '' }],
    meaning: meaning || '暂无',
  };

  if (exampleTranslation) {
    result.examples = [{ en: example || '', zh: exampleTranslation }];
  }

  if (Array.isArray(params.recommendations) && params.recommendations.length > 0) {
    result.recommendations = params.recommendations;
  }
  if (String(params.cefrLevel || '').trim()) {
    result.cefrLevel = String(params.cefrLevel || '').trim();
  }
  if (typeof params.difficultyLevel === 'number') {
    result.difficultyLevel = params.difficultyLevel;
  }
  if (Array.isArray(params.examTags) && params.examTags.length > 0) {
    result.examTags = params.examTags.map((x) => String(x || '').trim()).filter(Boolean);
  }
  if (String(params.schoolStage || '').trim()) {
    result.schoolStage = String(params.schoolStage || '').trim();
  }

  return result;
}

export const VocabularyService = {
  /**
   * 词汇查询 (Text Lookup)
   * 
   * 调用后端 LLM 服务查询指定单词的详细释义、例句、发音等信息。
   * 
   * @param {string} word - 待查询的单词或短语
   * @returns {Promise<VocabularyResult>} 查询结果对象
   * @throws {Error} 如果查询失败或后端返回错误信息
   */
  async query(word: string): Promise<VocabularyResult> {
    await AuthService.ensureLogin();

    const userId = getCurrentUserId();
    const sessionId = getLookupSessionId(userId);
    const response = await api.post('/v1/vocab/lookup', {
      term: word,
      source: 'manual',
      user_id: userId,
      session_id: sessionId,
    });

    const result = response as unknown as {
      term: string;
      definition: string;
      meaning?: string;
      example?: string;
      example_translation?: string;
      definitions?: LookupDefinition[];
      recommendations?: LookupRecommendation[];
      cefr_level?: string;
      difficulty_level?: number;
      exam_tags?: string[];
      school_stage?: string;
    };
    return toVocabularyResult({
      word: String(result.term || word),
      definition: String(result.definition || ''),
      meaning: String(result.meaning || ''),
      example: String(result.example || ''),
      exampleTranslation: String(result.example_translation || ''),
      definitions: result.definitions || [],
      recommendations: result.recommendations || [],
      cefrLevel: String(result.cefr_level || ''),
      difficultyLevel: Number(result.difficulty_level || 0) || undefined,
      examTags: Array.isArray(result.exam_tags) ? result.exam_tags : [],
      schoolStage: String(result.school_stage || ''),
    });
  },

  /**
   * OCR 图片查词 (Image Lookup)
   * 
   * 上传图片 Base64 数据，后端进行 OCR 文字识别并查询识别到的单词释义。
   * 
   * @param {string} imageBase64 - 图片的 Base64 字符串 (可包含或不包含 data URI 前缀)
   * @returns {Promise<VocabularyResult>} 查询结果对象
   * @throws {Error} 如果 OCR 识别失败或查询出错
   */
  async queryOCR(imageBase64: string): Promise<VocabularyResult> {
    const cleanBase64 = imageBase64.includes(',') ? imageBase64.split(',')[1] : imageBase64;

    const userId = getCurrentUserId();
    const sessionId = getLookupSessionId(userId);
    const response = await api.post(
      '/v1/vocab/lookup-ocr',
      { image: cleanBase64, language: 'english', user_id: userId, session_id: sessionId },
      { timeout: 60000 }
    );
    const result = response as unknown as {
      term: string;
      ocr_text: string;
      meaning: string;
      example: string;
      example_translation?: string;
      recommendations?: LookupRecommendation[];
      cefr_level?: string;
      difficulty_level?: number;
      exam_tags?: string[];
      school_stage?: string;
    };
    return toVocabularyResult({
      word: String(result.term || ''),
      meaning: String(result.meaning || ''),
      example: String(result.example || ''),
      exampleTranslation: String(result.example_translation || ''),
      recommendations: result.recommendations || [],
      cefrLevel: String(result.cefr_level || ''),
      difficultyLevel: Number(result.difficulty_level || 0) || undefined,
      examTags: Array.isArray(result.exam_tags) ? result.exam_tags : [],
      schoolStage: String(result.school_stage || ''),
    });
  }
};
