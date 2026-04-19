import api from './api';

export interface ChartData {
  type: 'radar' | 'line' | 'bar' | 'pie' | 'scatter';
  title: string;
  labels: string[];
  datasets: Array<{
    label: string;
    data: number[];
  }>;
}

export interface DimensionTimePoint {
  date: string;
  vocab_growth_rate: number | null;
  sm2_retention_rate: number | null;
  active_lookup_conversion: number | null;
  morph_transfer_ability: number | null;
  long_term_memory_robustness: number | null;
  grammar_error_decay_slope: number | null;
  advanced_vocab_substitution: number | null;
  msl_diversity_index: number | null;
  logical_coherence_trend: number | null;
  semantic_accuracy_trend: number | null;
  response_latency_avg_ms: number | null;
  speech_wpm: number | null;
  difficulty_jump_success: number | null;
  cross_cultural_deviation: number | null;
  paraphrase_count: number | null;
  learning_stability_std: number | null;
  error_regression_rate: number | null;
  feedback_response_depth: number | null;
  topic_coverage_breadth: number | null;
  autonomous_drive_count: number | null;
}

export interface StudentProfile {
  user_id: number;
  username: string | null;
  profile: {
    class_id?: string | null;
    level?: string | null;
    goals?: string[];
    interests?: string[];
  } | null;
  time_series: DimensionTimePoint[];
  latest_summary: (Partial<DimensionTimePoint> & {
    date?: string;
    class_id?: string | null;
    level?: string | null;
    goals?: string[];
    interests?: string[];
    llm_narrative?: string | null;
    metric_methodology?: Record<string, { mode: string; reason: string }>;
    llm_used_for?: string[];
    topics?: string[];
  }) | null;
  llm_narrative: string | null;
  longitudinal_summary: {
    window_start: string;
    window_end: string;
    window_days: number;
    llm_summary: string;
    risk_flags: string[];
    strength_flags: string[];
    metric_deltas: Record<string, unknown>;
    evidence: Array<Record<string, unknown>>;
  } | null;
  charts: {
    radar_20d?: ChartData;
    trend_lines?: ChartData[];
    focus_bar?: ChartData;
  };
  analysis_methodology?: Record<string, { mode: string; reason: string }>;
  data_quality?: Record<string, unknown>;
}

export interface AgentReport {
  agent_type: string;
  insights: string[];
  suggestions: string[];
  risk_flags: string[][];
  evidence?: Array<Record<string, unknown>>;
  intervention_tasks: InterventionTaskItem[];
}

export interface StudentReport {
  user_id: number;
  date: string;
  agent_reports: AgentReport[];
}

export interface StudentListItem {
  user_id: number;
  username: string | null;
  risk_tags: string[];
  latest_score: number | null;
  last_active_date: string | null;
  class_id?: string | null;
}

export interface ClassOverview {
  class_id: string;
  date: string;
  total_students: number;
  active_students: number;
  risk_count: number;
  avg_vocab_growth: number | null;
  avg_grammar_decay: number | null;
  ability_distribution: {
    bottom: number;
    middle: number;
    top: number;
  };
  trend_7d: {
    vocab_growth_avg: number | null;
    grammar_decay_avg: number | null;
    data_points: number;
    common_error_index?: number | null;
  };
  recent_analysis?: {
    window_start?: string | null;
    window_end?: string | null;
    content: string;
    evidence: Array<Record<string, unknown>>;
  } | null;
  charts: {
    ability_pie?: ChartData;
    trend_line?: ChartData;
    class_radar?: ChartData;
    risk_bar?: ChartData;
  };
}

export interface InterventionTaskItem {
  title: string;
  description: string;
  priority: string;
  status: string;
  due_date: string | null;
}

export interface InterventionTask {
  id: number;
  student_id: number;
  class_id: string | null;
  agent_type: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  due_date: string | null;
  created_at: string;
}

export interface CreateInterventionRequest {
  student_id: number;
  class_id?: string;
  title: string;
  description?: string;
  suggestion?: Record<string, any>;
  priority?: string;
  due_date?: string;
}

export interface WeeklyReport {
  class_id: string;
  week_start: string;
  content: string;
  generated_at: string;
  evidence: Array<Record<string, unknown>>;
}

export interface ClassDashboard {
  class_id: string;
  overview: ClassOverview;
  students: StudentListItem[];
  weekly: WeeklyReport | null;
}

export interface StudentDashboard {
  student_id: number;
  profile: StudentProfile;
  report: StudentReport;
}

export interface StudentClassAssignmentItem {
  user_id: number;
  username: string | null;
  role: string;
  class_id: string | null;
  latest_summary_class_id: string | null;
  latest_score: number | null;
  risk_tags: string[];
  last_active_date: string | null;
  level?: string | null;
}

export interface UpdateStudentClassAssignmentRequest {
  class_id?: string | null;
  note?: string;
  sync_related_records?: boolean;
}

export interface StudentClassAssignmentUpdateResult {
  user_id: number;
  username: string | null;
  previous_class_id: string | null;
  class_id: string | null;
  changed: boolean;
  sync_stats: Record<string, number>;
}

export const TeacherAnalyticsService = {
  async getClassDashboard(
    class_id: string,
    target_date?: string,
    recent_days = 3,
    include_weekly = false,
  ): Promise<ClassDashboard> {
    const params: Record<string, string | number | boolean> = { recent_days, include_weekly };
    if (target_date) params.target_date = target_date;
    const response = await api.get<ClassDashboard>(`/api/v1/analytics/class/${class_id}/dashboard`, { params });
    return response as unknown as ClassDashboard;
  },

  async getClassOverview(class_id: string, target_date?: string, recent_days = 3): Promise<ClassOverview> {
    const params: Record<string, string | number> = { recent_days };
    if (target_date) params.target_date = target_date;
    const response = await api.get<ClassOverview>(`/api/v1/analytics/class/${class_id}/overview`, { params });
    return response as unknown as ClassOverview;
  },

  async getClassStudents(class_id: string, target_date?: string): Promise<StudentListItem[]> {
    const params = target_date ? { target_date } : {};
    const response = await api.get<StudentListItem[]>(`/api/v1/analytics/class/${class_id}/students`, { params });
    return response as unknown as StudentListItem[];
  },

  async getStudentProfile(student_id: number, days?: number, target_date?: string): Promise<StudentProfile> {
    const params: Record<string, string | number> = {};
    if (days) params.days = days;
    if (target_date) params.target_date = target_date;
    const response = await api.get<StudentProfile>(`/api/v1/analytics/student/${student_id}/profile`, { params });
    return response as unknown as StudentProfile;
  },

  async getStudentDashboard(
    student_id: number,
    days?: number,
    target_date?: string,
    llm_enhance = false,
  ): Promise<StudentDashboard> {
    const params: Record<string, string | number | boolean> = { llm_enhance };
    if (days) params.days = days;
    if (target_date) params.target_date = target_date;
    const response = await api.get<StudentDashboard>(`/api/v1/analytics/student/${student_id}/dashboard`, { params });
    return response as unknown as StudentDashboard;
  },

  async getStudentReport(student_id: number, target_date?: string): Promise<StudentReport> {
    const params = target_date ? { target_date } : {};
    const response = await api.get<StudentReport>(`/api/v1/analytics/student/${student_id}/report`, { params });
    return response as unknown as StudentReport;
  },

  async regenerateStudentLongitudinalSummary(student_id: number, days?: number, target_date?: string): Promise<Record<string, unknown>> {
    const params: Record<string, string | number> = {};
    if (days) params.days = days;
    if (target_date) params.target_date = target_date;
    const response = await api.post<Record<string, unknown>>(`/api/v1/analytics/student/${student_id}/llm-profile`, undefined, { params });
    return response as unknown as Record<string, unknown>;
  },

  async createIntervention(req: CreateInterventionRequest): Promise<InterventionTask> {
    const response = await api.post<InterventionTask>('/api/v1/analytics/intervention', req);
    return response as unknown as InterventionTask;
  },

  async getIntervention(task_id: number): Promise<InterventionTask> {
    const response = await api.get<InterventionTask>(`/api/v1/analytics/intervention/${task_id}`);
    return response as unknown as InterventionTask;
  },

  async getWeeklyReport(class_id: string, week_start?: string): Promise<WeeklyReport> {
    const params = week_start ? { week_start } : {};
    const response = await api.get<WeeklyReport>(`/api/v1/analytics/class/${class_id}/weekly`, { params });
    return response as unknown as WeeklyReport;
  },

  async listStudentClassAssignments(
    class_id?: string,
    include_unassigned = false,
    limit = 200,
  ): Promise<StudentClassAssignmentItem[]> {
    const params: Record<string, string | number | boolean> = { include_unassigned, limit };
    if (class_id) params.class_id = class_id;
    const response = await api.get<StudentClassAssignmentItem[]>('/api/v1/analytics/class-assignments', { params });
    return response as unknown as StudentClassAssignmentItem[];
  },

  async updateStudentClassAssignment(
    student_id: number,
    req: UpdateStudentClassAssignmentRequest,
  ): Promise<StudentClassAssignmentUpdateResult> {
    const response = await api.post<StudentClassAssignmentUpdateResult>(
      `/api/v1/analytics/student/${student_id}/class-assignment`,
      req,
    );
    return response as unknown as StudentClassAssignmentUpdateResult;
  },
};
