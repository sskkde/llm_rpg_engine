'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getValidationAudit } from '@/lib/api';
import type { ValidationResultAuditResponse, ValidationCheckResponse } from '@/types/api';

interface ValidationAuditViewerProps {
  sessionId: string;
  validationId: string;
}

export function ValidationAuditViewer({ sessionId, validationId }: ValidationAuditViewerProps) {
  const t = useTranslations('Debug');
  const [data, setData] = useState<ValidationResultAuditResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    if (!sessionId || !validationId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getValidationAudit(sessionId, validationId);
      setData(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else if (status === 404) {
        setError(t('validationNotFound'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  if (!sessionId || !validationId) {
    return <DebugEmptyState message={t('emptyState.noValidation')} />;
  }

  if (isLoading && !data) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error && !data) {
    return <ErrorMessage message={error} variant="card" onRetry={loadData} />;
  }

  if (!data) {
    return (
      <Card className="p-4">
        <button
          onClick={loadData}
          className="w-full py-2 px-4 bg-indigo-600 dark:bg-indigo-500 text-white rounded-lg hover:bg-indigo-700 dark:hover:bg-indigo-600 transition-colors"
        >
          {t('loadValidationAudit')}
        </button>
      </Card>
    );
  }

  const getStatusColorClasses = (status: string): string => {
    switch (status) {
      case 'passed':
        return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200 border-green-200 dark:border-green-800';
      case 'failed':
        return 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200 border-red-200 dark:border-red-800';
      case 'warning':
        return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-200 border-yellow-200 dark:border-yellow-800';
      default:
        return 'bg-slate-100 dark:bg-slate-900/30 text-slate-800 dark:text-slate-200 border-slate-200 dark:border-slate-800';
    }
  };

  const getStatusBadgeClasses = (status: string): string => {
    switch (status) {
      case 'passed':
        return 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100';
      case 'failed':
        return 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100';
      case 'warning':
        return 'bg-yellow-200 dark:bg-yellow-800 text-yellow-900 dark:text-yellow-100';
      default:
        return 'bg-slate-200 dark:bg-slate-800 text-slate-900 dark:text-slate-100';
    }
  };

  const renderCheckEntry = (check: ValidationCheckResponse, index: number) => {
    const statusColor = getStatusColorClasses(check.status);
    const badgeColor = getStatusBadgeClasses(check.status);

    return (
      <div
        key={index}
        className={`p-3 rounded-lg border ${statusColor} space-y-2`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${badgeColor}`}>
              {check.status.toUpperCase()}
            </span>
            <span className="font-mono text-xs text-slate-600 dark:text-slate-400">
              {check.check_type}
            </span>
          </div>
          <span className="font-mono text-xs text-slate-500 dark:text-slate-500">
            {check.check_id.slice(0, 12)}...
          </span>
        </div>

        {check.message && (
          <div className="text-sm text-slate-700 dark:text-slate-300">
            {check.message}
          </div>
        )}

        {check.details && Object.keys(check.details).length > 0 && (
          <div className="text-xs bg-slate-50 dark:bg-slate-800/50 p-2 rounded">
            <pre className="whitespace-pre-wrap text-slate-600 dark:text-slate-400">
              {JSON.stringify(check.details, null, 2)}
            </pre>
          </div>
        )}
      </div>
    );
  };

  const overallBadgeColor = getStatusBadgeClasses(data.overall_status);

  const checksByType: Record<string, ValidationCheckResponse[]> = {};
  for (const check of data.checks) {
    if (!checksByType[check.check_type]) {
      checksByType[check.check_type] = [];
    }
    checksByType[check.check_type].push(check);
  }

  const checkTypeLabels: Record<string, string> = {
    action_validity: t('checkType.actionValidity'),
    state_delta: t('checkType.stateDelta'),
    lore_consistency: t('checkType.loreConsistency'),
    perspective: t('checkType.perspective'),
    numerical: t('checkType.numerical'),
    quest: t('checkType.quest'),
    inventory: t('checkType.inventory'),
    location: t('checkType.location'),
    combat: t('checkType.combat'),
    narration_leak: t('checkType.narrationLeak'),
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {t('validationAuditTitle')}
        </h3>
        <button
          onClick={loadData}
          disabled={isLoading}
          className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline disabled:opacity-50"
        >
          {isLoading ? t('refreshing') : t('refresh')}
        </button>
      </div>

      {error && <ErrorMessage message={error} variant="inline" />}

      <Card className="p-4 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('validationId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.validation_id.slice(0, 12)}...
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('turnNo')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.turn_no}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('validationTarget')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.validation_target}</span>
          </div>
          {data.target_id && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">{t('targetId')}:</span>
              <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
                {data.target_id.slice(0, 8)}...
              </span>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm bg-slate-50 dark:bg-slate-700/50 p-3 rounded-lg">
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('overallStatus')}</span>
            <div className="mt-1">
              <span className={`px-3 py-1 rounded text-sm font-medium ${overallBadgeColor}`}>
                {data.overall_status.toUpperCase()}
              </span>
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('checkCount')}</span>
            <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {data.checks.length}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('errorCount')}</span>
            <div className="mt-1 text-lg font-semibold text-red-600 dark:text-red-400">
              {data.error_count}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('warningCount')}</span>
            <div className="mt-1 text-lg font-semibold text-yellow-600 dark:text-yellow-400">
              {data.warning_count}
            </div>
          </div>
        </div>

        {data.transaction_id && (
          <div className="text-sm">
            <span className="text-slate-500 dark:text-slate-400">{t('transactionId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.transaction_id}
            </span>
          </div>
        )}
      </Card>

      {data.errors.length > 0 && (
        <Card className="p-4">
          <h4 className="font-semibold text-red-800 dark:text-red-200 mb-2">
            {t('errors')} ({data.errors.length})
          </h4>
          <ul className="list-disc list-inside text-sm text-red-700 dark:text-red-300 space-y-1">
            {data.errors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </Card>
      )}

      {data.warnings.length > 0 && (
        <Card className="p-4">
          <h4 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-2">
            {t('warnings')} ({data.warnings.length})
          </h4>
          <ul className="list-disc list-inside text-sm text-yellow-700 dark:text-yellow-300 space-y-1">
            {data.warnings.map((warn, i) => (
              <li key={i}>{warn}</li>
            ))}
          </ul>
        </Card>
      )}

      {Object.entries(checksByType).map(([checkType, checks]) => (
        <CollapsibleSection
          key={checkType}
          title={checkTypeLabels[checkType] || checkType}
          summary={`${checks.length} ${t('checks')}`}
          defaultOpen={checks.some(c => c.status === 'failed')}
        >
          <div className="p-4 space-y-3">
            {checks.map((check, i) => renderCheckEntry(check, i))}
          </div>
        </CollapsibleSection>
      ))}

      <Card className="p-4">
        <div className="text-sm text-slate-500 dark:text-slate-400">
          {t('createdAt')}: {new Date(data.created_at).toLocaleString()}
        </div>
      </Card>
    </div>
  );
}
