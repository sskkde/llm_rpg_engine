import { generatePortrait, generateSceneAsset, generateBGM, getAsset, listSessionAssets } from '@/lib/api';

const mockFetch = jest.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockClear();
});

function mockSuccessResponse(data: unknown) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

describe('Media API Client', () => {
  beforeEach(() => {
    localStorage.setItem('access_token', 'test-token');
  });

  afterEach(() => {
    localStorage.removeItem('access_token');
  });

  describe('generatePortrait', () => {
    it('calls POST /media/portraits/generate with correct body', async () => {
      const mockResponse = {
        asset_id: 'asset-1',
        asset_type: 'portrait',
        generation_status: 'completed',
        cache_hit: false,
        created_at: '2024-01-01T00:00:00Z',
      };
      mockSuccessResponse(mockResponse);

      const result = await generatePortrait({
        npc_id: 'npc-1',
        style: 'anime',
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/media/portraits/generate',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ npc_id: 'npc-1', style: 'anime' }),
        })
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe('generateSceneAsset', () => {
    it('calls POST /media/scenes/generate', async () => {
      mockSuccessResponse({ asset_id: 'asset-2', asset_type: 'scene', generation_status: 'completed', cache_hit: false, created_at: '2024-01-01T00:00:00Z' });
      const result = await generateSceneAsset({ location_id: 'loc-1' });
      expect(mockFetch).toHaveBeenCalledWith('/media/scenes/generate', expect.any(Object));
      expect(result.asset_type).toBe('scene');
    });
  });

  describe('generateBGM', () => {
    it('calls POST /media/bgm/generate', async () => {
      mockSuccessResponse({ asset_id: 'asset-3', asset_type: 'bgm', generation_status: 'completed', cache_hit: false, created_at: '2024-01-01T00:00:00Z' });
      const result = await generateBGM({ mood: 'calm', duration_seconds: 60 });
      expect(mockFetch).toHaveBeenCalledWith('/media/bgm/generate', expect.any(Object));
      expect(result.asset_type).toBe('bgm');
    });
  });

  describe('getAsset', () => {
    it('calls GET /media/assets/{id}', async () => {
      mockSuccessResponse({ asset_id: 'asset-1', asset_type: 'portrait', generation_status: 'completed', cache_hit: false, created_at: '2024-01-01T00:00:00Z' });
      const result = await getAsset('asset-1');
      expect(mockFetch).toHaveBeenCalledWith('/media/assets/asset-1', expect.any(Object));
      expect(result.asset_id).toBe('asset-1');
    });
  });

  describe('listSessionAssets', () => {
    it('calls GET /media/sessions/{id}/assets', async () => {
      mockSuccessResponse([{ asset_id: 'a1', asset_type: 'portrait' }]);
      const result = await listSessionAssets('session-1');
      expect(mockFetch).toHaveBeenCalledWith('/media/sessions/session-1/assets', expect.any(Object));
      expect(result).toHaveLength(1);
    });

    it('includes asset_type query param when provided', async () => {
      mockSuccessResponse([]);
      await listSessionAssets('session-1', 'portrait');
      const callUrl = mockFetch.mock.calls[0][0];
      expect(callUrl).toContain('asset_type=portrait');
    });
  });
});
