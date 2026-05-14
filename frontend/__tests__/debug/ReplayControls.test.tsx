import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { ReplayControls } from '@/components/debug/ReplayControls';

jest.mock('@/lib/api', () => ({
  replaySession: jest.fn(),
  createSnapshot: jest.fn(),
  getReplayReport: jest.fn(),
}));

import { replaySession, createSnapshot, getReplayReport } from '@/lib/api';

const mockReplaySession = replaySession as jest.MockedFunction<typeof replaySession>;
const mockCreateSnapshot = createSnapshot as jest.MockedFunction<typeof createSnapshot>;
const mockGetReplayReport = getReplayReport as jest.MockedFunction<typeof getReplayReport>;

describe('ReplayControls', () => {
  const sessionId = 'test-session-123';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders turn range inputs and perspective selector', () => {
    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    expect(screen.getByText('起始回合')).toBeInTheDocument();
    expect(screen.getByText('结束回合')).toBeInTheDocument();
    expect(screen.getByText('视角')).toBeInTheDocument();
  });

  it('renders action buttons', () => {
    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    expect(screen.getByRole('button', { name: '开始回放' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '创建快照' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '生成报告' })).toBeInTheDocument();
  });

  it('disables buttons when loading', async () => {
    mockReplaySession.mockImplementation(() => new Promise(() => {}));

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const startReplayButton = screen.getByRole('button', { name: '开始回放' });
    fireEvent.click(startReplayButton);

    await waitFor(() => {
      expect(startReplayButton).toBeDisabled();
    });
  });

  it('calls replaySession with correct parameters', async () => {
    mockReplaySession.mockResolvedValue({
      replay_id: 'replay-1',
      session_id: sessionId,
      start_turn: 1,
      end_turn: 10,
      perspective: 'admin',
      steps: [],
      final_state: {},
      total_steps: 0,
      total_events: 0,
      total_state_deltas: 0,
      success: true,
      started_at: '2024-01-01T00:00:00',
    });

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const startReplayButton = screen.getByRole('button', { name: '开始回放' });
    fireEvent.click(startReplayButton);

    await waitFor(() => {
      expect(mockReplaySession).toHaveBeenCalledWith(sessionId, {
        start_turn: 1,
        end_turn: 10,
        perspective: 'admin',
      });
    });
  });

  it('calls createSnapshot with correct parameters', async () => {
    mockCreateSnapshot.mockResolvedValue({
      snapshot_id: 'snapshot-1',
      session_id: sessionId,
      turn_no: 10,
      world_state: {},
      player_state: {},
      npc_states: {},
      location_states: {},
      quest_states: {},
      faction_states: {},
      created_at: '2024-01-01T00:00:00',
      snapshot_type: 'manual',
    });

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const createSnapshotButton = screen.getByRole('button', { name: '创建快照' });
    fireEvent.click(createSnapshotButton);

    await waitFor(() => {
      expect(mockCreateSnapshot).toHaveBeenCalledWith(sessionId, {
        turn_no: 10,
      });
    });
  });

  it('calls getReplayReport with correct parameters', async () => {
    mockGetReplayReport.mockResolvedValue({
      session_id: sessionId,
      from_turn: 1,
      to_turn: 10,
      replayed_event_count: 0,
      deterministic: true,
      llm_calls_made: 0,
      state_diff: {
        entries: [],
        added_keys: [],
        removed_keys: [],
        changed_keys: [],
      },
      warnings: [],
      created_at: '2024-01-01T00:00:00',
    });

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const generateReportButton = screen.getByRole('button', { name: '生成报告' });
    fireEvent.click(generateReportButton);

    await waitFor(() => {
      expect(mockGetReplayReport).toHaveBeenCalledWith(sessionId, {
        start_turn: 1,
        end_turn: 10,
        perspective: 'admin',
      });
    });
  });

  it('displays error message on API failure', async () => {
    mockReplaySession.mockRejectedValue({
      status: 403,
      detail: 'Admin required',
    });

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const startReplayButton = screen.getByRole('button', { name: '开始回放' });
    fireEvent.click(startReplayButton);

    await waitFor(() => {
      expect(screen.getByText(/需要管理员权限/)).toBeInTheDocument();
    });
  });

  it('displays replay results after successful replay', async () => {
    mockReplaySession.mockResolvedValue({
      replay_id: 'replay-1',
      session_id: sessionId,
      start_turn: 1,
      end_turn: 10,
      perspective: 'admin',
      steps: [
        {
          step_no: 1,
          turn_no: 1,
          player_input: 'test input',
          state_before: {},
          state_after: {},
          events: [],
          state_deltas: [],
          timestamp: '2024-01-01T00:00:00',
        },
      ],
      final_state: {},
      total_steps: 1,
      total_events: 0,
      total_state_deltas: 0,
      success: true,
      started_at: '2024-01-01T00:00:00',
    });

    renderWithIntl(<ReplayControls sessionId={sessionId} />);

    const startReplayButton = screen.getByRole('button', { name: '开始回放' });
    fireEvent.click(startReplayButton);

    await waitFor(() => {
      expect(screen.getByText('回放结果')).toBeInTheDocument();
      expect(screen.getByText('回合 1')).toBeInTheDocument();
    });
  });
});
