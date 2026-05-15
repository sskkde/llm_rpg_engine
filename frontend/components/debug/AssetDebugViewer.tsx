'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { listDebugSessionAssets } from '@/lib/api';
import type { AssetResponse } from '@/types/api';

interface AssetDebugViewerProps {
  sessionId: string;
}

export function AssetDebugViewer({ sessionId }: AssetDebugViewerProps) {
  const t = useTranslations('Debug');
  const [assets, setAssets] = useState<AssetResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId.trim()) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();

    async function fetchAssets() {
      setIsLoading(true);
      setError(null);
      try {
        const result = await listDebugSessionAssets(sessionId);
        if (!cancelled) {
          setAssets(result);
        }
      } catch (err: unknown) {
        if (cancelled) return;
        const status = (err as { status?: number })?.status;
        if (status === 401 || status === 403) {
          setError(t('adminRequired'));
        } else {
          setError(t('failedToLoad'));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    fetchAssets();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [sessionId, t]);

  const handleRetry = async () => {
    if (!sessionId.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await listDebugSessionAssets(sessionId);
      setAssets(result);
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

  if (!sessionId.trim()) {
    return <DebugEmptyState message={t('emptyState.noSession')} />;
  }

  if (isLoading && assets.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && assets.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetry} />;
  }

  if (assets.length === 0) {
    return <DebugEmptyState message={t('emptyState.noAssets')} />;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="text-lg font-semibold mb-4 text-slate-800 dark:text-slate-200">
          {t('assets')} ({assets.length})
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('assetId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('type')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('status')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('provider')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('error')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('created')}</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.asset_id} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="p-2 font-mono text-xs">{asset.asset_id}</td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      asset.asset_type === 'portrait' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300' :
                      asset.asset_type === 'scene' ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' :
                      'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
                    }`}>
                      {asset.asset_type}
                    </span>
                  </td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                      asset.generation_status === 'completed' ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' :
                      asset.generation_status === 'failed' ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300' :
                      asset.generation_status === 'processing' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300' :
                      'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300'
                    }`}>
                      {asset.generation_status}
                    </span>
                  </td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{asset.provider || '-'}</td>
                  <td className="p-2 text-xs text-red-600 dark:text-red-400 max-w-[200px] truncate">{asset.error_message || '-'}</td>
                  <td className="p-2 text-xs text-slate-500">{new Date(asset.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
