'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getDebugRateLimitEvents } from '@/lib/api';
import type { RateLimitEventResponse } from '@/types/api';

interface RateLimitViewerProps {
  userId?: string;
}

export function RateLimitViewer({ userId }: RateLimitViewerProps) {
  const t = useTranslations('Debug');
  const [events, setEvents] = useState<RateLimitEventResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterUserId, setFilterUserId] = useState('');

  const fetchEvents = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const effectiveUserId = filterUserId || userId;
      const result = await getDebugRateLimitEvents(0, 100, effectiveUserId);
      setEvents(result.items);
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
      await fetchEvents();
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [userId, filterUserId, t]);

  const handleRetryFetch = async () => {
    await fetchEvents();
  };

  if (isLoading && events.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && events.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetryFetch} />;
  }

  if (events.length === 0) {
    return <DebugEmptyState message={t('emptyState.noRateLimitEvents')} />;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-4 mb-4">
          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200">
            {t('rateLimitEvents')} ({total})
          </h3>
          <input
            type="text"
            value={filterUserId}
            onChange={(e) => setFilterUserId(e.target.value)}
            placeholder={t('filterByUser')}
            className="flex-1 px-3 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded-lg dark:bg-slate-800 dark:text-slate-200"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('userId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('sessionId')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('provider')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('bucketKey')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('limitType')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('allowed')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('limitValue')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('currentValue')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('resetAt')}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id} className="border-b border-slate-100 dark:border-slate-800">
                  <td className="p-2 font-mono text-xs">{event.user_id ? `${event.user_id.slice(0, 8)}...` : '-'}</td>
                  <td className="p-2 font-mono text-xs">{event.session_id ? `${event.session_id.slice(0, 8)}...` : '-'}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{event.provider_name}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400 max-w-[150px] truncate">{event.bucket_key}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{event.limit_type}</td>
                  <td className="p-2">
                    {event.allowed ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
                        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                        {t('allowed')}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300">
                        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                        </svg>
                        {t('denied')}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{event.limit_value}</td>
                  <td className="p-2 text-xs text-slate-600 dark:text-slate-400">{event.current_value}</td>
                  <td className="p-2 text-xs text-slate-500">
                    {new Date(event.reset_at).toLocaleString()}
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
