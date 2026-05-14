import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {NPCMindInspector} from '@/components/debug/NPCMindInspector';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockListSessionNpcs = api.listSessionNpcs as jest.MockedFunction<typeof api.listSessionNpcs>;
const mockGetNpcMind = api.getNpcMind as jest.MockedFunction<typeof api.getNpcMind>;

const mockNpcsResponse = {
  session_id: 'test-session',
  npcs: [
    { npc_id: 'npc-1', name: '张三', location_id: 'loc-1' },
    { npc_id: 'npc-2', name: '李四', location_id: 'loc-2' },
  ],
};

const mockMindResponse = {
  session_id: 'test-session',
  npc_id: 'npc-1',
  npc_name: '张三',
  viewer_role: 'admin' as const,
  beliefs: [
    { belief_id: 'b1', content: '相信玩家是好人', confidence: 0.8, source_turn: 1 },
  ],
  private_memories: [
    { memory_id: 'm1', content: '记得玩家帮助过我', strength: 0.9, memory_type: 'episodic', created_turn: 2 },
  ],
  secrets: [
    { secret_id: 's1', content: '隐藏身份是仙人', reveal_willingness: 0.1, known_by: [] },
  ],
  goals: [
    { goal_id: 'g1', description: '帮助玩家成长', priority: 1, status: 'active' },
  ],
  forbidden_knowledge: [
    { knowledge_id: 'fk1', content: '知道天机', source: '古籍' },
  ],
  relationship_memories: [
    { target_entity_id: 'player', target_name: '玩家', relationship_type: 'mentor', memories: ['教导修炼'], trust_score: 0.7 },
  ],
};

describe('NPCMindInspector', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListSessionNpcs.mockResolvedValue(mockNpcsResponse);
    mockGetNpcMind.mockResolvedValue(mockMindResponse);
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<NPCMindInspector sessionId="" />);

    expect(screen.getByText('未加载会话')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockListSessionNpcs.mockImplementation(() => new Promise(() => {}));

    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders NPC selector after loading', async () => {
    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('选择NPC:')).toBeInTheDocument();
    });

    expect(screen.getByText('张三')).toBeInTheDocument();
    expect(screen.getByText('李四')).toBeInTheDocument();
  });

  it('shows NPC mind data after selection', async () => {
    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '张三' })).toBeInTheDocument();
    });

    expect(screen.getByText('管理员视图')).toBeInTheDocument();
  });

  it('shows auditor view badge for auditor role', async () => {
    mockGetNpcMind.mockResolvedValue({
      ...mockMindResponse,
      viewer_role: 'auditor',
    });

    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('审计员视图')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockListSessionNpcs.mockRejectedValue(error);

    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows no NPCs found message when list is empty', async () => {
    mockListSessionNpcs.mockResolvedValue({
      session_id: 'test-session',
      npcs: [],
    });

    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('未找到NPC')).toBeInTheDocument();
    });
  });

  it('changes selected NPC when dropdown changes', async () => {
    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument();
    });

    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'npc-2' } });

    await waitFor(() => {
      expect(mockGetNpcMind).toHaveBeenCalledWith('test-session', 'npc-2');
    });
  });

  it('renders collapsible sections', async () => {
    renderWithIntl(<NPCMindInspector sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('信念')).toBeInTheDocument();
    });

    expect(screen.getByText('私密记忆')).toBeInTheDocument();
    expect(screen.getByText('秘密')).toBeInTheDocument();
    expect(screen.getByText('目标')).toBeInTheDocument();
    expect(screen.getByText('禁忌知识')).toBeInTheDocument();
    expect(screen.getByText('关系')).toBeInTheDocument();
  });
});
