import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { RelationshipPanel } from '@/components/game/RelationshipPanel';
import * as api from '@/lib/api';
import type { PlayerRelationship, RelationshipSummary } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getPlayerRelationships: jest.fn(),
  getPlayerRelationshipsSummary: jest.fn(),
}));

const mockGetPlayerRelationships = api.getPlayerRelationships as jest.MockedFunction<typeof api.getPlayerRelationships>;
const mockGetPlayerRelationshipsSummary = api.getPlayerRelationshipsSummary as jest.MockedFunction<typeof api.getPlayerRelationshipsSummary>;

describe('RelationshipPanel', () => {
  const sessionId = 'test-session-id';

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

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetPlayerRelationships.mockImplementation(() => new Promise(() => {}));
    mockGetPlayerRelationshipsSummary.mockImplementation(() => new Promise(() => {}));
    
    renderWithIntl(<RelationshipPanel sessionId={sessionId} />);
    
    expect(screen.getByText('人际关系')).toBeInTheDocument();
  });

  it('shows empty state when no relationships', async () => {
    mockGetPlayerRelationships.mockResolvedValueOnce([]);
    mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary({ total_npcs: 0 }));
    
    renderWithIntl(<RelationshipPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('尚未结识任何人物')).toBeInTheDocument();
    });
    
    expect(mockGetPlayerRelationships).toHaveBeenCalledWith(sessionId, 'trust');
  });

  it('renders NPC list with trust scores', async () => {
    const rel1 = createMockRelationship({ npc_id: 'npc-1', npc_name: 'Friendly NPC', trust_score: 80 });
    const rel2 = createMockRelationship({ npc_id: 'npc-2', npc_name: 'Neutral NPC', trust_score: 50 });
    
    mockGetPlayerRelationships.mockResolvedValueOnce([rel1, rel2]);
    mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary());
    
    renderWithIntl(<RelationshipPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Friendly NPC')).toBeInTheDocument();
    });
    
    expect(screen.getByText('Neutral NPC')).toBeInTheDocument();
    expect(screen.getByText('80')).toBeInTheDocument();
    expect(screen.getByText('50')).toBeInTheDocument();
  });

  it('sort toggle works', async () => {
    const rel = createMockRelationship();
    
    mockGetPlayerRelationships.mockResolvedValueOnce([rel]);
    mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(createMockSummary());
    
    renderWithIntl(<RelationshipPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Test NPC')).toBeInTheDocument();
    });
    
    mockGetPlayerRelationships.mockResolvedValueOnce([rel]);
    const respectButton = screen.getByRole('button', { name: '尊重排序' });
    fireEvent.click(respectButton);
    
    await waitFor(() => {
      expect(mockGetPlayerRelationships).toHaveBeenCalledWith(sessionId, 'respect');
    });
  });

  it('shows summary statistics', async () => {
    const rel = createMockRelationship();
    const summary = createMockSummary();
    
    mockGetPlayerRelationships.mockResolvedValueOnce([rel]);
    mockGetPlayerRelationshipsSummary.mockResolvedValueOnce(summary);
    
    renderWithIntl(<RelationshipPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('已结识人物')).toBeInTheDocument();
    });
    
    expect(screen.getByText('平均信任')).toBeInTheDocument();
    expect(screen.getByText('最高信任')).toBeInTheDocument();
  });
});
