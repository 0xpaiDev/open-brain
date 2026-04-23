/* API response types matching the FastAPI backend */

export interface PulseResponse {
  id: string;
  pulse_date: string;
  status: string;
  ai_question: string | null;
  ai_question_response: string | null;
  wake_time: string | null;
  sleep_quality: number | null;
  energy_level: number | null;
  notes: string | null;
  parsed_data: Record<string, unknown> | null;
  clean_meal: boolean | null;
  alcohol: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarEvent {
  title: string;
  start: string;
  end: string;
  location: string | null;
  calendar: string;
  all_day: boolean;
}

export interface CalendarTomorrowEvent {
  title: string;
  start: string;
  all_day: boolean;
}

export interface CalendarResponse {
  status: "ok" | "unavailable";
  date: string;
  fetched_at: string;
  events: CalendarEvent[];
  tomorrow_preview: CalendarTomorrowEvent[];
}

export interface TodoItem {
  id: string;
  description: string;
  priority: "high" | "normal" | "low";
  status: "open" | "done" | "cancelled";
  due_date: string | null;
  start_date: string | null;
  label: string | null;
  learning_item_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningItem {
  id: string;
  section_id: string;
  title: string;
  status: "pending" | "done";
  feedback: string | null;
  notes: string | null;
  position: number;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningSection {
  id: string;
  topic_id: string;
  name: string;
  position: number;
  items: LearningItem[];
}

export interface LearningTopic {
  id: string;
  name: string;
  description: string | null;
  depth: "foundational" | "deep";
  is_active: boolean;
  position: number;
  sections: LearningSection[];
}

export interface LearningTreeResponse {
  topics: LearningTopic[];
}

export interface TodoLabel {
  id: string;
  name: string;
  color: string;
  created_at: string;
}

export interface TodoListResponse {
  todos: TodoItem[];
  total: number;
}

export interface PulseUpdate {
  wake_time?: string;
  sleep_quality?: number;
  energy_level?: number;
  ai_question_response?: string;
  notes?: string;
  status?: string;
  clean_meal?: boolean;
  alcohol?: boolean;
}

export interface TodoCreate {
  description: string;
  priority?: "high" | "normal" | "low";
  due_date?: string;
  start_date?: string;
  label?: string;
}

export interface TodoUpdate {
  status?: "open" | "done" | "cancelled";
  priority?: "high" | "normal" | "low";
  due_date?: string | null;
  start_date?: string | null;
  description?: string;
  reason?: string;
  label?: string | null;
}

export interface MemoryItemResponse {
  id: string;
  raw_id: string;
  type: string;
  content: string;
  summary: string | null;
  base_importance: number | null;
  dynamic_importance: number | null;
  importance_score: number | null;
  is_superseded: boolean;
  supersedes_id: string | null;
  project: string | null;
  created_at: string;
}

export interface MemoryRecentResponse {
  items: MemoryItemResponse[];
  total: number;
}

export interface MemoryIngestResponse {
  raw_id: string;
  status: "queued" | "duplicate";
  supersedes_id: string | null;
}

export interface VoiceCommandResponse {
  action: "created" | "completed" | "memory" | "ambiguous";
  entity_id: string | null;
  title: string | null;
  confidence: number;
  message: string;
}

export interface SearchResultItem {
  id: string;
  content: string;
  summary: string | null;
  type: string;
  importance_score: number | null;
  combined_score: number;
  project: string | null;
}

export interface ProjectLabel {
  id: string;
  name: string;
  color: string;
  created_at: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResultItem[];
}

/* ── Chat types matching POST /v1/chat ──────────────────────────────────── */

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatSourceItem {
  id: string;
  content: string;
  summary: string | null;
  type: string;
  importance_score: number;
  combined_score: number;
  project: string | null;
}

export interface ChatRequest {
  message: string;
  history: ChatMessage[];
  model?: string | null;
  external_context?: string | null;
}

export interface ChatResponse {
  response: string;
  sources: ChatSourceItem[];
  model: string;
  search_query: string;
}

export interface ChatDisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSourceItem[];
  searchQuery?: string;
}

/* ── Operations Log types ─────────────────────────────────────────────── */

export interface JobRunItem {
  id: string;
  job_name: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  error_message: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface JobHistoryResponse {
  items: JobRunItem[];
  total: number;
}

export interface JobStatusInfo {
  last_run: string | null;
  last_status: string | null;
  duration_seconds: number | null;
  error: string | null;
  overdue: boolean;
  schedule: string;
}

export interface JobStatusResponse {
  jobs: Record<string, JobStatusInfo>;
  scheduler: { container: string; tip: string };
  checked_at: string;
}

export interface QueueStatusResponse {
  pending: number;
  processing: number;
  done: number;
  failed: number;
  total: number;
  oldest_locked_at: string | null;
}

export interface DeadLetterItem {
  id: string;
  raw_id: string;
  queue_id: string;
  error_reason: string;
  attempt_count: number;
  last_output: string | null;
  retry_count: number;
  created_at: string;
  resolved_at: string | null;
}

export interface DeadLetterListResponse {
  items: DeadLetterItem[];
  total: number;
}

/* ── Commitment types ────────────────────────────────────────────────── */

export interface CommitmentEntry {
  id: string;
  commitment_id: string;
  entry_date: string;
  logged_count: number;
  status: "pending" | "hit" | "miss";
  created_at: string;
  updated_at: string;
}

export interface CommitmentResponse {
  id: string;
  name: string;
  exercise: string;
  daily_target: number;
  metric: string;
  cadence: "daily" | "aggregate";
  targets: Record<string, number> | null;
  progress: Record<string, number> | null;
  pace: Record<string, number> | null;
  start_date: string;
  end_date: string;
  status: "active" | "completed" | "abandoned";
  created_at: string;
  updated_at: string;
  current_streak: number;
  goal_reached: boolean | null;
  entries: CommitmentEntry[];
}

export interface CommitmentListResponse {
  commitments: CommitmentResponse[];
  total: number;
}

export interface CommitmentCreate {
  name: string;
  exercise: string;
  daily_target: number;
  metric?: string;
  cadence?: "daily" | "aggregate";
  targets?: Record<string, number>;
  start_date: string;
  end_date: string;
}
