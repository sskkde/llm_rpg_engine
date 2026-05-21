import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { QuestJournalPanel } from '@/components/game/QuestJournalPanel';
import { InventoryPanel } from '@/components/game/InventoryPanel';
import { LocationMapPanel } from '@/components/game/LocationMapPanel';
import { RelationshipPanel } from '@/components/game/RelationshipPanel';
import * as api from '@/lib/api';
import type {
  PlayerQuestSummary,
  PlayerQuestDetail,
  PlayerInventoryItem,
  InventoryStats,
  PlayerLocation,
  PlayerRelationship,
  RelationshipSummary,
} from '@/types/api';

jest.mock('@/lib/api', () => ({
  getPlayerQuests: jest.fn(),
  getPlayerQuestDetail: jest.fn(),
  getPlayerInventory: jest.fn(),
  getPlayerInventoryStats: jest.fn(),
  getPlayerLocations: jest.fn(),
  getPlayerRelationships: jest.fn(),
  getPlayerRelationshipsSummary: jest.fn(),
}));

const mockGetPlayerQuests = api.getPlayerQuests as jest.MockedFunction<typeof api.getPlayerQuests>;
const mockGetPlayerQuestDetail = api.getPlayerQuestDetail as jest.MockedFunction<typeof api.getPlayerQuestDetail>;
const mockGetPlayerInventory = api.getPlayerInventory as jest.MockedFunction<typeof api.getPlayerInventory>;
const mockGetPlayerInventoryStats = api.getPlayerInventoryStats as jest.MockedFunction<typeof api.getPlayerInventoryStats>;
const mockGetPlayerLocations = api.getPlayerLocations as jest.MockedFunction<typeof api.getPlayerLocations>;
const mockGetPlayerRelationships = api.getPlayerRelationships as jest.MockedFunction<typeof api.getPlayerRelationships>;
const mockGetPlayerRelationshipsSummary = api.getPlayerRelationshipsSummary as jest.MockedFunction<typeof api.getPlayerRelationshipsSummary>;

function V1PlayableFlow({ sessionId }: { sessionId: string }) {
  return (
    <div data-testid="v1-playable-flow">
      <QuestJournalPanel sessionId={sessionId} />
      <InventoryPanel sessionId={sessionId} />
      <LocationMapPanel sessionId={sessionId} />
      <RelationshipPanel sessionId={sessionId} />
    </div>
  );
}

const createMockQuestSummary = (overrides: Partial<PlayerQuestSummary> = {}): PlayerQuestSummary => ({
  quest_id: 'quest-1',
  title: 'Test Quest',
  description: 'A test quest description',
  stage: 1,
  status: 'active',
  objectives: [
    { step_no: 1, objective: 'First objective', completed: false },
    { step_no: 2, objective: 'Second objective', completed: true },
  ],
  ...overrides,
});

const createMockQuestDetail = (overrides: Partial<PlayerQuestDetail> = {}): PlayerQuestDetail => ({
  quest_id: 'quest-1',
  title: 'Test Quest',
  description: 'A test quest description',
  stage: 1,
  status: 'active',
  objectives: [
    { step_no: 1, objective: 'First objective', completed: false },
    { step_no: 2, objective: 'Second objective', completed: true },
  ],
  steps: [
    { stage: 1, description: 'First step', completed: true },
    { stage: 2, description: 'Second step', completed: false },
  ],
  started_at: '2024-01-01T00:00:00Z',
  ...overrides,
});

const createMockItem = (overrides: Partial<PlayerInventoryItem> = {}): PlayerInventoryItem => ({
  id: 'item-1',
  name: 'Test Item',
  description: 'A test item description',
  quantity: 1,
  rarity: 'common',
  item_type: 'consumable',
  effects: { hp: 10 },
  ...overrides,
});

const createMockStats = (overrides: Partial<InventoryStats> = {}): InventoryStats => ({
  total_items: 5,
  unique_items: 3,
  categories: { consumable: 2, equipment: 1 },
  ...overrides,
});

const createMockLocation = (overrides: Partial<PlayerLocation> = {}): PlayerLocation => ({
  location_id: 'loc-1',
  name: 'Test Location',
  description: 'A test location description',
  connections: ['loc-2'],
  is_current: false,
  danger_level: 'safe',
  accessible: true,
  ...overrides,
});

const createMockRelationship = (overrides: Partial<PlayerRelationship> = {}): PlayerRelationship => ({
  npc_id: 'npc-1',
  npc_name: 'Test NPC',
  trust_score: 50,
  respect_score: 50,
  fear_score: 30,
  last_interaction_turn: 5,
  ...overrides,
});

const createMockSummary = (overrides: Partial<RelationshipSummary> = {}): RelationshipSummary => ({
  total_npcs: 2,
  highest_trust: { npc_id: 'npc-1', npc_name: 'Friendly NPC', trust_score: 80 },
  lowest_trust: { npc_id: 'npc-2', npc_name: 'Hostile NPC', trust_score: 20 },
  average_trust: 50,
  average_respect: 45,
  ...overrides,
});

describe('V1PlayableFlow Integration', () => {
  const sessionId = 'test-session-id';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Test 1: All panels render together with mock data', () => {
    it('renders all 4 panels with their data', async () => {
      const quest = createMockQuestSummary({ quest_id: 'quest-1', title: 'Main Quest' });
      const questDetail = createMockQuestDetail({ quest_id: 'quest-1', title: 'Main Quest' });
      const item = createMockItem({ id: 'item-1', name: 'Health Potion' });
      const stats = createMockStats();
      const location = createMockLocation({ location_id: 'loc-1', name: 'Village', is_current: true });
      const relationship = createMockRelationship({ npc_id: 'npc-1', npc_name: 'Elder Wang' });
      const summary = createMockSummary();

      mockGetPlayerQuests.mockResolvedValueOnce([quest]);
      mockGetPlayerQuestDetail.mockResolvedValueOnce(questDetail);
      mockGetPlayerInventory.mockResolvedValueOnce([item]);
      mockGetPlayerInventoryStats.mockResolvedValueOnce(stats);
      mockGetPlayerLocations.mockResolvedValueOnce([location]);
      mockGetPlayerRelationships.mockResolvedValueOnce([relationship]);
      mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(summary);

      renderWithIntl(<V1PlayableFlow sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByText('Main Quest')).toBeInTheDocument();
      });

      expect(screen.getByText('任务日志')).toBeInTheDocument();
      expect(screen.getByText('物品栏')).toBeInTheDocument();
      expect(screen.getByText('地点地图')).toBeInTheDocument();
      expect(screen.getByText('人际关系')).toBeInTheDocument();

      expect(screen.getByText('Health Potion')).toBeInTheDocument();
      expect(screen.getByText('Village')).toBeInTheDocument();
      expect(screen.getByText('Elder Wang')).toBeInTheDocument();

      expect(mockGetPlayerQuests).toHaveBeenCalledWith(sessionId);
      expect(mockGetPlayerInventory).toHaveBeenCalledWith(sessionId, undefined);
      expect(mockGetPlayerLocations).toHaveBeenCalledWith(sessionId);
      expect(mockGetPlayerRelationships).toHaveBeenCalledWith(sessionId, 'trust');
    });
  });

  describe('Test 2: Empty state for all panels', () => {
    it('shows empty state for all panels when API returns empty arrays', async () => {
      mockGetPlayerQuests.mockResolvedValueOnce([]);
      mockGetPlayerInventory.mockResolvedValueOnce([]);
      mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats({ total_items: 0, unique_items: 0 }));
      mockGetPlayerLocations.mockResolvedValueOnce([]);
      mockGetPlayerRelationships.mockResolvedValueOnce([]);
      mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary({ total_npcs: 0 }));

      renderWithIntl(<V1PlayableFlow sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByText('暂无任务')).toBeInTheDocument();
      });

      expect(screen.getByText('物品栏为空')).toBeInTheDocument();
      expect(screen.getByText('尚未发现任何地点')).toBeInTheDocument();
      expect(screen.getByText('尚未结识任何人物')).toBeInTheDocument();

      expect(screen.getByText('任务日志')).toBeInTheDocument();
      expect(screen.getByText('物品栏')).toBeInTheDocument();
      expect(screen.getByText('地点地图')).toBeInTheDocument();
      expect(screen.getByText('人际关系')).toBeInTheDocument();
    });
  });

  describe('Test 3: Error state for all panels', () => {
    it('shows error state for all panels when API rejects', async () => {
      mockGetPlayerQuests.mockRejectedValueOnce(new Error('Quest API Error'));
      mockGetPlayerInventory.mockRejectedValueOnce(new Error('Inventory API Error'));
      mockGetPlayerInventoryStats.mockRejectedValueOnce(new Error('Stats API Error'));
      mockGetPlayerLocations.mockRejectedValueOnce(new Error('Location API Error'));
      mockGetPlayerRelationships.mockRejectedValueOnce(new Error('Relationship API Error'));
      mockGetPlayerRelationshipsSummary.mockRejectedValueOnce(new Error('Summary API Error'));

      renderWithIntl(<V1PlayableFlow sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByText('加载任务失败')).toBeInTheDocument();
      });

      expect(screen.getByText('加载物品栏失败')).toBeInTheDocument();
      expect(screen.getByText('加载地点失败')).toBeInTheDocument();

      expect(screen.getByText('任务日志')).toBeInTheDocument();
      expect(screen.getByText('物品栏')).toBeInTheDocument();
      expect(screen.getByText('地点地图')).toBeInTheDocument();
      expect(screen.getByText('人际关系')).toBeInTheDocument();
    });
  });

  describe('Test 4: Panel coexistence without conflict', () => {
    it('renders all panels in the same container without React errors', async () => {
      const quest = createMockQuestSummary();
      const questDetail = createMockQuestDetail();
      const item = createMockItem();
      const location = createMockLocation();
      const relationship = createMockRelationship();

      mockGetPlayerQuests.mockResolvedValueOnce([quest]);
      mockGetPlayerQuestDetail.mockResolvedValueOnce(questDetail);
      mockGetPlayerInventory.mockResolvedValueOnce([item]);
      mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
      mockGetPlayerLocations.mockResolvedValueOnce([location]);
      mockGetPlayerRelationships.mockResolvedValueOnce([relationship]);
      mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary());

      const { container } = renderWithIntl(<V1PlayableFlow sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByTestId('v1-playable-flow')).toBeInTheDocument();
      });

      const flowContainer = container.querySelector('[data-testid="v1-playable-flow"]');
      expect(flowContainer).toBeInTheDocument();

      expect(screen.getByText('任务日志')).toBeInTheDocument();
      expect(screen.getByText('物品栏')).toBeInTheDocument();
      expect(screen.getByText('地点地图')).toBeInTheDocument();
      expect(screen.getByText('人际关系')).toBeInTheDocument();
    });

    it('all panels use the same sessionId consistently', async () => {
      const testSessionId = 'shared-session-123';

      mockGetPlayerQuests.mockResolvedValueOnce([]);
      mockGetPlayerInventory.mockResolvedValueOnce([]);
      mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
      mockGetPlayerLocations.mockResolvedValueOnce([]);
      mockGetPlayerRelationships.mockResolvedValueOnce([]);
      mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary());

      renderWithIntl(<V1PlayableFlow sessionId={testSessionId} />);

      await waitFor(() => {
        expect(screen.getByText('暂无任务')).toBeInTheDocument();
      });

      expect(mockGetPlayerQuests).toHaveBeenCalledWith(testSessionId);
      expect(mockGetPlayerInventory).toHaveBeenCalledWith(testSessionId, undefined);
      expect(mockGetPlayerLocations).toHaveBeenCalledWith(testSessionId);
      expect(mockGetPlayerRelationships).toHaveBeenCalledWith(testSessionId, 'trust');
      expect(mockGetPlayerRelationshipsSummary).toHaveBeenCalledWith(testSessionId);
    });

    it('handles mixed states - some panels with data, some empty', async () => {
      const quest = createMockQuestSummary({ title: 'Active Quest' });
      const questDetail = createMockQuestDetail({ title: 'Active Quest' });
      const location = createMockLocation({ name: 'Town' });

      mockGetPlayerQuests.mockResolvedValueOnce([quest]);
      mockGetPlayerQuestDetail.mockResolvedValueOnce(questDetail);
      mockGetPlayerInventory.mockResolvedValueOnce([]);
      mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
      mockGetPlayerLocations.mockResolvedValueOnce([location]);
      mockGetPlayerRelationships.mockResolvedValueOnce([]);
      mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary({ total_npcs: 0 }));

      renderWithIntl(<V1PlayableFlow sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByText('Active Quest')).toBeInTheDocument();
      });

      expect(screen.getByText('Active Quest')).toBeInTheDocument();
      expect(screen.getByText('物品栏为空')).toBeInTheDocument();
      expect(screen.getByText('Town')).toBeInTheDocument();
      expect(screen.getByText('尚未结识任何人物')).toBeInTheDocument();
    });
  });
});
