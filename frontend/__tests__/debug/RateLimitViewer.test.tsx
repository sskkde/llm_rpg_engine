import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { RateLimitViewer } from '@/components/debug/RateLimitViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetDebugRateLimitEvents = api.getDebugRateLimitEvents as jest.MockedFunction<typeof api.getDebugRateLimitEvents>;

const mockEvents = [
  {
    event_id: 'event-1',
    user_id: 'user-1',
    session_id: 'session-1',
    provider_name: 'openai',
    bucket_key: 'openai:user-1:hour',
    limit_type: 'requests',
    allowed: true,
    limit_value: 100,
    current_value: 5,
    reset_at: '2024-01-01T01:00:00Z',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    event_id: 'event-2',
    user_id: 'user-1',
    session_id: 'session-1',
    provider_name: 'openai',
    bucket_key: 'openai:user-1:hour',
    limit_type: 'requests',
    allowed: false,
    limit_value: 100,
    current_value: 100,
    reset_at: '2024-01-01T01:00:00Z',
    created_at: '2024-01-01T00:30:00Z',
  },
  {
    event_id: 'event-3',
    user_id: 'user-2',
    session_id: 'session-2',
    provider_name: 'mock',
    bucket_key: 'mock:user-2:minute',
    limit_type: 'tokens',
    allowed: true,
    limit_value: 10000,
    current_value: 500,
    reset_at: '2024-01-01T00:01:00Z',
    created_at: '2024-01-01T00:00:30Z',
  },
];

describe('RateLimitViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetDebugRateLimitEvents.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<RateLimitViewer />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders rate limit events table when loaded', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 3, items: mockEvents });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      expect(screen.getByText(/速率限制事件/)).toBeInTheDocument();
    });
  });

  it('shows allowed badge for allowed events', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 1, items: [mockEvents[0]] });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      const allowedBadges = screen.getAllByText('允许');
      expect(allowedBadges.length).toBeGreaterThan(0);
    });
  });

  it('shows denied badge for denied events', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 1, items: [mockEvents[1]] });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      const deniedBadges = screen.getAllByText('拒绝');
      expect(deniedBadges.length).toBeGreaterThan(0);
    });
  });

  it('filters by user ID', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 2, items: [mockEvents[0], mockEvents[1]] });

    renderWithIntl(<RateLimitViewer userId="user-1" />);

    await waitFor(() => {
      expect(mockGetDebugRateLimitEvents).toHaveBeenCalledWith(0, 100, 'user-1');
    });
  });

  it('shows empty state when no events', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 0, items: [] });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      expect(screen.getByText('暂无速率限制事件')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetDebugRateLimitEvents.mockRejectedValue(error);

    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows admin required message on 403', async () => {
    const error = new Error('Forbidden') as Error & { status?: number };
    error.status = 403;
    mockGetDebugRateLimitEvents.mockRejectedValue(error);

    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      expect(screen.getByText('需要管理员权限')).toBeInTheDocument();
    });
  });

  it('displays provider name', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 3, items: mockEvents });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      const openaiProviders = screen.getAllByText('openai');
      const mockProviders = screen.getAllByText('mock');
      expect(openaiProviders.length).toBeGreaterThan(0);
      expect(mockProviders.length).toBeGreaterThan(0);
    });
  });

  it('displays limit type', async () => {
    mockGetDebugRateLimitEvents.mockResolvedValue({ total: 3, items: mockEvents });
    renderWithIntl(<RateLimitViewer />);

    await waitFor(() => {
      const requests = screen.getAllByText('requests');
      const tokens = screen.getAllByText('tokens');
      expect(requests.length).toBeGreaterThan(0);
      expect(tokens.length).toBeGreaterThan(0);
    });
  });
});
