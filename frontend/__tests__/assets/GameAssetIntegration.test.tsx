/**
 * TEST DEBT STATUS: Fixed (was failing due to missing component mocks)
 * Original issue: GameSessionContent references InventoryPanel and LocationMapPanel
 *   which are not imported in the page module, causing ReferenceError in jsdom.
 * Resolution: Added jest.mock for InventoryPanel and LocationMapPanel.
 * Remaining debt: GameSessionPage.test.tsx still uses describe.skip due to
 *   React 19 use(params) incompatibility with jsdom (deferred - requires
 *   architectural change to extract GameSessionContent for testing).
 */
import { waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { GameSessionContent } from '@/app/[locale]/game/[sessionId]/page';

const mockGetSessionSnapshot = jest.fn();
const mockGetAdventureLog = jest.fn();
const mockGenerateSceneAsset = jest.fn();
const mockGenerateBGM = jest.fn();
const mockListSessionNpcs = jest.fn();
const mockGeneratePortrait = jest.fn();
const mockCreatePortraitJob = jest.fn();
const mockGetAssetJob = jest.fn();
const mockGetPlayerQuests = jest.fn();

jest.mock('@/lib/api', () => ({
  getSessionSnapshot: (...args: unknown[]) => mockGetSessionSnapshot(...args),
  getAdventureLog: (...args: unknown[]) => mockGetAdventureLog(...args),
  generateSceneAsset: (...args: unknown[]) => mockGenerateSceneAsset(...args),
  generateBGM: (...args: unknown[]) => mockGenerateBGM(...args),
  listSessionNpcs: (...args: unknown[]) => mockListSessionNpcs(...args),
  generatePortrait: (...args: unknown[]) => mockGeneratePortrait(...args),
  createPortraitJob: (...args: unknown[]) => mockCreatePortraitJob(...args),
  getAssetJob: (...args: unknown[]) => mockGetAssetJob(...args),
  getPlayerQuests: (...args: unknown[]) => mockGetPlayerQuests(...args),
}));

jest.mock('@/hooks/useAssetJob', () => ({
  useAssetJob: () => ({
    job: null,
    isLoading: false,
    error: null,
    isPolling: false,
    retry: jest.fn(),
    cancel: jest.fn(),
    refetch: jest.fn(),
  }),
}));

jest.mock('@/hooks/useTurnStream', () => ({
  useTurnStream: () => ({
    isStreaming: false,
    isPending: false,
    narration: '',
    error: null,
    usedFallback: false,
    submitTurn: jest.fn(),
    clearError: jest.fn(),
  }),
}));

jest.mock('@/components/ui/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/zh/game/test-session',
}));

jest.mock('@/components/game/InventoryPanel', () => ({
  InventoryPanel: () => <div data-testid="inventory-panel">Inventory</div>,
}));

jest.mock('@/components/game/LocationMapPanel', () => ({
  LocationMapPanel: () => <div data-testid="location-map-panel">Location Map</div>,
}));

jest.mock('@/components/game/QuestJournalPanel', () => ({
  QuestJournalPanel: () => <div data-testid="quest-journal">Quest Journal</div>,
}));

jest.mock('@/components/game/SettingsPanel', () => ({
  SettingsPanel: () => <div data-testid="settings-panel">Settings</div>,
}));

function renderPage() {
  return renderWithIntl(
    <GameSessionContent sessionId="test-session" />
  );
}

const mockSnapshot = {
  session_id: 'test-session',
  user_id: 'user-1',
  world_id: 'world-1',
  status: 'active',
  started_at: '2025-01-01T00:00:00Z',
  last_played_at: '2025-01-01T00:00:00Z',
  player_state: { hp: 100, max_hp: 100, level: 1 },
  session_state: {
    active_mode: 'exploration',
    current_location_id: 'loc-mountain-gate',
    current_time: '清晨',
  },
};

const mockLogEntries = [
  {
    id: 'entry-1',
    turn_no: 0,
    event_type: 'initial_scene',
    action: null,
    narration: '你站在一座古老的山门前。',
    recommended_actions: ['环顾四周'],
    occurred_at: '2025-01-01T00:00:00Z',
  },
];

const mockNpcsAtLocation = [
  { npc_id: 'npc-elder', name: '长老', location_id: 'loc-mountain-gate' },
  { npc_id: 'npc-guard', name: '守卫', location_id: 'loc-mountain-gate' },
];

const mockNpcsEmpty: { npc_id: string; name: string; location_id: string }[] = [];

describe('GameAssetIntegration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGenerateSceneAsset.mockReturnValue(new Promise(() => {}));
    mockGenerateBGM.mockReturnValue(new Promise(() => {}));
    mockGeneratePortrait.mockReturnValue(new Promise(() => {}));
    mockGetPlayerQuests.mockResolvedValue([]);
    mockCreatePortraitJob.mockResolvedValue({
      job_id: 'job-portrait-1',
      asset_type: 'portrait',
      status: 'pending',
      provider_name: 'mock',
      attempt_count: 0,
      max_attempts: 3,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
    });
    mockListSessionNpcs.mockResolvedValue({ session_id: 'test-session', npcs: mockNpcsAtLocation });
  });

  describe('test_renders_scene_background', () => {
    it('renders SceneBackground when snapshot has current_location_id', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      const { container } = renderPage();

      await waitFor(() => {
        const sceneBackground = container.querySelector('[data-location-id="loc-mountain-gate"]');
        expect(sceneBackground).toBeInTheDocument();
      });
    });

    it('passes correct props to SceneBackground', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      renderPage();

      await waitFor(() => {
        expect(mockGenerateSceneAsset).toHaveBeenCalledWith(
          expect.objectContaining({
            location_id: 'loc-mountain-gate',
            session_id: 'test-session',
          })
        );
      });
    });
  });

  describe('test_does_not_render_scene_background_without_location', () => {
    it('does not render SceneBackground when current_location_id is undefined', async () => {
      mockGetSessionSnapshot.mockResolvedValue({
        ...mockSnapshot,
        session_state: {
          active_mode: 'exploration',
          current_location_id: undefined,
          current_time: '清晨',
        },
      });
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-location-id]')).not.toBeInTheDocument();
      });
    });
  });

  describe('test_renders_bgm_control', () => {
    it('renders BGMControl on the page', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      renderPage();

      await waitFor(() => {
        expect(mockGenerateBGM).toHaveBeenCalledWith(
          expect.objectContaining({
            location_id: 'loc-mountain-gate',
            session_id: 'test-session',
          })
        );
      });
    });
  });

  describe('test_turn_submission_not_blocked_by_asset_error', () => {
    it('page renders without crashing when asset API throws', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);
      mockGenerateSceneAsset.mockRejectedValue(new Error('Asset API error'));
      mockGenerateBGM.mockRejectedValue(new Error('BGM API error'));

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-location-id="loc-mountain-gate"]')).toBeInTheDocument();
      });
    });
  });

  describe('test_page_renders_without_crashing', () => {
    it('renders full page with all components', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-location-id="loc-mountain-gate"]')).toBeInTheDocument();
        expect(mockGenerateBGM).toHaveBeenCalled();
      });
    });

    it('handles missing session_state gracefully', async () => {
      mockGetSessionSnapshot.mockResolvedValue({
        ...mockSnapshot,
        session_state: undefined,
      });
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-location-id]')).not.toBeInTheDocument();
      });
    });
  });

  describe('test_time_of_day_extraction', () => {
    it('passes night timeOfDay when current_time contains "night"', async () => {
      mockGetSessionSnapshot.mockResolvedValue({
        ...mockSnapshot,
        session_state: {
          ...mockSnapshot.session_state,
          current_time: 'night',
        },
      });
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      renderPage();

      await waitFor(() => {
        expect(mockGenerateSceneAsset).toHaveBeenCalledWith(
          expect.objectContaining({
            time_of_day: 'night',
          })
        );
      });
    });

    it('passes morning timeOfDay when current_time contains "morning"', async () => {
      mockGetSessionSnapshot.mockResolvedValue({
        ...mockSnapshot,
        session_state: {
          ...mockSnapshot.session_state,
          current_time: 'morning',
        },
      });
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);

      renderPage();

      await waitFor(() => {
        expect(mockGenerateSceneAsset).toHaveBeenCalledWith(
          expect.objectContaining({
            time_of_day: 'morning',
          })
        );
      });
    });
  });

  describe('test_npc_portrait_integration', () => {
    it('renders NPCPortrait for NPCs at current location', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);
      mockListSessionNpcs.mockResolvedValue({ session_id: 'test-session', npcs: mockNpcsAtLocation });

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-testid="npc-portraits"]')).toBeInTheDocument();
      });

      // P8: NPCPortrait with sessionId uses createPortraitJob (async flow)
      await waitFor(() => {
        expect(mockCreatePortraitJob).toHaveBeenCalledWith(
          expect.objectContaining({
            npc_id: 'npc-elder',
            session_id: 'test-session',
          })
        );
        expect(mockCreatePortraitJob).toHaveBeenCalledWith(
          expect.objectContaining({
            npc_id: 'npc-guard',
            session_id: 'test-session',
          })
        );
      });
    });

    it('does not render NPCPortrait when no NPCs at current location', async () => {
      mockGetSessionSnapshot.mockResolvedValue(mockSnapshot);
      mockGetAdventureLog.mockResolvedValue(mockLogEntries);
      mockListSessionNpcs.mockResolvedValue({ session_id: 'test-session', npcs: mockNpcsEmpty });

      const { container } = renderPage();

      await waitFor(() => {
        expect(container.querySelector('[data-location-id="loc-mountain-gate"]')).toBeInTheDocument();
      });

      expect(container.querySelector('[data-testid="npc-portraits"]')).not.toBeInTheDocument();
    });
  });
});
