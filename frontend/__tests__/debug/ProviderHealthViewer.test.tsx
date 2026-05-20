import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { ProviderHealthViewer } from '@/components/debug/ProviderHealthViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetDebugProviders = api.getDebugProviders as jest.MockedFunction<typeof api.getDebugProviders>;
const mockGetDebugProviderHealth = api.getDebugProviderHealth as jest.MockedFunction<typeof api.getDebugProviderHealth>;

const mockProviders = [
  {
    provider_name: 'openai',
    supported_asset_types: ['portrait', 'scene'],
    enabled: true,
    requires_api_key: true,
    configured: true,
    supports_async: true,
    supports_cancel: true,
    supports_cost_estimate: true,
  },
  {
    provider_name: 'mock',
    supported_asset_types: ['portrait', 'scene', 'bgm'],
    enabled: true,
    requires_api_key: false,
    configured: true,
    supports_async: false,
    supports_cancel: false,
    supports_cost_estimate: false,
  },
  {
    provider_name: 'disabled-provider',
    supported_asset_types: ['portrait'],
    enabled: false,
    requires_api_key: true,
    configured: false,
    supports_async: true,
    supports_cancel: false,
    supports_cost_estimate: true,
  },
];

describe('ProviderHealthViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetDebugProviders.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<ProviderHealthViewer />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders provider cards when loaded', async () => {
    mockGetDebugProviders.mockResolvedValue(mockProviders);
    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeInTheDocument();
      expect(screen.getByText('mock')).toBeInTheDocument();
      expect(screen.getByText('disabled-provider')).toBeInTheDocument();
    });
  });

  it('shows configured status badge', async () => {
    mockGetDebugProviders.mockResolvedValue(mockProviders);
    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      const configuredBadges = screen.getAllByText('已配置');
      expect(configuredBadges.length).toBe(2);
    });
  });

  it('shows green dot for enabled providers', async () => {
    mockGetDebugProviders.mockResolvedValue(mockProviders);
    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeInTheDocument();
    });
  });

  it('shows red dot for disabled providers', async () => {
    mockGetDebugProviders.mockResolvedValue(mockProviders);
    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('disabled-provider')).toBeInTheDocument();
    });
  });

  it('shows empty state when no providers', async () => {
    mockGetDebugProviders.mockResolvedValue([]);
    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('暂无提供商')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetDebugProviders.mockRejectedValue(error);

    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('health check button works', async () => {
    mockGetDebugProviders.mockResolvedValue(mockProviders);
    mockGetDebugProviderHealth.mockResolvedValue({
      configured: true,
      enabled: true,
      last_error: undefined,
    });

    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeInTheDocument();
    });

    const healthCheckButtons = screen.getAllByText('检查健康状态');
    fireEvent.click(healthCheckButtons[0]);

    await waitFor(() => {
      expect(mockGetDebugProviderHealth).toHaveBeenCalledWith('openai');
    });
  });

  it('displays health check result', async () => {
    mockGetDebugProviders.mockResolvedValue([mockProviders[0]]);
    mockGetDebugProviderHealth.mockResolvedValue({
      configured: true,
      enabled: true,
      last_error: undefined,
    });

    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeInTheDocument();
    });

    const healthCheckButton = screen.getByText('检查健康状态');
    fireEvent.click(healthCheckButton);

    await waitFor(() => {
      expect(screen.getByText('健康')).toBeInTheDocument();
    });
  });

  it('displays health check error', async () => {
    mockGetDebugProviders.mockResolvedValue([mockProviders[0]]);
    mockGetDebugProviderHealth.mockResolvedValue({
      configured: false,
      enabled: false,
      last_error: 'API key not configured',
    });

    renderWithIntl(<ProviderHealthViewer />);

    await waitFor(() => {
      expect(screen.getByText('openai')).toBeInTheDocument();
    });

    const healthCheckButton = screen.getByText('检查健康状态');
    fireEvent.click(healthCheckButton);

    await waitFor(() => {
      expect(screen.getByText('API key not configured')).toBeInTheDocument();
    });
  });
});
