import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {TurnDebugViewer} from '@/components/debug/TurnDebugViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetTurnDebug = api.getTurnDebug as jest.MockedFunction<typeof api.getTurnDebug>;

const mockTurnDebugResponse = {
  audit_id: 'audit-123',
  session_id: 'test-session',
  turn_no: 1,
  transaction_id: 'tx-abc',
  player_input: 'Look around',
  parsed_intent: {action: 'explore', target: 'room'},
  world_time_before: {day: 1, period: 'morning'},
  world_time_after: {day: 1, period: 'afternoon'},
  events: [
    {event_id: 'evt-1', event_type: 'player_input', actor_id: 'player', summary: 'Player looked around'},
  ],
  state_deltas: [
    {delta_id: 'delta-1', path: 'player.location', old_value: 'hall', new_value: 'room', operation: 'changed', validated: true},
  ],
  context_build_ids: ['ctx-1'],
  model_call_ids: ['call-1'],
  validation_ids: ['val-1'],
  status: 'completed',
  narration_generated: true,
  narration_length: 150,
  turn_duration_ms: 2500,
  started_at: '2024-01-01T10:00:00Z',
  completed_at: '2024-01-01T10:00:03Z',
  llm_stages: [
    {stage_name: 'world', enabled: true, timeout: 30.0, accepted: true, fallback_reason: undefined, validation_errors: [], model_call_id: 'call-1'},
    {stage_name: 'narration', enabled: true, timeout: 30.0, accepted: false, fallback_reason: 'timeout', validation_errors: ['Invalid output'], model_call_id: undefined},
  ],
  fallback_reasons: ['narration: timeout'],
  prompt_template_ids: ['prompt-1'],
  context_hashes: [{build_id: 'ctx-1', context_hash: 'abc123'}],
  model_call_references: [
    {call_id: 'call-1', prompt_type: 'world', model_name: 'gpt-4', provider: 'openai', input_tokens: 100, output_tokens: 50, cost_estimate: 0.001, latency_ms: 1500},
  ],
};

describe('TurnDebugViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetTurnDebug.mockResolvedValue(mockTurnDebugResponse);
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<TurnDebugViewer sessionId="" turnNo={1} />);
    expect(screen.getByText('未加载回合')).toBeInTheDocument();
  });

  it('shows empty state when turn number is invalid', () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={0} />);
    expect(screen.getByText('未加载回合')).toBeInTheDocument();
  });

  it('shows load button when valid props provided', () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);
    expect(screen.getByText('加载回合调试数据')).toBeInTheDocument();
  });

  it('loads data when button clicked', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(mockGetTurnDebug).toHaveBeenCalledWith('test-session', 1);
    });

    await waitFor(() => {
      expect(screen.getByText('回合 1 调试数据')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetTurnDebug.mockRejectedValue(error);

    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows 404 error when turn not found', async () => {
    const error = new Error('Not found') as Error & { status?: number };
    error.status = 404;
    mockGetTurnDebug.mockRejectedValue(error);

    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={999} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('回合未找到')).toBeInTheDocument();
    });
  });

  it('renders LLM stages section', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('LLM阶段')).toBeInTheDocument();
    });
  });

  it('renders state deltas section', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('状态变更')).toBeInTheDocument();
    });
  });

  it('renders context builds section', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('上下文构建')).toBeInTheDocument();
    });
  });

  it('shows fallback reasons when present', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('回退原因')).toBeInTheDocument();
    });
  });

  it('refreshes data when refresh button clicked', async () => {
    renderWithIntl(<TurnDebugViewer sessionId="test-session" turnNo={1} />);

    const loadButton = screen.getByText('加载回合调试数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('回合 1 调试数据')).toBeInTheDocument();
    });

    const refreshButton = screen.getByText('刷新');
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(mockGetTurnDebug).toHaveBeenCalledTimes(2);
    });
  });
});
