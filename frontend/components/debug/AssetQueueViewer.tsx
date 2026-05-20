'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { listDebugAssetJobs, retryDebugAssetJob, cancelDebugAssetJob } from '@/lib/api';
import type { AssetJobResponse } from '@/types/api';

interface AssetJobWithLease extends AssetJobResponse {
  lease_owner?: string | null;
  dead_letter?: boolean;
}

interface AssetQueueViewerProps {
  sessionId?: string;
}

type StatusFilter = 'all' | 'pending' | 'processing' | 'failed' | 'dead_lettered';

const REFRESH_INTERVAL_MS = 10000;

export function AssetQueueViewer({ sessionId }: AssetQueueViewerProps) {
  const t = useTranslations('Debug');
  const [jobs, setJobs] = useState<AssetJobWithLease[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchJobs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await listDebugAssetJobs(0, 100);
      setJobs(result.jobs as AssetJobWithLease[]);
      setTotal(result.total);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  const mountedRef = useRef(false);

  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      fetchJobs();
    }
  }, [fetchJobs, sessionId]);

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchJobs, REFRESH_INTERVAL_MS);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [autoRefresh, fetchJobs]);

  const handleRetry = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const updated = await retryDebugAssetJob(jobId);
      setJobs(jobs.map(j => j.job_id === jobId ? (updated as AssetJobWithLease) : j));
    } catch {
      setError(t('failedToLoad'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancel = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const updated = await cancelDebugAssetJob(jobId);
      setJobs(jobs.map(j => j.job_id === jobId ? (updated as AssetJobWithLease) : j));
    } catch {
      setError(t('failedToLoad'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleViewDetails = (job: AssetJobWithLease) => {
    console.log('Job details:', job);
  };

  const handleRetryFetch = async () => {
    await fetchJobs();
  };

  const filteredJobs = jobs.filter(job => {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'dead_lettered') {
      return job.status === 'failed' && (job.dead_letter === true || job.attempt_count >= job.max_attempts);
    }
    return job.status === statusFilter;
  });

  const getStatusColor = (status: string, isDeadLettered?: boolean) => {
    if (isDeadLettered) {
      return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
    }
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
      case 'processing':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300';
      case 'pending':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300';
      case 'cancelled':
        return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
      default:
        return 'bg-gray-100 text-gray-700 dark:bg-gray-900 dark:text-gray-300';
    }
  };

  const getAssetTypeColor = (assetType: string) => {
    switch (assetType) {
      case 'portrait':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300';
      case 'scene':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
      case 'bgm':
        return 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300';
      default:
        return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
    }
  };

  const truncateId = (id: string) => {
    return id.length > 8 ? `${id.slice(0, 8)}...` : id;
  };

  const truncateError = (errorMsg: string | null | undefined) => {
    if (!errorMsg) return '-';
    return errorMsg.length > 30 ? `${errorMsg.slice(0, 30)}...` : errorMsg;
  };

  if (isLoading && jobs.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && jobs.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetryFetch} />;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">
            {t('assetJobs')} ({total})
          </h3>
          
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-slate-300 dark:border-slate-600"
              />
              <span className="text-slate-600 dark:text-slate-400">{t('autoRefresh')}</span>
            </label>

            <Button
              variant="outline"
              size="sm"
              onClick={fetchJobs}
              disabled={isLoading}
            >
              {isLoading ? t('refreshing') : t('refresh')}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 mb-4">
          {(['all', 'pending', 'processing', 'failed', 'dead_lettered'] as StatusFilter[]).map((filter) => (
            <button
              key={filter}
              onClick={() => setStatusFilter(filter)}
              className={`px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${
                statusFilter === filter
                  ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                  : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600'
              }`}
            >
              {t(`statusFilter.${filter}`)}
            </button>
          ))}
        </div>

        {filteredJobs.length === 0 ? (
          <DebugEmptyState message={t('emptyState.noJobs')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('jobId')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('type')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('status')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('provider')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('attempts')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('leaseOwner')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('error')}</th>
                  <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('actions')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredJobs.map((job) => {
                  const isDeadLettered = job.dead_letter === true || (job.status === 'failed' && job.attempt_count >= job.max_attempts);
                  
                  return (
                    <tr key={job.job_id} className="border-b border-slate-100 dark:border-slate-800">
                      <td className="p-2 font-mono text-xs" title={job.job_id}>
                        {truncateId(job.job_id)}
                      </td>
                      <td className="p-2">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getAssetTypeColor(job.asset_type)}`}>
                          {job.asset_type}
                        </span>
                      </td>
                      <td className="p-2">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(job.status, isDeadLettered)}`}>
                          {isDeadLettered ? 'dead_lettered' : job.status}
                        </span>
                      </td>
                      <td className="p-2 text-xs text-slate-600 dark:text-slate-400">
                        {job.provider_name || '-'}
                      </td>
                      <td className="p-2 text-xs text-slate-600 dark:text-slate-400">
                        {job.attempt_count}/{job.max_attempts}
                      </td>
                      <td className="p-2 text-xs text-slate-600 dark:text-slate-400">
                        {job.lease_owner || '-'}
                      </td>
                      <td className="p-2 text-xs text-red-600 dark:text-red-400 max-w-[200px] truncate" title={job.error_message || undefined}>
                        {truncateError(job.error_message)}
                      </td>
                      <td className="p-2">
                        <div className="flex gap-2">
                          {job.status === 'failed' && !isDeadLettered && (
                            <button
                              onClick={() => handleRetry(job.job_id)}
                              disabled={actionLoading === job.job_id}
                              className="px-2 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
                            >
                              {actionLoading === job.job_id ? '...' : t('retry')}
                            </button>
                          )}
                          {job.status === 'pending' && (
                            <button
                              onClick={() => handleCancel(job.job_id)}
                              disabled={actionLoading === job.job_id}
                              className="px-2 py-1 text-xs bg-slate-500 text-white rounded hover:bg-slate-600 disabled:opacity-50"
                            >
                              {actionLoading === job.job_id ? '...' : t('cancel')}
                            </button>
                          )}
                          <button
                            onClick={() => handleViewDetails(job)}
                            className="px-2 py-1 text-xs bg-slate-200 text-slate-700 rounded hover:bg-slate-300 dark:bg-slate-600 dark:text-slate-200 dark:hover:bg-slate-500"
                          >
                            {t('viewDetails')}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
