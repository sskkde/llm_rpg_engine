import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {ContextBuildAudit} from '@/components/debug/ContextBuildAudit';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetContextBuildAudit = api.getContextBuildAudit as jest.MockedFunction<typeof api.getContextBuildAudit>;

const mockContextBuildResponse = {
  build_id: 'build-123',
  session_id: 'test-session',
  turn_no: 1,
  perspective_type: 'player',
  perspective_id: 'player-1',
  owner_id: 'session-owner',
  included_memories: [
    {
      memory_id: 'mem-1',
      memory_type: 'episodic',
      owner_id: 'player-1',
      included: true,
      reason: 'high_relevance',
      relevance_score: 0.95,
      importance_score: 0.8,
      recency_score: 0.9,
      perspective_filter_applied: false,
      forbidden_knowledge_flag: false,
      notes: 'Recently accessed location',
    },
    {
      memory_id: 'mem-2',
      memory_type: 'semantic',
      owner_id: 'npc-1',
      included: true,
      reason: 'perspective_compatible',
      relevance_score: 0.7,
      importance_score: 0.6,
      recency_score: 0.5,
      perspective_filter_applied: true,
      forbidden_knowledge_flag: false,
      notes: undefined,
    },
  ],
  excluded_memories: [
    {
      memory_id: 'mem-3',
      memory_type: 'secret',
      owner_id: 'npc-2',
      included: false,
      reason: 'forbidden_knowledge',
      relevance_score: 0.9,
      importance_score: 0.95,
      recency_score: 0.8,
      perspective_filter_applied: true,
      forbidden_knowledge_flag: true,
      notes: 'Player should not know this',
    },
    {
      memory_id: 'mem-4',
      memory_type: 'episodic',
      owner_id: 'npc-3',
      included: false,
      reason: 'low_relevance',
      relevance_score: 0.1,
      importance_score: 0.2,
      recency_score: 0.3,
      perspective_filter_applied: false,
      forbidden_knowledge_flag: false,
      notes: undefined,
    },
  ],
  total_candidates: 4,
  included_count: 2,
  excluded_count: 2,
  context_token_count: 500,
  context_char_count: 2500,
  build_duration_ms: 150,
  created_at: '2024-01-01T10:00:00Z',
};

describe('ContextBuildAudit', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetContextBuildAudit.mockResolvedValue(mockContextBuildResponse);
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<ContextBuildAudit sessionId="" buildId="build-123" />);
    expect(screen.getByText('未加载上下文构建')).toBeInTheDocument();
  });

  it('shows empty state when no build ID provided', () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="" />);
    expect(screen.getByText('未加载上下文构建')).toBeInTheDocument();
  });

  it('shows load button when valid props provided', () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);
    expect(screen.getByText('加载上下文构建审计数据')).toBeInTheDocument();
  });

  it('loads data when button clicked', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(mockGetContextBuildAudit).toHaveBeenCalledWith('test-session', 'build-123');
    });

    await waitFor(() => {
      expect(screen.getByText('上下文构建审计')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetContextBuildAudit.mockRejectedValue(error);

    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows 404 error when build not found', async () => {
    const error = new Error('Not found') as Error & { status?: number };
    error.status = 404;
    mockGetContextBuildAudit.mockRejectedValue(error);

    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="nonexistent" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('上下文构建未找到')).toBeInTheDocument();
    });
  });

  it('renders included memories section', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('已包含记忆')).toBeInTheDocument();
    });
  });

  it('renders excluded memories section', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('已排除记忆')).toBeInTheDocument();
    });
  });

  it('shows memory counts in summary', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('候选总数')).toBeInTheDocument();
      expect(screen.getByText('包含数量')).toBeInTheDocument();
      expect(screen.getByText('排除数量')).toBeInTheDocument();
    });
  });

  it('displays memory entry with correct styling', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getAllByText('已包含').length).toBeGreaterThan(0);
      expect(screen.getAllByText('已排除').length).toBeGreaterThan(0);
    });
  });

  it('shows forbidden knowledge flag when present', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('禁忌知识')).toBeInTheDocument();
    });
  });

  it('shows perspective filtered flag when present', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getAllByText('视角过滤').length).toBeGreaterThan(0);
    });
  });

  it('refreshes data when refresh button clicked', async () => {
    renderWithIntl(<ContextBuildAudit sessionId="test-session" buildId="build-123" />);

    const loadButton = screen.getByText('加载上下文构建审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('上下文构建审计')).toBeInTheDocument();
    });

    const refreshButton = screen.getByText('刷新');
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(mockGetContextBuildAudit).toHaveBeenCalledTimes(2);
    });
  });
});