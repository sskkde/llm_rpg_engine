import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { AssetUsageViewer } from '@/components/debug/AssetUsageViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetDebugUsage = api.getDebugUsage as jest.MockedFunction<typeof api.getDebugUsage>;
const mockGetDebugUsageSummary = api.getDebugUsageSummary as jest.MockedFunction<typeof api.getDebugUsageSummary>;

const mockUsageItems = [
  {
    usage_id: 'usage-1',
    session_id: 'session-1',
    provider_name: 'openai',
    asset_type: 'portrait',
    operation: 'generate',
    estimated_cost_usd: 0.02,
    actual_cost_usd: 0.019,
    status: 'success',
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    usage_id: 'usage-2',
    session_id: 'session-1',
    provider_name: 'mock',
    asset_type: 'scene',
    operation: 'generate',
    estimated_cost_usd: 0.01,
    actual_cost_usd: undefined,
    status: 'pending',
    created_at: '2024-01-01T00:01:00Z',
  },
];

const mockSummary = {
  total_estimated: 0.03,
  total_actual: 0.019,
  count: 2,
};

describe('AssetUsageViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetDebugUsage.mockReturnValue(new Promise(() => {}));
    mockGetDebugUsageSummary.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<AssetUsageViewer />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders usage table when loaded', async () => {
    mockGetDebugUsage.mockResolvedValue({ total: 2, items: mockUsageItems });
    mockGetDebugUsageSummary.mockResolvedValue(mockSummary);
    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText(/usage-1/)).toBeInTheDocument();
      expect(screen.getByText(/usage-2/)).toBeInTheDocument();
    });
  });

  it('shows cost summary row', async () => {
    mockGetDebugUsage.mockResolvedValue({ total: 2, items: mockUsageItems });
    mockGetDebugUsageSummary.mockResolvedValue(mockSummary);
    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText(/\$0.030000/)).toBeInTheDocument();
      const actualCosts = screen.getAllByText(/\$0.019000/);
      expect(actualCosts.length).toBeGreaterThan(0);
    });
  });

  it('filters by session ID', async () => {
    mockGetDebugUsage.mockResolvedValue({ total: 1, items: [mockUsageItems[0]] });
    mockGetDebugUsageSummary.mockResolvedValue({ total_estimated: 0.02, total_actual: 0.019, count: 1 });

    renderWithIntl(<AssetUsageViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(mockGetDebugUsage).toHaveBeenCalledWith(0, 100, 'session-1');
    });
  });

  it('shows empty table when no usage', async () => {
    mockGetDebugUsage.mockResolvedValue({ total: 0, items: [] });
    mockGetDebugUsageSummary.mockResolvedValue({ total_estimated: 0, total_actual: 0, count: 0 });
    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText(/使用日志/)).toBeInTheDocument();
      expect(screen.getByText(/\(0\)/)).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetDebugUsage.mockRejectedValue(error);
    mockGetDebugUsageSummary.mockRejectedValue(error);

    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows admin required message on 403', async () => {
    const error = new Error('Forbidden') as Error & { status?: number };
    error.status = 403;
    mockGetDebugUsage.mockRejectedValue(error);
    mockGetDebugUsageSummary.mockRejectedValue(error);

    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText('需要管理员权限')).toBeInTheDocument();
    });
  });

  it('displays status badges', async () => {
    mockGetDebugUsage.mockResolvedValue({ total: 2, items: mockUsageItems });
    mockGetDebugUsageSummary.mockResolvedValue(mockSummary);
    renderWithIntl(<AssetUsageViewer />);

    await waitFor(() => {
      expect(screen.getByText('success')).toBeInTheDocument();
      expect(screen.getByText('pending')).toBeInTheDocument();
    });
  });
});
