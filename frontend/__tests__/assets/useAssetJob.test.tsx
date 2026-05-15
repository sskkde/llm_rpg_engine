import { renderHook, act, waitFor } from '@testing-library/react';
import { useAssetJob } from '@/hooks/useAssetJob';
import * as api from '@/lib/api';
import type { AssetJobResponse } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getAssetJob: jest.fn(),
  retryAssetJob: jest.fn(),
  cancelAssetJob: jest.fn(),
}));

const mockJob: AssetJobResponse = {
  job_id: 'job-1',
  asset_type: 'portrait',
  status: 'pending',
  attempt_count: 0,
  max_attempts: 3,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

describe('useAssetJob', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('starts polling when jobId is provided', async () => {
    (api.getAssetJob as jest.Mock).mockResolvedValue({ ...mockJob, status: 'processing' });

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    expect(result.current.isPolling).toBe(true);

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalledWith('job-1');
    });
  });

  it('stops polling when status is completed', async () => {
    const completedJob = { ...mockJob, status: 'completed' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(completedJob);

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(result.current.job?.status).toBe('completed');
    });

    expect(result.current.isPolling).toBe(false);
  });

  it('stops polling when status is failed', async () => {
    const failedJob = { ...mockJob, status: 'failed' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(failedJob);

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(result.current.job?.status).toBe('failed');
    });

    expect(result.current.isPolling).toBe(false);
  });

  it('calls onCompleted callback when job completes', async () => {
    const completedJob = { ...mockJob, status: 'completed' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(completedJob);
    const onCompleted = jest.fn();

    renderHook(() => useAssetJob({ jobId: 'job-1', onCompleted }));

    await waitFor(() => {
      expect(onCompleted).toHaveBeenCalledWith(completedJob);
    });
  });

  it('calls onFailed callback when job fails', async () => {
    const failedJob = { ...mockJob, status: 'failed', error_message: 'Test error' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(failedJob);
    const onFailed = jest.fn();

    renderHook(() => useAssetJob({ jobId: 'job-1', onFailed }));

    await waitFor(() => {
      expect(onFailed).toHaveBeenCalledWith(failedJob);
    });
  });

  it('retry function calls retryAssetJob and resumes polling', async () => {
    const retriedJob = { ...mockJob, status: 'pending' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(mockJob);
    (api.retryAssetJob as jest.Mock).mockResolvedValue(retriedJob);

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.retry();
    });

    expect(api.retryAssetJob).toHaveBeenCalledWith('job-1');
    expect(result.current.isPolling).toBe(true);
  });

  it('cancel function calls cancelAssetJob and stops polling', async () => {
    const cancelledJob = { ...mockJob, status: 'cancelled' };
    (api.getAssetJob as jest.Mock).mockResolvedValue(mockJob);
    (api.cancelAssetJob as jest.Mock).mockResolvedValue(cancelledJob);

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.cancel();
    });

    expect(api.cancelAssetJob).toHaveBeenCalledWith('job-1');
    expect(result.current.isPolling).toBe(false);
  });

  it('stops polling when component unmounts', async () => {
    (api.getAssetJob as jest.Mock).mockResolvedValue({ ...mockJob, status: 'processing' });

    const { unmount } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalled();
    });

    const callCountBeforeUnmount = (api.getAssetJob as jest.Mock).mock.calls.length;

    unmount();

    act(() => {
      jest.advanceTimersByTime(5000);
    });

    expect((api.getAssetJob as jest.Mock).mock.calls.length).toBe(callCountBeforeUnmount);
  });

  it('does not poll when jobId is null', async () => {
    const { result } = renderHook(() => useAssetJob({ jobId: null }));

    expect(result.current.isPolling).toBe(false);
    expect(api.getAssetJob).not.toHaveBeenCalled();

    act(() => {
      jest.advanceTimersByTime(5000);
    });

    expect(api.getAssetJob).not.toHaveBeenCalled();
  });

  it('refetch function fetches job status', async () => {
    (api.getAssetJob as jest.Mock).mockResolvedValue(mockJob);

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalled();
    });

    jest.clearAllMocks();

    await act(async () => {
      await result.current.refetch();
    });

    expect(api.getAssetJob).toHaveBeenCalledWith('job-1');
  });

  it('sets error when API call fails', async () => {
    (api.getAssetJob as jest.Mock).mockRejectedValue(new Error('API error'));

    const { result } = renderHook(() => useAssetJob({ jobId: 'job-1' }));

    await waitFor(() => {
      expect(result.current.error).toBe('API error');
    });
  });

  it('polls at specified interval', async () => {
    (api.getAssetJob as jest.Mock).mockResolvedValue({ ...mockJob, status: 'processing' });

    renderHook(() => useAssetJob({ jobId: 'job-1', pollInterval: 1000 }));

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalledTimes(1);
    });

    act(() => {
      jest.advanceTimersByTime(1000);
    });

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalledTimes(2);
    });

    act(() => {
      jest.advanceTimersByTime(1000);
    });

    await waitFor(() => {
      expect(api.getAssetJob).toHaveBeenCalledTimes(3);
    });
  });
});
