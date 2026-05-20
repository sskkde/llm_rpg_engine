'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getDebugProviders, getDebugProviderHealth } from '@/lib/api';
import type { ProviderCapabilityResponse, ProviderHealthResponse } from '@/types/api';

export function ProviderHealthViewer() {
  const t = useTranslations('Debug');
  const [providers, setProviders] = useState<ProviderCapabilityResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [healthChecks, setHealthChecks] = useState<Record<string, ProviderHealthResponse>>({});
  const [checkingProvider, setCheckingProvider] = useState<string | null>(null);

  const fetchProviders = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await getDebugProviders();
      setProviders(result);
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
      await fetchProviders();
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleHealthCheck = async (providerName: string) => {
    setCheckingProvider(providerName);
    try {
      const health = await getDebugProviderHealth(providerName);
      setHealthChecks((prev) => ({ ...prev, [providerName]: health }));
    } catch {
      setHealthChecks((prev) => ({
        ...prev,
        [providerName]: { configured: false, enabled: false, last_error: t('healthCheckFailed') },
      }));
    } finally {
      setCheckingProvider(null);
    }
  };

  const handleRetryFetch = async () => {
    await fetchProviders();
  };

  if (isLoading && providers.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && providers.length === 0) {
    return <ErrorMessage message={error} variant="card" onRetry={handleRetryFetch} />;
  }

  if (providers.length === 0) {
    return <DebugEmptyState message={t('emptyState.noProviders')} />;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="text-lg font-semibold mb-4 text-slate-800 dark:text-slate-200">
          {t('providers')} ({providers.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {providers.map((provider) => {
            const health = healthChecks[provider.provider_name];
            return (
              <div
                key={provider.provider_name}
                className="p-4 border border-slate-200 dark:border-slate-700 rounded-lg"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2.5 h-2.5 rounded-full ${
                        provider.enabled
                          ? 'bg-green-500'
                          : 'bg-red-500'
                      }`}
                    />
                    <h4 className="font-medium text-slate-800 dark:text-slate-200">
                      {provider.provider_name}
                    </h4>
                  </div>
                  {provider.configured && (
                    <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 rounded">
                      {t('configured')}
                    </span>
                  )}
                </div>
                <div className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
                  <div className="flex flex-wrap gap-1">
                    {provider.supported_asset_types.map((type) => (
                      <span
                        key={type}
                        className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 rounded"
                      >
                        {type}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span>{provider.supports_async ? 'Async' : 'Sync'}</span>
                    <span>|</span>
                    <span>{provider.supports_cancel ? 'Cancelable' : 'Not Cancelable'}</span>
                    <span>|</span>
                    <span>{provider.supports_cost_estimate ? 'Cost Est.' : 'No Cost Est.'}</span>
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
                  <button
                    onClick={() => handleHealthCheck(provider.provider_name)}
                    disabled={checkingProvider === provider.provider_name}
                    className="w-full px-3 py-1.5 text-xs bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded hover:bg-slate-200 dark:hover:bg-slate-700 disabled:opacity-50"
                  >
                    {checkingProvider === provider.provider_name ? t('checking') : t('checkHealth')}
                  </button>
                  {health && (
                    <div className="mt-2 text-xs space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            health.enabled && health.configured
                              ? 'bg-green-500'
                              : 'bg-red-500'
                          }`}
                        />
                        <span className="text-slate-600 dark:text-slate-400">
                          {health.enabled && health.configured ? t('healthy') : t('unhealthy')}
                        </span>
                      </div>
                      {health.last_error && (
                        <p className="text-red-600 dark:text-red-400 truncate">{health.last_error}</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
