import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { QuestJournalPanel } from '@/components/game/QuestJournalPanel';
import * as api from '@/lib/api';
import type { PlayerQuestSummary, PlayerQuestDetail } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getPlayerQuests: jest.fn(),
  getPlayerQuestDetail: jest.fn(),
}));

const mockGetPlayerQuests = api.getPlayerQuests as jest.MockedFunction<typeof api.getPlayerQuests>;
const mockGetPlayerQuestDetail = api.getPlayerQuestDetail as jest.MockedFunction<typeof api.getPlayerQuestDetail>;

describe('QuestJournalPanel', () => {
  const sessionId = 'test-session-id';

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

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetPlayerQuests.mockImplementation(() => new Promise(() => {}));
    
    renderWithIntl(<QuestJournalPanel sessionId={sessionId} />);
    
    expect(screen.getByText('任务日志')).toBeInTheDocument();
  });

  it('shows empty state when no quests', async () => {
    mockGetPlayerQuests.mockResolvedValueOnce([]);
    
    renderWithIntl(<QuestJournalPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('暂无任务')).toBeInTheDocument();
    });
    
    expect(mockGetPlayerQuests).toHaveBeenCalledWith(sessionId);
  });

  it('renders quest list with quests', async () => {
    const quest1 = createMockQuestSummary({ quest_id: 'quest-1', title: 'First Quest' });
    const quest2 = createMockQuestSummary({ quest_id: 'quest-2', title: 'Second Quest' });
    const questDetail = createMockQuestDetail({ quest_id: 'quest-1', title: 'First Quest' });
    
    mockGetPlayerQuests.mockResolvedValueOnce([quest1, quest2]);
    mockGetPlayerQuestDetail.mockResolvedValueOnce(questDetail);
    
    renderWithIntl(<QuestJournalPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('First Quest')).toBeInTheDocument();
    });
    
    expect(screen.getByText('Second Quest')).toBeInTheDocument();
    expect(mockGetPlayerQuests).toHaveBeenCalledWith(sessionId);
    expect(mockGetPlayerQuestDetail).toHaveBeenCalledWith(sessionId, 'quest-1');
  });

  it('shows quest detail when selected', async () => {
    const quest = createMockQuestSummary();
    const questDetail = createMockQuestDetail();
    
    mockGetPlayerQuests.mockResolvedValueOnce([quest]);
    mockGetPlayerQuestDetail.mockResolvedValueOnce(questDetail);
    
    renderWithIntl(<QuestJournalPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Test Quest')).toBeInTheDocument();
    });
    
    expect(screen.getByText('First objective')).toBeInTheDocument();
    expect(screen.getByText('Second objective')).toBeInTheDocument();
  });

  it('shows error state on API failure', async () => {
    mockGetPlayerQuests.mockRejectedValueOnce(new Error('API Error'));
    
    renderWithIntl(<QuestJournalPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('加载任务失败')).toBeInTheDocument();
    });
  });
});
