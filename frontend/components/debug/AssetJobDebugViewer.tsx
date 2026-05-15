'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { listDebugAssetJobs, retryDebugAssetJob, cancelDebugAssetJob } from '@/lib/api';
import type { AssetJobResponse } from '@/types/api';

interface AssetJobDebugViewerProps {
  sessionId?: string;
}

export function AssetJobDebugViewer({ sessionId }: AssetJobDebugViewerProps) {
  const t = useTranslations('Debug');
  const [jobs, setJobs] = useState<AssetJobResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchJobs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await listDebugAssetJobs(0, 100);
      setJobs(result.jobs);
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
  };

  useEffect(() => {
    let cancelled = false;
    
    async function load() {
      if (cancelled) return;
      await fetchJobs();
    }
    
    load();
    
    return () => {
      cancelled = true;
    };
  }, [sessionId, t]);

  const handleRetry = async (jobId: string) => {
    setActionLoading(jobId);
    try {
      const updated = await retryDebugAssetJob(jobId);
      setJobs(jobs.map(j => j.job_id === jobId ? updated : j));
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
      setJobs(jobs.map(j => j.job_id === jobId ? updated : j));
    } catch {
      setError(t('failedToLoad'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleRetryFetch = async () => {
    await fetchJobs();
  };

  if (isLoading && jobs.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && jobs.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetryFetch} />;
  }

  if (jobs.length === 0) {
    return <DebugEmptyState message={t('emptyState.noJobs')} />;
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
      case 'processing':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300';
      case 'cancelled':
        return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
      default:
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300';
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

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="text-lg font-semibold mb-4 text-slate-800 dark:text-slate-200">
          {t('assetJobs')} ({total})
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('jobId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('type')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('status')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('provider')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('attempts')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('error')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('actions')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('created')}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="p-2 font-mono text-xs">{job.job_id.slice(0, 8)}...</td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getAssetTypeColor(job.asset_type)}`}>
                      {job.asset_type}
                    </span>
                  </td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(job.status)}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{job.provider_name || '-'}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">
                    {job.attempt_count}/{job.max_attempts}
                  </td>
                  <td className="p-2 text-xs text-red-600 dark:text-red-400 max-w-[200px] truncate">
                    {job.error_message || '-'}
                  </td>
                  <td className="p-2">
                    <div className="flex gap-2">
                      {job.status === 'failed' && (
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
                    </div>
                  </td>
                  <td className="p-2 text-xs text-slate-500">
                    {new Date(job.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
