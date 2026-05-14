import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {TimelineViewer} from '@/components/debug/TimelineViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetSessionTimeline = api.getSessionTimeline as jest.MockedFunction<typeof api.getSessionTimeline>;
const mockGetTurnTimeline = api.getTurnTimeline as jest.MockedFunction<typeof api.getTurnTimeline>;

const mockTimelineResponse = {
  session_id: 'test-session',
  turns: [
    {
      turn_no: 1,
      timestamp: '2024-01-01T10:00:00Z',
      event_type: 'player_action',
      npc_actions: ['NPC讨论天气'],
      narration_excerpt: '这是一个测试叙事...',
    },
    {
      turn_no: 2,
      timestamp: '2024-01-01T10:05:00Z',
      event_type: 'narration',
      npc_actions: [],
      narration_excerpt: '另一个测试叙事...',
    },
  ],
  total_turns: 2,
  has_more: false,
};

const mockTurnDetail = {
  turn_no: 1,
  timestamp: '2024-01-01T10:00:00Z',
  event_type: 'player_action',
  player_action: '环顾四周',
  narration: '完整的叙事内容',
  npc_actions: ['NPC讨论天气'],
  events_committed: 3,
  world_time: {
    calendar: '修仙历',
    season: '春',
    day: 1,
    period: '早晨',
  },
};

describe('TimelineViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSessionTimeline.mockResolvedValue(mockTimelineResponse);
    mockGetTurnTimeline.mockResolvedValue(mockTurnDetail);
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<TimelineViewer sessionId="" />);

    expect(screen.getByText('未加载会话')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockGetSessionTimeline.mockImplementation(() => new Promise(() => {}));

    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders timeline turns after loading', async () => {
    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('1')).toBeInTheDocument();
    });

    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('player_action')).toBeInTheDocument();
  });

  it('shows turn detail when clicked', async () => {
    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('1')).toBeInTheDocument();
    });

    const turnCard = screen.getByText('1').closest('button');
    if (turnCard) {
      fireEvent.click(turnCard);
    }

    await waitFor(() => {
      expect(mockGetTurnTimeline).toHaveBeenCalledWith('test-session', 1);
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetSessionTimeline.mockRejectedValue(error);

    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows pagination controls when has_more is true', async () => {
    mockGetSessionTimeline.mockResolvedValue({
      ...mockTimelineResponse,
      has_more: true,
    });

    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('上一页')).toBeInTheDocument();
      expect(screen.getByText('下一页')).toBeInTheDocument();
    });
  });

  it('applies turn range filter', async () => {
    renderWithIntl(<TimelineViewer sessionId="test-session" />);

    await waitFor(() => {
      expect(screen.getByText('1')).toBeInTheDocument();
    });

    const inputs = screen.getAllByRole('spinbutton');
    const startInput = inputs[0];
    const endInput = inputs[1];
    const filterButton = screen.getByText('筛选');

    fireEvent.change(startInput, { target: { value: '1' } });
    fireEvent.change(endInput, { target: { value: '5' } });
    fireEvent.click(filterButton);

    await waitFor(() => {
      expect(mockGetSessionTimeline).toHaveBeenCalledWith(
        'test-session',
        1,
        5,
        20,
        0,
      );
    });
  });
});
