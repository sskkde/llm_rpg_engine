'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getDebugUsage, getDebugUsageSummary } from '@/lib/api';
import type { UsageLogResponse, CostSummaryResponse } from '@/types/api';

interface AssetUsageViewerProps {
  sessionId?: string;
}

export function AssetUsageViewer({ sessionId }: AssetUsageViewerProps) {
  const t = useTranslations('Debug');
  const [usage, setUsage] = useState<UsageLogResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<CostSummaryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterSessionId, setFilterSessionId] = useState('');

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const effectiveSessionId = filterSessionId || sessionId;
      const [usageResult, summaryResult] = await Promise.all([
        getDebugUsage(0, 100, effectiveSessionId),
        getDebugUsageSummary(effectiveSessionId),
      ]);
      setUsage(usageResult.items);
      setTotal(usageResult.total);
      setSummary(summaryResult);
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
      await fetchData();
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [sessionId, filterSessionId, t]);

  const handleRetryFetch = async () => {
    await fetchData();
  };

  if (isLoading && usage.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && usage.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetryFetch} />;
  }

  if (usage.length === 0 && !summary) {
    return <DebugEmptyState message={t('emptyState.noUsage')} />;
  }

  const formatCost = (cost: number | undefined | null) => {
    if (cost === undefined || cost === null) return '-';
    return `$${cost.toFixed(6)}`;
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-4 mb-4">
          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">
            {t('usageLogs')} ({total})
          </h3>
          <input
            type="text"
            value={filterSessionId}
            onChange={(e) => setFilterSessionId(e.target.value)}
            placeholder={t('filterBySession')}
            className="flex-1 px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg dark:bg-slate-800 dark:text-slate-200"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('usageId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('sessionId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('provider')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('assetType')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('operation')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('estimatedCost')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('actualCost')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('status')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('created')}</th>
              </tr>
            </thead>
            <tbody>
              {usage.map((item) => (
                <tr key={item.usage_id} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="p-2 font-mono text-xs">{item.usage_id.slice(0, 8)}...</td>
                  <td className="p-2 font-mono text-xs">{item.session_id ? `${item.session_id.slice(0, 8)}...` : '-'}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{item.provider_name}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{item.asset_type || '-'}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{item.operation}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{formatCost(item.estimated_cost_usd)}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{formatCost(item.actual_cost_usd)}</td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      item.status === 'success'
                        ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                        : item.status === 'failed'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                        : 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300'
                    }`}>
                      {item.status || '-'}
                    </span>
                  </td>
                  <td className="p-2 text-xs text-slate-500">
                    {new Date(item.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {summary && (
          <div className="mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-6 text-sm">
              <span className="text-slate-600 dark:text-slate-400">
                {t('totalEstimated')}: <strong className="text-slate-800 dark:text-slate-200">{formatCost(summary.total_estimated)}</strong>
              </span>
              <span className="text-slate-600 dark:text-slate-400">
                {t('totalActual')}: <strong className="text-slate-800 dark:text-slate-200">{formatCost(summary.total_actual)}</strong>
              </span>
              <span className="text-slate-600 dark:text-slate-400">
                {t('totalCount')}: <strong className="text-slate-800 dark:text-slate-200">{summary.count}</strong>
              </span>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
