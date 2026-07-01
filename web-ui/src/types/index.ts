export interface ActivityLabel {
  running: string;
  done: string;
}

// Tool call information
export interface ToolCallInfo {
  id: string;
  name: string;
  parameters: Record<string, any>;
  result?: string | null;
  error?: string | null;
  result_summary?: string | null;
  approved?: boolean | null;
  nested_tool_calls?: ToolCallInfo[] | null;
}

// Deep research section
export interface DeepResearchSection {
  category: string;
  subtopic: string;
  content: string;
}

// Taxonomy types
export interface TaxonomySubTopic {
  name: string;
  description: string;
  search_queries: string[];
  sections: any[];
}

export interface TaxonomyCategory {
  name: string;
  description: string;
  sub_topics: TaxonomySubTopic[];
}

export interface ResearchTaxonomy {
  taxonomy: TaxonomyCategory[];
  confidence: string;
  known_gaps: string[];
}

// Search result item from search_done event
export interface SearchResultItem {
  title: string;
  url: string;
  domain: string;
}

// Message types
export type DeepAnalyzePhase = 'explore' | 'load' | 'profile' | 'plan' | 'extract' | 'synthesize' | 'report';
export type DeepAnalyzePhaseStatus = 'pending' | 'running' | 'done';
export type DeepAnalyzeItemStatus = 'done' | 'failed';

export interface DeepAnalyzeSubtable {
  name: string;
  rows: number;
  status: DeepAnalyzeItemStatus;
  error?: string;
}


// Structured todo item (mirrors backend TodoHandler.to_payload())
export type TodoStatus = 'todo' | 'doing' | 'done';

export interface Todo {
  id: string;
  title: string;
  status: TodoStatus;
  active_form?: string;
}

export interface Message {
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'thinking' | 'search_result' | 'deep_research' | 'deep_analyze' | 'image_message' | 'data_message' | 'custom_block' | 'todos';
  // live todo list (role === 'todos')
  todos?: Todo[];
  // custom_block fields
  block_id?: string;
  block_module?: string;
  block_file?: string;
  block_src?: string;
  block_props?: Record<string, any>;
  block_height?: number | 'auto';
  block_title?: string;
  content: string;
  timestamp?: string;
  tool_call_id?: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  tool_result?: any;
  tool_args_display?: string | null;
  activity?: ActivityLabel | null;
  tool_summary?: string | string[] | null;
  tool_success?: boolean;
  tool_error?: string | null;
  tool_calls?: ToolCallInfo[];
  metadata?: Record<string, any>;
  depth?: number;
  parent_tool_call_id?: string;
  thinking_trace?: string | null;
  reasoning_content?: string | null;
  streaming?: boolean;
  // search_result fields
  search_query?: string;
  search_result_count?: number;
  search_results?: SearchResultItem[];
  search_provider?: string;
  // deep_research fields
  dr_job_id?: string;
  dr_topic?: string;
  dr_taxonomy?: ResearchTaxonomy;
  dr_progress?: number;
  dr_sections?: DeepResearchSection[];
  dr_active_section?: { category: string; subtopic: string };
  dr_status?: 'reviewing' | 'queued' | 'running' | 'done' | 'error';
  dr_error?: string;
  dr_review_request_id?: string;
  dr_report_path?: string;
  // deep_analyze fields
  da_job_id?: string;
  da_status?: 'running' | 'clarifying' | 'plan_reviewing' | 'done' | 'error' | 'cancelled';
  da_phases?: Partial<Record<DeepAnalyzePhase, DeepAnalyzePhaseStatus>>;
  da_load_rows?: number;
  da_load_cols?: number;
  da_plan_subtables?: number;
  da_plan_charts?: number;
  da_subtables?: DeepAnalyzeSubtable[];
  da_report_path?: string;
  da_error?: string;
  da_failed_phase?: string;
  da_plan?: {
    summary?: string;
    sections: Array<{
      name: string;
      key_question?: string;
      description?: string;
      chart_names: string[];
      analysis_angles?: string[];
    }>;
    charts: Array<{
      name: string;
      source_table: string;
      type: string;
      x: string;
      y: string[];
      title: string;
      insight?: string;
    }>;
    sub_tables: Array<{
      name: string;
      sql: string;
      why?: string;
    }>;
  };
  da_plan_review_request_id?: string;
  // EXPLORE-phase clarify Q&A
  da_clarify_request_id?: string;
  da_clarify_iteration?: number;
  da_clarify_questions?: Array<{
    id: string;
    text: string;
    kind: 'intent' | 'ambiguity';
    column?: string;
  }>;
  da_domain_brief?: string;
  // image_message fields
  image_src?: string;
  image_mime?: string;
  image_caption?: string;
  // data_message fields
  data_message_id?: string;
  data_title?: string;
  data_columns?: DataColumn[];
  data_rows?: Record<string, any>[];
  data_suggestions?: ChartSuggestion[];
  data_warning?: string;
  data_sql?: string;
  // lazy-load fallback: fetch rows via /api/analyze/table-data
  data_db_path?: string;
  data_table_name?: string;
  // pre-rendered chart image from the pipeline (live base64 from WS event)
  data_image_src?: string;
  // server-side PNG path: fetched via /api/analyze/chart-image on reload
  data_image_path?: string;
}

export interface ChartSuggestion {
  chart_type: 'bar' | 'line' | 'area' | 'pie' | 'doughnut' | 'scatter';
  x: string;
  y: string[];
  title?: string;
  reason?: string;
}

export type DataColumnType = 'number' | 'string' | 'date' | 'bool';
export interface DataColumn {
  name: string;
  type: DataColumnType;
}

// Session types
export interface Session {
  id: string;
  working_dir: string;  // Backend returns this key even though model has working_directory
  created_at: string;
  updated_at: string;
  message_count: number;
  token_usage: Record<string, number>;
  title?: string;
  has_session_model?: boolean;
}

// Configuration types
export interface Config {
  model: string;
  model_thinking?: string | null;
  model_vlm?: string | null;
  model_critique?: string | null;
  model_compact?: string | null;
  api_base_url?: string | null;
  api_key: string | null;
  temperature: number;
  enable_bash: boolean;
  working_directory: string;
}

// Parallel solver WS payload shapes
export interface ParallelSolverStartedData {
  job_id: string;
  n: number;
  task: string;
  worktree_names: string[];
  session_id: string;
}

export interface ParallelSolverProgressData {
  job_id: string;
  done: number;
  n: number;
  session_id: string;
}

export interface ParallelSolverCandidateData {
  thread: number;
  ok: boolean;
  summary: string;
}

export interface ParallelSolverDoneData {
  job_id: string;
  status: string;
  applied: boolean;
  winner_thread: number;
  reasoning: string;
  conflicted_files: string[];
  dropped_threads: number[];
  candidates: ParallelSolverCandidateData[];
  session_id: string;
}

// WebSocket event types
export interface WSMessage {
  type: 'user_message' | 'message_start' | 'message_chunk' | 'message_complete' | 'tool_call' | 'tool_result' | 'approval_required' | 'approval_resolved' | 'error' | 'pong' | 'mcp_status_update' | 'mcp_servers_update' | 'connected' | 'disconnected' | 'thinking_block' | 'thinking' | 'thinking_done' | 'search_done' | 'status_update' | 'ask_user_required' | 'ask_user_resolved' | 'session_activity' | 'plan_approval_required' | 'plan_approval_resolved' | 'plan_content' | 'subagent_start' | 'subagent_complete' | 'todos_updated' | 'parallel_agents_start' | 'parallel_agents_done' | 'parallel_solver_started' | 'parallel_solver_progress' | 'parallel_solver_done' | 'divide_job_started' | 'divide_task_update' | 'divide_job_done' | 'task_completed' | 'progress' | 'nested_tool_call' | 'nested_tool_result' | 'deep_research_taxonomy_ready' | 'deep_research_queued' | 'deep_research_start' | 'deep_research_section_start' | 'deep_research_section_done' | 'deep_research_done' | 'deep_research_error' | 'analyze.started' | 'analyze.phase' | 'analyze.subtable' | 'analyze.plan_ready' | 'analyze.clarify' | 'analyze.chart_data' | 'analyze.chart_image' | 'analyze.chart_insight' | 'analyze.section_synthesized' | 'analyze.report' | 'analyze.done' | 'analyze.failed' | 'analyze.cancelled' | 'analyze.agent_message' | 'image_message' | 'data_message' | 'custom_block' | 'custom_block_update' | 'custom_block_remove' | 'block_rpc_result' | 'session_messages_replaced' | 'blackboard.note';
  data: any;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, any>;
  requiresApproval: boolean;
}

export interface ApprovalRequest {
  id: string;
  tool_name: string;
  arguments: Record<string, any>;
  description: string;
  preview?: string;
}

// Status bar info
export interface StatusInfo {
  mode: 'normal' | 'plan';
  autonomy_level: 'Manual' | 'Semi-Auto' | 'Auto';
  thinking_level?: 'Off' | 'Low' | 'Medium' | 'High';
  model?: string;
  working_dir?: string;
  git_branch?: string | null;
  session_cost?: number;
  context_usage_pct?: number;
  simple_mode?: boolean;
}

// Ask-user question types
export interface AskUserOption {
  label: string;
  description: string;
}

export interface AskUserQuestion {
  question: string;
  header: string;
  options: AskUserOption[];
  multi_select: boolean;
}

export interface AskUserRequest {
  request_id: string;
  questions: AskUserQuestion[];
}

// Plan approval types
export interface PlanApprovalRequest {
  request_id: string;
  plan_content: string;
}

// ── Project workspace types ─────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  workspace_path: string;
  created_at: string | null;
  conversation_count: number;
}

export interface Conversation {
  id: string;
  name: string;
  project_id: string;
  working_directory: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: number;
  project_id: number | null;
  conversation_id: number | null;
  type: 'file' | 'code' | 'report' | 'image' | 'data';
  source_mode: string | null;
  title: string | null;
  pinned: boolean;
  payload_ref: string | null;
  preview: any | null;
  size?: number; // Actual file size in bytes
  created_at: string;
  updated_at: string | null;
}

// Per-session state for concurrent session support
export interface PerSessionState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  pendingApproval: ApprovalRequest | null;
  pendingAskUser: AskUserRequest | null;
  pendingPlanApproval: PlanApprovalRequest | null;
  progressMessage: string | null;
  queuedMessages: string[];
  selectedPersona?: string | null;
}

// ── Artifact Viewer ──────────────────────────────────────────────────────────
export interface FsEntry {
  name: string;
  kind: 'file' | 'dir';
  size: number;
  mtime: number;
  ext: string;
}

export interface FsListResponse {
  path: string;
  entries: FsEntry[];
}

export type ViewerTab =
  | {
      kind: 'file';
      id: string;       // === path
      path: string;     // relative to working_directory
      name: string;
      ext: string;
    }
  | {
      kind: 'module';
      id: string;       // === `module:<name>`
      name: string;     // module name
    }
  | {
      kind: 'module-file';
      id: string;       // === `module:<module>:<path>`
      module: string;
      path: string;     // relative to module folder
      name: string;
      ext: string;
    };

// File-tree / fs-API scope. Either a conversation working directory or a module folder.
export type FsScope =
  | { kind: 'conv'; id: number }
  | { kind: 'module'; name: string };

export function fsScopeKey(scope: FsScope): string {
  return scope.kind === 'conv' ? `conv:${scope.id}` : `module:${scope.name}`;
}

export interface Persona {
  name: string;
  system_prompt: string;
  is_built_in: boolean;
  created_at: string;
}
