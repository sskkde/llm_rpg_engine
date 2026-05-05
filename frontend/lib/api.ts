import type {
  TokenResponse, UserRegisterRequest, UserLoginRequest, User,
  SaveSlot, SaveSlotDetail, SaveSlotCreateRequest, SaveSlotUpdateRequest, ManualSaveRequest, ManualSaveResponse,
  GameSession, SessionSnapshot, LoadSessionResponse, AdventureLogEntry,
  TurnRequest, TurnResponse,
  SSEEventData,
  WorldState, WorldSummary, Chapter, Location, NPC, Quest,
  StartCombatRequest, StartCombatResponse, CombatSession, CombatActionRequest, SubmitActionResponse,
  EndCombatResponse, CombatEventsResponse,
  AdminWorld, AdminWorldDetail, AdminChapter, AdminLocation, AdminNPCTemplate,
  AdminItemTemplate, AdminQuestTemplate, AdminEventTemplate, AdminPromptTemplate,
  DebugSessionLogsResponse, DebugSessionStateResponse, DebugModelCallsResponse, DebugErrorsResponse,
  SystemSettings, SystemSettingsUpdateRequest,
} from '@/types/api';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

class APIError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = 'APIError';
  }
}

async function fetchWithAuth<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const token = localStorage.getItem('access_token');
  
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  const response = await fetch(`${API_BASE_URL}${url}`, {
    ...options,
    headers,
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new APIError(response.status, error.detail || 'Request failed');
  }
  
  if (response.status === 204) {
    return undefined as T;
  }
  
  return response.json();
}

// =============================================================================
// Authentication
// =============================================================================

export async function registerUser(data: UserRegisterRequest): Promise<TokenResponse> {
  return fetchWithAuth<TokenResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function loginUser(data: UserLoginRequest): Promise<TokenResponse> {
  return fetchWithAuth<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getCurrentUser(): Promise<User> {
  return fetchWithAuth<User>('/auth/me');
}

// =============================================================================
// Save Slots
// =============================================================================

export async function createSaveSlot(data: SaveSlotCreateRequest): Promise<SaveSlot> {
  return fetchWithAuth<SaveSlot>('/saves', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function listSaveSlots(): Promise<SaveSlot[]> {
  return fetchWithAuth<SaveSlot[]>('/saves');
}

export async function getSaveSlot(slotId: string): Promise<SaveSlotDetail> {
  return fetchWithAuth<SaveSlotDetail>(`/saves/${slotId}`);
}

export async function updateSaveSlot(slotId: string, data: SaveSlotUpdateRequest): Promise<SaveSlot> {
  return fetchWithAuth<SaveSlot>(`/saves/${slotId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteSaveSlot(slotId: string): Promise<void> {
  return fetchWithAuth<void>(`/saves/${slotId}`, {
    method: 'DELETE',
  });
}

export async function manualSave(data: ManualSaveRequest): Promise<ManualSaveResponse> {
  return fetchWithAuth<ManualSaveResponse>('/saves/manual-save', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// =============================================================================
// Sessions
// =============================================================================

export async function listSessions(): Promise<GameSession[]> {
  return fetchWithAuth<GameSession[]>('/sessions');
}

export async function getSessionSnapshot(sessionId: string): Promise<SessionSnapshot> {
  return fetchWithAuth<SessionSnapshot>(`/sessions/${sessionId}/snapshot`);
}

export async function loadSession(sessionId: string): Promise<LoadSessionResponse> {
  return fetchWithAuth<LoadSessionResponse>(`/sessions/${sessionId}/load`, {
    method: 'POST',
  });
}

export async function getAdventureLog(sessionId: string): Promise<AdventureLogEntry[]> {
  return fetchWithAuth<AdventureLogEntry[]>(`/sessions/${sessionId}/adventure-log`);
}

// =============================================================================
// Game
// =============================================================================

export async function executeTurn(sessionId: string, data: TurnRequest): Promise<TurnResponse> {
  return fetchWithAuth<TurnResponse>(`/game/sessions/${sessionId}/turn`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// =============================================================================
// Streaming
// =============================================================================

export interface TurnStreamHandle {
  abort(): void;
  events: AsyncIterable<SSEEventData>;
}

async function* parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  decoder: TextDecoder,
): AsyncGenerator<SSEEventData> {
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() || '';

      for (const chunk of chunks) {
        if (!chunk.trim()) continue;

        let eventType = '';
        const dataLines: string[] = [];

        for (const line of chunk.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            dataLines.push(line.slice(6));
          }
        }

        if (eventType && dataLines.length > 0) {
          try {
            const data = JSON.parse(dataLines.join('\n'));
            yield { event: eventType, ...data } as SSEEventData;
          } catch (err) {
            console.warn('Failed to parse SSE event', err);
          }
        }
      }
    }

    if (buffer.trim()) {
      let eventType = '';
      const dataLines: string[] = [];

      for (const line of buffer.split('\n')) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          dataLines.push(line.slice(6));
        }
      }

      if (eventType && dataLines.length > 0) {
        try {
          const data = JSON.parse(dataLines.join('\n'));
          yield { event: eventType, ...data } as SSEEventData;
        } catch (err) {
          console.warn('Failed to parse buffered SSE event', err);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function createTurnStream(
  sessionId: string,
  action: string,
  useMock: boolean = false,
): TurnStreamHandle {
  const controller = new AbortController();
  const endpoint = useMock
    ? `/streaming/sessions/${sessionId}/turn/mock`
    : `/streaming/sessions/${sessionId}/turn`;

  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const responsePromise = fetch(`${API_BASE_URL}${endpoint}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ action }),
    signal: controller.signal,
  });

  const events: AsyncIterable<SSEEventData> = {
    async *[Symbol.asyncIterator]() {
      let response: Response;
      try {
        response = await responsePromise;
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        throw err;
      }

      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: 'Stream request failed' }));
        throw new APIError(
          response.status,
          error.detail || 'Stream request failed',
        );
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      yield* parseSSEStream(reader, decoder);
    },
  };

  return {
    abort: () => controller.abort(),
    events,
  };
}

// =============================================================================
// World
// =============================================================================

export async function getWorldState(): Promise<WorldState> {
  return fetchWithAuth<WorldState>('/world/state');
}

export async function getWorldSummary(): Promise<WorldSummary> {
  return fetchWithAuth<WorldSummary>('/world/summary');
}

export async function getChapter(chapterId: string): Promise<Chapter> {
  return fetchWithAuth<Chapter>(`/world/chapters/${chapterId}`);
}

export async function getLocation(locationId: string): Promise<Location> {
  return fetchWithAuth<Location>(`/world/locations/${locationId}`);
}

export async function getNPC(npcId: string): Promise<NPC> {
  return fetchWithAuth<NPC>(`/world/npcs/${npcId}`);
}

export async function getQuest(questId: string): Promise<Quest> {
  return fetchWithAuth<Quest>(`/world/quests/${questId}`);
}

// =============================================================================
// Combat
// =============================================================================

export async function startCombat(data: StartCombatRequest): Promise<StartCombatResponse> {
  return fetchWithAuth<StartCombatResponse>('/combat/start', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getCombat(combatId: string): Promise<CombatSession> {
  return fetchWithAuth<CombatSession>(`/combat/${combatId}`);
}

export async function submitCombatAction(
  combatId: string, 
  data: CombatActionRequest
): Promise<SubmitActionResponse> {
  return fetchWithAuth<SubmitActionResponse>(`/combat/${combatId}/turn`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function endCombat(combatId: string): Promise<EndCombatResponse> {
  return fetchWithAuth<EndCombatResponse>(`/combat/${combatId}/end`, {
    method: 'POST',
  });
}

export async function getCombatEvents(combatId: string): Promise<CombatEventsResponse> {
  return fetchWithAuth<CombatEventsResponse>(`/combat/${combatId}/events`);
}

// =============================================================================
// Admin
// =============================================================================

export async function listWorlds(): Promise<AdminWorld[]> {
  return fetchWithAuth<AdminWorld[]>('/admin/worlds');
}

export async function getWorldDetail(worldId: string): Promise<AdminWorldDetail> {
  return fetchWithAuth<AdminWorldDetail>(`/admin/worlds/${worldId}`);
}

export async function updateWorld(worldId: string, data: Partial<AdminWorldDetail>): Promise<AdminWorldDetail> {
  return fetchWithAuth<AdminWorldDetail>(`/admin/worlds/${worldId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listChapters(): Promise<AdminChapter[]> {
  return fetchWithAuth<AdminChapter[]>('/admin/chapters');
}

export async function getChapterDetail(chapterId: string): Promise<AdminChapter> {
  return fetchWithAuth<AdminChapter>(`/admin/chapters/${chapterId}`);
}

export async function updateChapter(chapterId: string, data: Partial<AdminChapter>): Promise<AdminChapter> {
  return fetchWithAuth<AdminChapter>(`/admin/chapters/${chapterId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listLocations(): Promise<AdminLocation[]> {
  return fetchWithAuth<AdminLocation[]>('/admin/locations');
}

export async function getLocationDetail(locationId: string): Promise<AdminLocation> {
  return fetchWithAuth<AdminLocation>(`/admin/locations/${locationId}`);
}

export async function updateLocation(locationId: string, data: Partial<AdminLocation>): Promise<AdminLocation> {
  return fetchWithAuth<AdminLocation>(`/admin/locations/${locationId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listNPCTemplates(): Promise<AdminNPCTemplate[]> {
  return fetchWithAuth<AdminNPCTemplate[]>('/admin/npc-templates');
}

export async function getNPCTemplateDetail(npcId: string): Promise<AdminNPCTemplate> {
  return fetchWithAuth<AdminNPCTemplate>(`/admin/npc-templates/${npcId}`);
}

export async function updateNPCTemplate(npcId: string, data: Partial<AdminNPCTemplate>): Promise<AdminNPCTemplate> {
  return fetchWithAuth<AdminNPCTemplate>(`/admin/npc-templates/${npcId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listItemTemplates(): Promise<AdminItemTemplate[]> {
  return fetchWithAuth<AdminItemTemplate[]>('/admin/item-templates');
}

export async function getItemTemplateDetail(itemId: string): Promise<AdminItemTemplate> {
  return fetchWithAuth<AdminItemTemplate>(`/admin/item-templates/${itemId}`);
}

export async function updateItemTemplate(itemId: string, data: Partial<AdminItemTemplate>): Promise<AdminItemTemplate> {
  return fetchWithAuth<AdminItemTemplate>(`/admin/item-templates/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listQuestTemplates(): Promise<AdminQuestTemplate[]> {
  return fetchWithAuth<AdminQuestTemplate[]>('/admin/quest-templates');
}

export async function getQuestTemplateDetail(questId: string): Promise<AdminQuestTemplate> {
  return fetchWithAuth<AdminQuestTemplate>(`/admin/quest-templates/${questId}`);
}

export async function updateQuestTemplate(questId: string, data: Partial<AdminQuestTemplate>): Promise<AdminQuestTemplate> {
  return fetchWithAuth<AdminQuestTemplate>(`/admin/quest-templates/${questId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listEventTemplates(): Promise<AdminEventTemplate[]> {
  return fetchWithAuth<AdminEventTemplate[]>('/admin/event-templates');
}

export async function getEventTemplateDetail(eventId: string): Promise<AdminEventTemplate> {
  return fetchWithAuth<AdminEventTemplate>(`/admin/event-templates/${eventId}`);
}

export async function updateEventTemplate(eventId: string, data: Partial<AdminEventTemplate>): Promise<AdminEventTemplate> {
  return fetchWithAuth<AdminEventTemplate>(`/admin/event-templates/${eventId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function listPromptTemplates(): Promise<AdminPromptTemplate[]> {
  return fetchWithAuth<AdminPromptTemplate[]>('/admin/prompt-templates');
}

export async function getPromptTemplateDetail(templateId: string): Promise<AdminPromptTemplate> {
  return fetchWithAuth<AdminPromptTemplate>(`/admin/prompt-templates/${templateId}`);
}

export async function updatePromptTemplate(templateId: string, data: Partial<AdminPromptTemplate>): Promise<AdminPromptTemplate> {
  return fetchWithAuth<AdminPromptTemplate>(`/admin/prompt-templates/${templateId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// =============================================================================
// System Settings
// =============================================================================

export async function getSystemSettings(): Promise<SystemSettings> {
  return fetchWithAuth<SystemSettings>('/admin/system-settings');
}

export async function updateSystemSettings(data: SystemSettingsUpdateRequest): Promise<SystemSettings> {
  return fetchWithAuth<SystemSettings>('/admin/system-settings', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// =============================================================================
// Debug
// =============================================================================

export async function getDebugSessionLogs(sessionId: string): Promise<DebugSessionLogsResponse> {
  return fetchWithAuth<DebugSessionLogsResponse>(`/debug/sessions/${sessionId}/logs`);
}

export async function getDebugSessionState(sessionId: string): Promise<DebugSessionStateResponse> {
  return fetchWithAuth<DebugSessionStateResponse>(`/debug/sessions/${sessionId}/state`);
}

export async function getDebugModelCalls(): Promise<DebugModelCallsResponse> {
  return fetchWithAuth<DebugModelCallsResponse>('/debug/model-calls');
}

export async function getDebugErrors(): Promise<DebugErrorsResponse> {
  return fetchWithAuth<DebugErrorsResponse>('/debug/errors');
}

export { APIError };
