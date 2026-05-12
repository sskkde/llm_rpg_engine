import type {
  FactionListItem,
  FactionDetail,
  FactionCreateRequest,
  FactionUpdateRequest,
  PlotBeatListItem,
  PlotBeatDetail,
  PlotBeatCreateRequest,
  PlotBeatUpdateRequest,
  ContentPackValidateResponse,
  ContentPackImportResponse,
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
// Factions
// =============================================================================

export async function getFactions(worldId?: string): Promise<FactionListItem[]> {
  const params = worldId ? `?world_id=${encodeURIComponent(worldId)}` : '';
  return fetchWithAuth<FactionListItem[]>(`/admin/factions${params}`);
}

export async function getFaction(factionId: string): Promise<FactionDetail> {
  return fetchWithAuth<FactionDetail>(`/admin/factions/${factionId}`);
}

export async function createFaction(data: FactionCreateRequest): Promise<FactionDetail> {
  return fetchWithAuth<FactionDetail>('/admin/factions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateFaction(factionId: string, data: FactionUpdateRequest): Promise<FactionDetail> {
  return fetchWithAuth<FactionDetail>(`/admin/factions/${factionId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteFaction(factionId: string): Promise<void> {
  return fetchWithAuth<void>(`/admin/factions/${factionId}`, {
    method: 'DELETE',
  });
}

// =============================================================================
// Plot Beats
// =============================================================================

export async function getPlotBeats(worldId?: string): Promise<PlotBeatListItem[]> {
  const params = worldId ? `?world_id=${encodeURIComponent(worldId)}` : '';
  return fetchWithAuth<PlotBeatListItem[]>(`/admin/plot-beats${params}`);
}

export async function getPlotBeat(beatId: string): Promise<PlotBeatDetail> {
  return fetchWithAuth<PlotBeatDetail>(`/admin/plot-beats/${beatId}`);
}

export async function createPlotBeat(data: PlotBeatCreateRequest): Promise<PlotBeatDetail> {
  return fetchWithAuth<PlotBeatDetail>('/admin/plot-beats', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updatePlotBeat(beatId: string, data: PlotBeatUpdateRequest): Promise<PlotBeatDetail> {
  return fetchWithAuth<PlotBeatDetail>(`/admin/plot-beats/${beatId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deletePlotBeat(beatId: string): Promise<void> {
  return fetchWithAuth<void>(`/admin/plot-beats/${beatId}`, {
    method: 'DELETE',
  });
}

// =============================================================================
// Content Packs
// =============================================================================

export async function validateContentPack(path: string): Promise<ContentPackValidateResponse> {
  return fetchWithAuth<ContentPackValidateResponse>('/admin/content-packs/validate', {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

export async function importContentPack(path: string, dryRun: boolean = false): Promise<ContentPackImportResponse> {
  const params = dryRun ? '?dry_run=true' : '';
  return fetchWithAuth<ContentPackImportResponse>(`/admin/content-packs/import${params}`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

export { APIError };
