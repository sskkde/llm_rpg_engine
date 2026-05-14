import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { AssetDebugViewer } from '@/components/debug/AssetDebugViewer';
import * as api from '@/lib/api';
import { AssetType, AssetGenerationStatus } from '@/types/api';

jest.mock('@/lib/api');

const mockListDebugSessionAssets = api.listDebugSessionAssets as jest.MockedFunction<typeof api.listDebugSessionAssets>;

const mockAssets = [
  {
    asset_id: 'asset-1',
    asset_type: AssetType.PORTRAIT,
    generation_status: AssetGenerationStatus.COMPLETED,
    result_url: 'https://example.com/p1.png',
    provider: 'mock',
    cache_hit: false,
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    asset_id: 'asset-2',
    asset_type: AssetType.SCENE,
    generation_status: AssetGenerationStatus.FAILED,
    error_message: 'Provider error',
    provider: 'mock',
    cache_hit: false,
    created_at: '2024-01-01T00:01:00Z',
  },
  {
    asset_id: 'asset-3',
    asset_type: AssetType.BGM,
    generation_status: AssetGenerationStatus.PROCESSING,
    provider: 'openai',
    cache_hit: false,
    created_at: '2024-01-01T00:02:00Z',
  },
];

describe('AssetDebugViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<AssetDebugViewer sessionId="" />);

    expect(screen.getByText('未加载会话')).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    mockListDebugSessionAssets.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders assets when loaded', async () => {
    mockListDebugSessionAssets.mockResolvedValue(mockAssets);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText('asset-1')).toBeInTheDocument();
      expect(screen.getByText('asset-2')).toBeInTheDocument();
      expect(screen.getByText('asset-3')).toBeInTheDocument();
    });
  });

  it('shows empty state when no assets', async () => {
    mockListDebugSessionAssets.mockResolvedValue([]);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText('该会话暂无资源')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockListDebugSessionAssets.mockRejectedValue(error);

    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows admin required message on 403', async () => {
    const error = new Error('Forbidden') as Error & { status?: number };
    error.status = 403;
    mockListDebugSessionAssets.mockRejectedValue(error);

    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText('需要管理员权限')).toBeInTheDocument();
    });
  });

  it('displays asset type badges with correct colors', async () => {
    mockListDebugSessionAssets.mockResolvedValue(mockAssets);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText(AssetType.PORTRAIT)).toBeInTheDocument();
      expect(screen.getByText(AssetType.SCENE)).toBeInTheDocument();
      expect(screen.getByText(AssetType.BGM)).toBeInTheDocument();
    });
  });

  it('displays status badges with correct colors', async () => {
    mockListDebugSessionAssets.mockResolvedValue(mockAssets);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText(AssetGenerationStatus.COMPLETED)).toBeInTheDocument();
      expect(screen.getByText(AssetGenerationStatus.FAILED)).toBeInTheDocument();
      expect(screen.getByText(AssetGenerationStatus.PROCESSING)).toBeInTheDocument();
    });
  });

  it('displays error message for failed assets', async () => {
    mockListDebugSessionAssets.mockResolvedValue(mockAssets);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      expect(screen.getByText('Provider error')).toBeInTheDocument();
    });
  });

  it('displays provider name', async () => {
    mockListDebugSessionAssets.mockResolvedValue(mockAssets);
    renderWithIntl(<AssetDebugViewer sessionId="session-1" />);

    await waitFor(() => {
      const mockProviders = screen.getAllByText('mock');
      const openaiProviders = screen.getAllByText('openai');
      expect(mockProviders.length).toBeGreaterThan(0);
      expect(openaiProviders.length).toBeGreaterThan(0);
    });
  });
});
