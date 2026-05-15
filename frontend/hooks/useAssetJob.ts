'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { getAssetJob, retryAssetJob, cancelAssetJob } from '@/lib/api';
import type { AssetJobResponse } from '@/types/api';

const POLL_INTERVAL_MS = 2000;

interface UseAssetJobOptions {
  jobId: string | null;
  pollInterval?: number;
  onCompleted?: (job: AssetJobResponse) => void;
  onFailed?: (job: AssetJobResponse) => void;
}

interface UseAssetJobReturn {
  job: AssetJobResponse | null;
  isLoading: boolean;
  error: string | null;
  isPolling: boolean;
  retry: () => Promise<void>;
  cancel: () => Promise<void>;
  refetch: () => Promise<void>;
}

export function useAssetJob({ jobId, pollInterval = POLL_INTERVAL_MS, onCompleted, onFailed }: UseAssetJobOptions): UseAssetJobReturn {
  const [job, setJob] = useState<AssetJobResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompletedRef = useRef(onCompleted);
  const onFailedRef = useRef(onFailed);
  
  onCompletedRef.current = onCompleted;
  onFailedRef.current = onFailed;

  const fetchJob = useCallback(async () => {
    if (!jobId) return;
    try {
      const result = await getAssetJob(jobId);
      setJob(result);
      setError(null);

      if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') {
        setIsPolling(false);
        if (result.status === 'completed' && onCompletedRef.current) {
          onCompletedRef.current(result);
        }
        if (result.status === 'failed' && onFailedRef.current) {
          onFailedRef.current(result);
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to fetch job status';
      setError(message);
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId || !isPolling) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }

    fetchJob();

    pollRef.current = setInterval(fetchJob, pollInterval);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [jobId, isPolling, pollInterval, fetchJob]);

  useEffect(() => {
    if (jobId) {
      setIsPolling(true);
    }
    return () => {
      setIsPolling(false);
    };
  }, [jobId]);

  const retry = useCallback(async () => {
    if (!jobId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await retryAssetJob(jobId);
      setJob(result);
      setIsPolling(true);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to retry job';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  const cancel = useCallback(async () => {
    if (!jobId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await cancelAssetJob(jobId);
      setJob(result);
      setIsPolling(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to cancel job';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (jobId) {
        const result = await getAssetJob(jobId);
        setJob(result);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to fetch job status';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  return { job, isLoading, error, isPolling, retry, cancel, refetch };
}
