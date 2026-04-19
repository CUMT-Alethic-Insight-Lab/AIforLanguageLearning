export interface VocabularyResult {
  word: string;
  phonetics?: string;
  pos?: string[];
  forms?: {
    prototype?: string;
    verb?: { past?: string; past_participle?: string; pronunciation?: string };
    noun?: { singular?: string; plural?: string; note?: string };
    adj?: { comparative?: string; superlative?: string };
    adv?: string;
  };
  definitions: Array<{
    meaning: string;
    example: string;
  }>;
  roots?: {
    origin?: string;
    root?: string;
    meaning?: string;
    cognates?: Array<{ word: string; meaning: string; pos: string; note?: string }>;
  };
  affixes?: Array<{ part: string; meaning: string }>;
  synonyms?: Array<{ word: string; meaning: string; pronunciation?: string; distinction?: string }>;
  phrases?: Array<{ phrase: string; meaning: string; example?: string; mnemonic?: string }>;
  
  // Legacy fields for compatibility
  meaning?: string;
  pronunciation?: string;
  difficulty?: string;
  examples?: Array<{ en: string; zh: string }>;
  antonyms?: string[];
  etymology?: string;
  cefrLevel?: string;
  difficultyLevel?: number;
  examTags?: string[];
  schoolStage?: string;
  recommendations?: Array<{
    word: string;
    reason?: string;
    score?: number;
    relation_type?: string | null;
  }>;
}

export interface OCRResult {
  detectedText: string;
  explanation: VocabularyResult;
}
