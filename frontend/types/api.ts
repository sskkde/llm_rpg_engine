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
// Debug Types
// =============================================================================

export interface DebugSessionLog {
  log_id: string;
  session_id: string;
  timestamp: string;
  log_type: string;
  message: string;
}

export interface DebugSessionLogsResponse {
  session_id: string;
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
  call_id: string;
  timestamp: string;
  prompt_template_id?: string;
  model_name: string;
  latency_ms: number;
  token_usage_input: number;
  token_usage_output: number;
  cost_estimate: number;
}

export interface DebugModelCallsResponse {
  calls: DebugModelCall[];
  total_cost: number;
}

export interface DebugError {
  error_id: string;
  timestamp: string;
  error_type: string;
  message: string;
  session_id?: string;
}

export interface DebugErrorsResponse {
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
