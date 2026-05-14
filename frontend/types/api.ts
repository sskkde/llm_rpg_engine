// API Type Definitions for LLM RPG Engine Frontend

// =============================================================================
// Authentication Types
// =============================================================================

export interface User {
  id: string;
  username: string;
  email?: string;
  is_admin: boolean;
  created_at: string;
  last_login_at?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface UserRegisterRequest {
  username: string;
  email?: string;
  password: string;
}

export interface UserLoginRequest {
  username: string;
  password: string;
}

// =============================================================================
// Save Slot Types
// =============================================================================

export interface SaveSlot {
  id: string;
  user_id: string;
  slot_number: number;
  name?: string;
  created_at: string;
  session_count: number;
}

export interface SessionSummary {
  id: string;
  world_id: string;
  status: string;
  started_at: string;
  last_played_at: string;
}

export interface SaveSlotDetail extends SaveSlot {
  sessions: SessionSummary[];
}

export interface SaveSlotCreateRequest {
  slot_number: number;
  name?: string;
}

export interface SaveSlotUpdateRequest {
  name?: string;
}

export interface ManualSaveRequest {
  world_id: string;
  save_slot_id?: string;
  current_chapter_id?: string;
}

export interface ManualSaveResponse {
  session_id: string;
  save_slot_id: string;
  message: string;
}

// =============================================================================
// Session Types
// =============================================================================

export interface GameSession {
  id: string;
  world_id: string;
  save_slot_id?: string;
  status: string;
  started_at: string;
  last_played_at: string;
}

export interface PlayerStateSnapshot {
  realm_stage: string;
  hp: number;
  max_hp: number;
  stamina: number;
  spirit_power: number;
  conditions: string[];
}

export interface SessionStateSnapshot {
  current_time?: string;
  time_phase?: string;
  active_mode: string;
  current_location_id?: string;
}

export interface SessionSnapshot {
  session_id: string;
  user_id: string;
  world_id: string;
  status: string;
  save_slot_id?: string;
  started_at: string;
  last_played_at: string;
  session_state?: SessionStateSnapshot;
  player_state?: PlayerStateSnapshot;
}

export interface LoadSessionResponse {
  session_id: string;
  world_id: string;
  message: string;
}

export interface AdventureLogEntry {
  id: string;
  turn_no: number;
  event_type: string;
  action?: string | null;
  narration: string;
  recommended_actions: string[];
  occurred_at: string;
}

// =============================================================================
// Game Turn Types
// =============================================================================

export interface TurnRequest {
  action: string;
  idempotency_key?: string;
}

export interface TurnResponse {
  turn_index: number;
  narration: string;
  recommended_actions: string[];
  world_time: {
    calendar?: string;
    season?: string;
    day?: number;
    period?: string;
  };
  player_state: {
    entity_id?: string;
    name?: string;
    location_id?: string;
    flags?: Record<string, unknown>;
  };
  events_committed: number;
  actions_committed: number;
  validation_passed: boolean;
  transaction_id: string;
}

// =============================================================================
// Streaming Types
// =============================================================================

export interface StreamTurnRequest {
  action: string;
}

export type SSEEventType = 
  | 'turn_started'
  | 'event_committed'
  | 'narration_delta'
  | 'turn_completed'
  | 'turn_error';

export interface TurnStartedEvent {
  event: 'turn_started';
  session_id: string;
  turn_index: number;
  player_input: string;
  timestamp: string;
}

export interface EventCommittedEvent {
  event: 'event_committed';
  session_id: string;
  turn_index: number;
  transaction_id: string;
  events_committed: number;
  actions_committed: number;
  world_time: {
    calendar?: string;
    season?: string;
    day?: number;
    period?: string;
  };
  timestamp: string;
}

export interface NarrationDeltaEvent {
  event: 'narration_delta';
  delta: string;
  turn_index: number;
}

export interface TurnCompletedEvent {
  event: 'turn_completed';
  session_id: string;
  turn_index: number;
  narration: string;
  recommended_actions?: string[];
  player_state: {
    entity_id?: string;
    name?: string;
    location_id?: string;
    flags?: Record<string, unknown>;
  };
  world_time: {
    calendar?: string;
    season?: string;
    day?: number;
    period?: string;
  };
  timestamp: string;
}

export interface TurnErrorEvent {
  event: 'turn_error';
  session_id: string;
  turn_index: number;
  error_type: string;
  message: string;
  errors?: string[];
  audit_event_id?: string;
  timestamp: string;
}

export type SSEEventData = 
  | TurnStartedEvent 
  | EventCommittedEvent 
  | NarrationDeltaEvent 
  | TurnCompletedEvent 
  | TurnErrorEvent;

// =============================================================================
// World Types
// =============================================================================

export interface WorldMetadata {
  id: string;
  code: string;
  name: string;
  genre?: string;
  lore_summary?: string;
  status: string;
}

export interface WorldState {
  world: WorldMetadata;
  chapters: Chapter[];
  locations: Location[];
  npcs: NPC[];
  items: Item[];
  quests: Quest[];
  endings: Array<{id: string; code: string; name: string; summary?: string}>;
  event_templates: Array<Record<string, unknown>>;
  prompt_templates: Array<Record<string, unknown>>;
}

export interface WorldSummary {
  worlds: number;
  chapters: number;
  locations: number;
  npcs: number;
  items: number;
  quests: number;
  events: number;
  prompts: number;
}

export interface Chapter {
  id: string;
  world_id: string;
  name: string;
  description?: string;
  sequence: number;
}

export interface Location {
  id: string;
  chapter_id: string;
  name: string;
  description?: string;
  access_rules?: Record<string, unknown>;
}

export interface NPC {
  id: string;
  name: string;
  description?: string;
  personality?: string;
  hidden_identity?: string;
}

export interface Quest {
  id: string;
  name: string;
  description?: string;
  quest_type: string;
}

export interface Item {
  id: string;
  code?: string;
  name: string;
  item_type?: string;
  rarity?: string;
  description?: string;
}

// =============================================================================
// Combat Types
// =============================================================================

export interface CombatParticipant {
  entity_id: string;
  name: string;
  hp: number;
  max_hp: number;
  is_player: boolean;
  is_defeated: boolean;
}

export interface CombatSession {
  id: string;
  session_id: string;
  status: 'active' | 'ended' | 'player_win' | 'player_loss';
  current_round: number;
  participants: CombatParticipant[];
}

export interface StartCombatRequest {
  session_id: string;
  enemy_ids: string[];
}

export interface StartCombatResponse {
  combat_id: string;
  session_id: string;
  current_round: number;
  message: string;
}

export interface CombatActionRequest {
  action_type: 'attack' | 'defend' | 'skill' | 'item' | 'flee';
  target_id?: string;
  skill_name?: string;
  item_id?: string;
}

export interface SubmitActionResponse {
  action_id: string;
  combat_id: string;
  action_type: string;
  result: string;
  damage_dealt?: number;
  healing_done?: number;
  round_complete: boolean;
}

export interface EndCombatResponse {
  combat_id: string;
  status: string;
  message: string;
}

export interface CombatEvent {
  event_id: string;
  combat_id: string;
  round: number;
  event_type: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface CombatEventsResponse {
  combat_id: string;
  events: CombatEvent[];
}

// =============================================================================
// Admin Types
// =============================================================================

export interface AdminWorld {
  id: string;
  name: string;
}

export interface AdminWorldDetail extends AdminWorld {
  description?: string;
  settings?: Record<string, unknown>;
}

export interface AdminChapter {
  id: string;
  world_id: string;
  name: string;
  sequence: number;
}

export interface AdminLocation {
  id: string;
  chapter_id: string;
  name: string;
}

export interface AdminNPCTemplate {
  id: string;
  name: string;
  personality?: string;
}

export interface AdminItemTemplate {
  id: string;
  name: string;
  rarity: string;
}

export interface AdminQuestTemplate {
  id: string;
  name: string;
  quest_type: string;
}

export interface AdminEventTemplate {
  id: string;
  name: string;
  trigger_type: string;
}

export interface AdminPromptTemplate {
  id: string;
  name: string;
  purpose: string;
}

// =============================================================================
// Media / Asset Types
// =============================================================================

export enum AssetType {
  PORTRAIT = 'portrait',
  SCENE = 'scene',
  BGM = 'bgm',
}

export enum AssetGenerationStatus {
  PENDING = 'pending',
  PROCESSING = 'processing',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled',
}

export interface AssetResponse {
  asset_id: string;
  asset_type: AssetType;
  generation_status: AssetGenerationStatus;
  result_url?: string;
  error_message?: string;
  provider?: string;
  cache_hit: boolean;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface PortraitGenerateRequest {
  npc_id: string;
  style?: string;
  expression?: string;
  session_id?: string;
  world_id?: string;
}

export interface SceneGenerateRequest {
  location_id: string;
  time_of_day?: string;
  weather?: string;
  session_id?: string;
  world_id?: string;
}

export interface BGMGenerateRequest {
  location_id?: string;
  mood: string;
  duration_seconds?: number;
  session_id?: string;
  world_id?: string;
}

// =============================================================================
// Debug Types
// =============================================================================

export interface DebugSessionLog {
  id: string;
  turn_no: number;
  event_type: string;
  input_text?: string;
  structured_action?: Record<string, unknown>;
  result_json?: Record<string, unknown>;
  narrative_text?: string;
  occurred_at: string;
}

export interface DebugSessionLogsResponse {
  session_id: string;
  total_count: number;
  logs: DebugSessionLog[];
}

export interface DebugSessionStateResponse {
  session_id: string;
  player_state?: Record<string, unknown>;
  npc_states?: Record<string, unknown>;
  inventory?: Record<string, unknown>;
  quests?: Record<string, unknown>;
}

export interface DebugModelCall {
  id: string;
  session_id: string;
  turn_no: number;
  provider?: string;
  model_name?: string;
  prompt_type?: string;
  prompt_template_id?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_estimate?: number;
  latency_ms?: number;
  created_at: string;
}

export interface DebugModelCallsResponse {
  total_count: number;
  total_cost: number;
  calls: DebugModelCall[];
}

export interface DebugError {
  timestamp: string;
  error_type: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface DebugErrorsResponse {
  total_count: number;
  errors: DebugError[];
}

// =============================================================================
// API Error Types
// =============================================================================

export interface APIError {
  status_code: number;
  detail: string | {
    message?: string;
    errors?: string[];
    warnings?: string[];
    audit_event_id?: string;
  };
}

// =============================================================================
// System Settings Types
// =============================================================================

export interface OpenAIKeyMetadata {
  configured: boolean;
  last4?: string;
  secret_updated_at?: string;
  secret_cleared_at?: string;
}

export interface LLMSettings {
  provider_mode: 'auto' | 'openai' | 'mock' | 'custom';
  default_model?: string;
  temperature: number;
  max_tokens: number;
  openai_api_key: OpenAIKeyMetadata;
  custom_base_url?: string | null;
  custom_api_key: OpenAIKeyMetadata;
}

export interface OpsSettings {
  registration_enabled: boolean;
  maintenance_mode: boolean;
  debug_enabled: boolean;
}

export interface SystemSettings {
  llm: LLMSettings;
  ops: OpsSettings;
  updated_at?: string;
  updated_by_user_id?: string;
}

export interface OpenAIKeyAction {
  action: 'keep' | 'set' | 'clear';
  value?: string;
}

export interface LLMSettingsUpdate {
  provider_mode?: 'auto' | 'openai' | 'mock' | 'custom';
  default_model?: string;
  temperature?: number;
  max_tokens?: number;
  openai_api_key?: OpenAIKeyAction;
  custom_base_url?: string | null;
  custom_api_key?: OpenAIKeyAction;
}

export interface OpsSettingsUpdate {
  registration_enabled?: boolean;
  maintenance_mode?: boolean;
  debug_enabled?: boolean;
}

export interface SystemSettingsUpdateRequest {
  llm?: LLMSettingsUpdate;
  ops?: OpsSettingsUpdate;
}

// =============================================================================
// Admin Content Types (Factions, PlotBeats, ContentPacks)
// =============================================================================

export interface FactionGoal {
  goal_id: string;
  description: string;
  priority?: number;
  status?: string;
}

export interface FactionRelationship {
  target_faction_id: string;
  relationship_type?: string;
  score?: number;
}

export interface FactionListItem {
  id: string;
  logical_id: string;
  world_id: string;
  name: string;
  visibility: string;
  status: string;
  created_at: string;
}

export interface FactionDetail extends FactionListItem {
  ideology: Record<string, unknown>;
  goals: FactionGoal[];
  relationships: FactionRelationship[];
}

export interface FactionCreateRequest {
  logical_id: string;
  world_id: string;
  name: string;
  ideology?: Record<string, unknown>;
  goals?: FactionGoal[];
  relationships?: FactionRelationship[];
  visibility?: string;
  status?: string;
}

export interface FactionUpdateRequest {
  name?: string;
  ideology?: Record<string, unknown>;
  goals?: FactionGoal[];
  relationships?: FactionRelationship[];
  visibility?: string;
  status?: string;
}

export interface PlotBeatCondition {
  type: string;
  params: Record<string, unknown>;
}

export interface PlotBeatEffect {
  type: string;
  params: Record<string, unknown>;
}

export interface PlotBeatListItem {
  id: string;
  logical_id: string;
  world_id: string;
  title: string;
  priority: number;
  visibility: string;
  status: string;
  created_at: string;
}

export interface PlotBeatDetail extends PlotBeatListItem {
  conditions: PlotBeatCondition[];
  effects: PlotBeatEffect[];
}

export interface PlotBeatCreateRequest {
  logical_id: string;
  world_id: string;
  title: string;
  conditions?: PlotBeatCondition[];
  effects?: PlotBeatEffect[];
  priority?: number;
  visibility?: string;
  status?: string;
}

export interface PlotBeatUpdateRequest {
  title?: string;
  conditions?: PlotBeatCondition[];
  effects?: PlotBeatEffect[];
  priority?: number;
  visibility?: string;
  status?: string;
}

export interface ContentPackValidationIssue {
  severity: string;
  message: string;
  path: string;
  code: string;
}

export interface ContentPackValidateResponse {
  is_valid: boolean;
  issues: ContentPackValidationIssue[];
  pack_id?: string;
  pack_name?: string;
}

export interface ContentPackImportResponse {
  success: boolean;
  imported_count: number;
  factions_imported: number;
  plot_beats_imported: number;
  errors: string[];
  warnings: string[];
  dry_run: boolean;
  pack_id?: string;
  pack_name?: string;
}

// =============================================================================
// Replay Types
// =============================================================================

export type ReplayPerspective = 'admin' | 'player' | 'auditor';

export interface ReplayEventResponse {
  event_id: string;
  event_type: string;
  turn_no: number;
  timestamp: string;
  actor_id: string;
  summary: string;
  visible_to_player: boolean;
  data: Record<string, unknown>;
}

export interface ReplayStepResponse {
  step_no: number;
  turn_no: number;
  player_input?: string | null;
  state_before: Record<string, unknown>;
  state_after: Record<string, unknown>;
  events: ReplayEventResponse[];
  state_deltas: Record<string, unknown>[];
  duration_ms?: number | null;
  timestamp: string;
}

export interface ReplayResultResponse {
  replay_id: string;
  session_id: string;
  start_turn: number;
  end_turn: number;
  perspective: string;
  steps: ReplayStepResponse[];
  final_state: Record<string, unknown>;
  total_steps: number;
  total_events: number;
  total_state_deltas: number;
  success: boolean;
  error_message?: string | null;
  started_at: string;
  completed_at?: string | null;
  replay_duration_ms?: number | null;
}

export interface SnapshotResponse {
  snapshot_id: string;
  session_id: string;
  turn_no: number;
  world_state: Record<string, unknown>;
  player_state: Record<string, unknown>;
  npc_states: Record<string, Record<string, unknown>>;
  location_states: Record<string, Record<string, unknown>>;
  quest_states: Record<string, Record<string, unknown>>;
  faction_states: Record<string, Record<string, unknown>>;
  created_at: string;
  snapshot_type: string;
}

export interface StateDiffEntryResponse {
  path: string;
  operation: string;
  old_value: unknown;
  new_value: unknown;
}

export interface StateDiffResponse {
  entries: StateDiffEntryResponse[];
  added_keys: string[];
  removed_keys: string[];
  changed_keys: string[];
}

export interface ReplayReportResponse {
  session_id: string;
  snapshot_id?: string | null;
  from_turn: number;
  to_turn: number;
  replayed_event_count: number;
  deterministic: boolean;
  llm_calls_made: number;
  state_diff: StateDiffResponse;
  warnings: string[];
  created_at: string;
}

// =============================================================================
// Prompt Inspector Types
// =============================================================================

export interface PromptTemplateUsageEntry {
  prompt_template_id: string;
  proposal_type: string;
  turn_no: number;
  model_name?: string;
  confidence?: number;
}

export interface PromptInspectorModelCallEntry {
  id: string;
  turn_no: number;
  prompt_type?: string;
  model_name?: string;
  provider?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_estimate?: number;
  latency_ms?: number;
  success: boolean;
  created_at: string;
}

export interface MemoryAuditResponse {
  memory_id: string;
  memory_type: string;
  owner_id: string;
  included: boolean;
  reason: string;
  relevance_score?: number;
  importance_score?: number;
  recency_score?: number;
  perspective_filter_applied: boolean;
  forbidden_knowledge_flag: boolean;
  notes?: string;
}

export interface PromptInspectorContextBuildEntry {
  build_id: string;
  turn_no: number;
  perspective_type: string;
  perspective_id: string;
  included_memories: MemoryAuditResponse[];
  excluded_memories: MemoryAuditResponse[];
  total_candidates: number;
  included_count: number;
  excluded_count: number;
  context_token_count: number;
  build_duration_ms: number;
}

export interface ValidationCheckResponse {
  check_id: string;
  check_type: string;
  status: string;
  message?: string;
  details: Record<string, unknown>;
}

export interface ProposalInspectorEntry {
  audit_id: string;
  turn_no: number;
  proposal_type: string;
  prompt_template_id?: string;
  model_name?: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  raw_output_preview: string;
  raw_output_hash?: string;
  parsed_proposal?: Record<string, unknown>;
  parse_success: boolean;
  repair_attempts: number;
  repair_strategies_tried: string[];
  repair_success: boolean;
  validation_passed: boolean;
  validation_errors: string[];
  validation_warnings: string[];
  rejected: boolean;
  rejection_reason?: string;
  fallback_used: boolean;
  fallback_reason?: string;
  fallback_strategy?: string;
  confidence: number;
  perspective_check_passed: boolean;
  forbidden_info_detected: string[];
}

export interface ValidationInspectorEntry {
  validation_id: string;
  turn_no: number;
  validation_target: string;
  overall_status: string;
  checks: ValidationCheckResponse[];
  error_count: number;
  warning_count: number;
  errors: string[];
  warnings: string[];
}

export interface PromptInspectorAggregates {
  total_tokens_used: number;
  total_cost: number;
  total_latency_ms: number;
  total_model_calls: number;
  call_success_rate: number;
  repair_success_rate: number;
}

export interface PromptInspectorResponse {
  session_id: string;
  total_turns: number;
  prompt_templates: PromptTemplateUsageEntry[];
  model_calls: PromptInspectorModelCallEntry[];
  context_builds: PromptInspectorContextBuildEntry[];
  proposals: ProposalInspectorEntry[];
  validations: ValidationInspectorEntry[];
  aggregates: PromptInspectorAggregates;
}

// =============================================================================
// Timeline and NPC Mind Debug Types
// =============================================================================

export interface TimelineTurn {
  turn_no: number;
  timestamp: string;
  event_type: string;
  npc_actions?: string[];
  narration_excerpt?: string;
}

export interface TimelineResponse {
  session_id: string;
  turns: TimelineTurn[];
  total_turns: number;
  has_more: boolean;
}

export interface TurnTimelineDetail {
  turn_no: number;
  timestamp: string;
  event_type: string;
  player_action?: string;
  narration: string;
  npc_actions: string[];
  events_committed: number;
  world_time?: {
    calendar?: string;
    season?: string;
    day?: number;
    period?: string;
  };
}

export interface SessionNPC {
  npc_id: string;
  name: string;
  location_id?: string;
}

export interface SessionNPCsResponse {
  session_id: string;
  npcs: SessionNPC[];
}

export interface NPCBelief {
  belief_id: string;
  content: string;
  confidence: number;
  source_turn?: number;
}

export interface NPCMemory {
  memory_id: string;
  content: string;
  strength: number;
  memory_type: string;
  created_turn: number;
}

export interface NPCSecret {
  secret_id: string;
  content: string;
  reveal_willingness: number;
  known_by: string[];
}

export interface NPCGoal {
  goal_id: string;
  description: string;
  priority: number;
  status: string;
}

export interface NPCForbiddenKnowledge {
  knowledge_id: string;
  content: string;
  source: string;
}

export interface NPCRelationshipMemory {
  target_entity_id: string;
  target_name: string;
  relationship_type: string;
  memories: string[];
  trust_score?: number;
}

export interface NPCMindResponse {
  session_id: string;
  npc_id: string;
  npc_name: string;
  viewer_role: 'admin' | 'auditor';
  beliefs: NPCBelief[];
  private_memories: NPCMemory[];
  secrets: NPCSecret[];
  goals: NPCGoal[];
  forbidden_knowledge: NPCForbiddenKnowledge[];
  relationship_memories: NPCRelationshipMemory[];
}

// =============================================================================
// Turn Debug and Context Build Audit Types
// =============================================================================

export interface TurnEventAuditEntry {
  event_id: string;
  event_type: string;
  actor_id?: string;
  summary?: string;
}

export interface StateDeltaAuditEntry {
  delta_id: string;
  path: string;
  old_value: unknown;
  new_value: unknown;
  operation: string;
  validated: boolean;
}

export interface LLMStageEvidence {
  stage_name: string;
  enabled: boolean;
  timeout: number;
  accepted: boolean;
  fallback_reason?: string;
  validation_errors: string[];
  model_call_id?: string;
}

export interface ContextHashEntry {
  build_id: string;
  context_hash: string;
}

export interface ModelCallReference {
  id: string;
  prompt_type?: string;
  model_name?: string;
  provider?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost_estimate?: number;
  latency_ms?: number;
}

export interface TurnDebugResponse {
  audit_id: string;
  session_id: string;
  turn_no: number;
  transaction_id: string;
  player_input: string;
  parsed_intent?: Record<string, unknown>;
  world_time_before: Record<string, unknown>;
  world_time_after?: Record<string, unknown>;
  events: TurnEventAuditEntry[];
  state_deltas: StateDeltaAuditEntry[];
  context_build_ids: string[];
  model_call_ids: string[];
  validation_ids: string[];
  status: string;
  narration_generated: boolean;
  narration_length: number;
  turn_duration_ms?: number;
  started_at: string;
  completed_at?: string;
  llm_stages: LLMStageEvidence[];
  fallback_reasons: string[];
  prompt_template_ids: string[];
  context_hashes: ContextHashEntry[];
  model_call_references: ModelCallReference[];
}

export interface ContextBuildAuditResponse {
  build_id: string;
  session_id: string;
  turn_no: number;
  perspective_type: string;
  perspective_id: string;
  owner_id?: string;
  included_memories: MemoryAuditResponse[];
  excluded_memories: MemoryAuditResponse[];
  total_candidates: number;
  included_count: number;
  excluded_count: number;
  context_token_count: number;
  context_char_count: number;
  build_duration_ms: number;
  created_at: string;
}

// =============================================================================
// Validation Audit Types
// =============================================================================

export interface ValidationResultAuditResponse {
  validation_id: string;
  session_id: string;
  turn_no: number;
  validation_target: string;
  target_id?: string;
  overall_status: 'passed' | 'failed' | 'warning';
  checks: ValidationCheckResponse[];
  error_count: number;
  warning_count: number;
  errors: string[];
  warnings: string[];
  transaction_id?: string;
  created_at: string;
}
