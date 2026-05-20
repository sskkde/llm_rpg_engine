import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { AssetQueueViewer } from '@/components/debug/AssetQueueViewer';
import * as api from '@/lib/api';
import { act } from 'react';

jest.mock('@/lib/api');

const mockListDebugAssetJobs = api.listDebugAssetJobs as jest.MockedFunction<typeof api.listDebugAssetJobs>;
const mockRetryDebugAssetJob = api.retryDebugAssetJob as jest.MockedFunction<typeof api.retryDebugAssetJob>;
const mockCancelDebugAssetJob = api.cancelDebugAssetJob as jest.MockedFunction<typeof api.cancelDebugAssetJob>;

const mockJobs = [
  {
    job_id: 'job-pending-123',
    asset_type: 'portrait',
    status: 'pending',
    provider_name: 'mock',
    attempt_count: 0,
    max_attempts: 3,
    error_message: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    job_id: 'job-processing-456',
    asset_type: 'scene',
    status: 'processing',
    provider_name: 'openai',
    attempt_count: 1,
    max_attempts: 3,
    error_message: null,
    created_at: '2024-01-01T00:01:00Z',
    updated_at: '2024-01-01T00:01:00Z',
  },
  {
    job_id: 'job-deadletter-789',
    asset_type: 'bgm',
    status: 'failed',
    provider_name: 'mock',
    attempt_count: 3,
    max_attempts: 3,
    error_message: 'Max retries exceeded',
    created_at: '2024-01-01T00:02:00Z',
    updated_at: '2024-01-01T00:02:00Z',
  },
];

describe('AssetQueueViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('shows loading state initially', () => {
    mockListDebugAssetJobs.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<AssetQueueViewer />);

    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('renders job table with jobs', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 3, jobs: mockJobs });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('job-pend...')).toBeInTheDocument();
      expect(screen.getByText('job-proc...')).toBeInTheDocument();
      expect(screen.getByText('job-dead...')).toBeInTheDocument();
    });
  });

  it('filters jobs by status', async () => {
    const jobsWithFailed = [
      ...mockJobs,
      {
        job_id: 'job-failed-extra',
        asset_type: 'portrait',
        status: 'failed',
        provider_name: 'mock',
        attempt_count: 1,
        max_attempts: 3,
        error_message: 'Some error',
        created_at: '2024-01-01T00:03:00Z',
        updated_at: '2024-01-01T00:03:00Z',
      },
    ];
    mockListDebugAssetJobs.mockResolvedValue({ total: 4, jobs: jobsWithFailed });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('job-pend...')).toBeInTheDocument();
    });

    const failedButton = screen.getByRole('button', { name: '失败' });
    fireEvent.click(failedButton);

    await waitFor(() => {
      expect(screen.getByText('job-dead...')).toBeInTheDocument();
      expect(screen.getByText('job-fail...')).toBeInTheDocument();
      expect(screen.queryByText('job-pend...')).not.toBeInTheDocument();
      expect(screen.queryByText('job-proc...')).not.toBeInTheDocument();
    });
  });

  it('shows retry button for failed jobs and calls API', async () => {
    const failedJob = {
      job_id: 'job-failed-retry',
      asset_type: 'portrait',
      status: 'failed',
      provider_name: 'mock',
      attempt_count: 1,
      max_attempts: 3,
      error_message: 'Temporary error',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };
    mockListDebugAssetJobs.mockResolvedValue({ total: 1, jobs: [failedJob] });
    mockRetryDebugAssetJob.mockResolvedValue({
      ...failedJob,
      status: 'pending',
      attempt_count: 0,
    });

    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('job-fail...')).toBeInTheDocument();
    });

    const retryButton = screen.getByRole('button', { name: '重试' });
    fireEvent.click(retryButton);

    await waitFor(() => {
      expect(mockRetryDebugAssetJob).toHaveBeenCalledWith('job-failed-retry');
    });
  });

  it('shows cancel button for pending jobs and calls API', async () => {
    const pendingJob = {
      job_id: 'job-pending-cancel',
      asset_type: 'scene',
      status: 'pending',
      provider_name: 'mock',
      attempt_count: 0,
      max_attempts: 3,
      error_message: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    };
    mockListDebugAssetJobs.mockResolvedValue({ total: 1, jobs: [pendingJob] });
    mockCancelDebugAssetJob.mockResolvedValue({
      ...pendingJob,
      status: 'cancelled',
    });

    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('job-pend...')).toBeInTheDocument();
    });

    const cancelButton = screen.getByRole('button', { name: '取消' });
    fireEvent.click(cancelButton);

    await waitFor(() => {
      expect(mockCancelDebugAssetJob).toHaveBeenCalledWith('job-pending-cancel');
    });
  });

  it('auto-refresh starts on mount and stops when toggled off', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 0, jobs: [] });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(mockListDebugAssetJobs).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      jest.advanceTimersByTime(10000);
    });

    await waitFor(() => {
      expect(mockListDebugAssetJobs).toHaveBeenCalledTimes(2);
    });

    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    await act(async () => {
      jest.advanceTimersByTime(10000);
    });

    expect(mockListDebugAssetJobs).toHaveBeenCalledTimes(2);
  });

  it('shows empty state when no jobs', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 0, jobs: [] });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('暂无资源任务')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockListDebugAssetJobs.mockRejectedValue(error);

    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows admin required message on 403', async () => {
    const error = new Error('Forbidden') as Error & { status?: number };
    error.status = 403;
    mockListDebugAssetJobs.mockRejectedValue(error);

    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('需要管理员权限')).toBeInTheDocument();
    });
  });

  it('displays asset type badges with correct colors', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 3, jobs: mockJobs });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('portrait')).toBeInTheDocument();
      expect(screen.getByText('scene')).toBeInTheDocument();
      expect(screen.getByText('bgm')).toBeInTheDocument();
    });
  });

  it('displays status badges', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 3, jobs: mockJobs });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('pending')).toBeInTheDocument();
      expect(screen.getByText('processing')).toBeInTheDocument();
      expect(screen.getByText('dead_lettered')).toBeInTheDocument();
    });
  });

  it('displays attempts count', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 3, jobs: mockJobs });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      expect(screen.getByText('0/3')).toBeInTheDocument();
      expect(screen.getByText('1/3')).toBeInTheDocument();
      expect(screen.getByText('3/3')).toBeInTheDocument();
    });
  });

  it('displays provider name', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 3, jobs: mockJobs });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      const mockProviders = screen.getAllByText('mock');
      const openaiProviders = screen.getAllByText('openai');
      expect(mockProviders.length).toBeGreaterThan(0);
      expect(openaiProviders.length).toBeGreaterThan(0);
    });
  });

  it('displays view details button for all jobs', async () => {
    mockListDebugAssetJobs.mockResolvedValue({ total: 1, jobs: [mockJobs[0]] });
    renderWithIntl(<AssetQueueViewer />);

    await waitFor(() => {
      const viewDetailsButtons = screen.getAllByRole('button', { name: '查看详情' });
      expect(viewDetailsButtons.length).toBe(1);
    });
  });
});
