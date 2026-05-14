'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getContextBuildAudit } from '@/lib/api';
import type { ContextBuildAuditResponse, MemoryAuditResponse } from '@/types/api';

interface ContextBuildAuditProps {
  sessionId: string;
  buildId: string;
}

export function ContextBuildAudit({ sessionId, buildId }: ContextBuildAuditProps) {
  const t = useTranslations('Debug');
  const [data, setData] = useState<ContextBuildAuditResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    if (!sessionId || !buildId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getContextBuildAudit(sessionId, buildId);
      setData(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else if (status === 404) {
        setError(t('contextBuildNotFound'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  if (!sessionId || !buildId) {
    return <DebugEmptyState message={t('emptyState.noContextBuild')} />;
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
          {t('loadContextBuildAudit')}
        </button>
      </Card>
    );
  }

  const getReasonColorClass = (reason: string): string => {
    if (reason.includes('included') || reason.includes('selected')) {
      return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200';
    }
    if (reason.includes('perspective') || reason.includes('conditional')) {
      return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-200';
    }
    return 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200';
  };

  const renderMemoryEntry = (memory: MemoryAuditResponse, index: number) => {
    const isIncluded = memory.included;
    const borderColor = isIncluded
      ? 'border-green-200 dark:border-green-800'
      : 'border-red-200 dark:border-red-800';
    const bgColor = isIncluded
      ? 'bg-green-50 dark:bg-green-900/20'
      : 'bg-red-50 dark:bg-red-900/20';

    const reasonColor = getReasonColorClass(memory.reason);

    return (
      <div
        key={index}
        className={`p-3 rounded-lg border ${borderColor} ${bgColor} space-y-2`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded text-xs font-medium ${isIncluded ? 'bg-green-200 dark:bg-green-800 text-green-900 dark:text-green-100' : 'bg-red-200 dark:bg-red-800 text-red-900 dark:text-red-100'}`}>
              {isIncluded ? t('included') : t('excluded')}
            </span>
            <span className="font-mono text-xs text-slate-600 dark:text-slate-400">
              {memory.memory_id.slice(0, 12)}...
            </span>
          </div>
          <span className={`px-2 py-1 rounded text-xs ${reasonColor}`}>
            {memory.reason}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('memoryType')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{memory.memory_type}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('ownerId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {memory.owner_id.slice(0, 8)}...
            </span>
          </div>
          {memory.relevance_score !== undefined && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">{t('relevanceScore')}:</span>
              <span className="ml-1 text-slate-700 dark:text-slate-300">
                {memory.relevance_score.toFixed(3)}
              </span>
            </div>
          )}
          {memory.importance_score !== undefined && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">{t('importanceScore')}:</span>
              <span className="ml-1 text-slate-700 dark:text-slate-300">
                {memory.importance_score.toFixed(3)}
              </span>
            </div>
          )}
          {memory.recency_score !== undefined && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">{t('recencyScore')}:</span>
              <span className="ml-1 text-slate-700 dark:text-slate-300">
                {memory.recency_score.toFixed(3)}
              </span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2 text-xs">
          {memory.perspective_filter_applied && (
            <span className="px-2 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300 rounded">
              {t('perspectiveFiltered')}
            </span>
          )}
          {memory.forbidden_knowledge_flag && (
            <span className="px-2 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded">
              {t('forbiddenKnowledge')}
            </span>
          )}
        </div>

        {memory.notes && (
          <div className="text-sm text-slate-600 dark:text-slate-400 italic">
            {memory.notes}
          </div>
        )}
      </div>
    );
  };

  const includedPercentage = data.total_candidates > 0
    ? ((data.included_count / data.total_candidates) * 100).toFixed(1)
    : '0.0';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {t('contextBuildAuditTitle')}
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
            <span className="text-slate-500 dark:text-slate-400">{t('buildId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.build_id.slice(0, 12)}...
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('turnNo')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.turn_no}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('perspectiveType')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.perspective_type}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('perspectiveId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.perspective_id.slice(0, 8)}...
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm bg-slate-50 dark:bg-slate-700/50 p-3 rounded-lg">
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('totalCandidates')}</span>
            <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {data.total_candidates}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('includedCount')}</span>
            <div className="mt-1 text-lg font-semibold text-green-600 dark:text-green-400">
              {data.included_count}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('excludedCount')}</span>
            <div className="mt-1 text-lg font-semibold text-red-600 dark:text-red-400">
              {data.excluded_count}
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('inclusionRate')}</span>
            <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {includedPercentage}%
            </div>
          </div>
          <div className="text-center">
            <span className="text-slate-500 dark:text-slate-400">{t('buildDuration')}</span>
            <div className="mt-1 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {data.build_duration_ms}ms
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('tokenCount')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.context_token_count}</span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('charCount')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">{data.context_char_count}</span>
          </div>
        </div>
      </Card>

      <CollapsibleSection
        title={t('includedMemories')}
        summary={`${data.included_memories.length} ${t('memories')}`}
        defaultOpen={true}
      >
        <div className="p-4 space-y-3">
          {data.included_memories.length > 0 ? (
            data.included_memories.map((memory, i) => renderMemoryEntry(memory, i))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noIncludedMemories')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('excludedMemories')}
        summary={`${data.excluded_memories.length} ${t('memories')}`}
        defaultOpen={data.excluded_memories.length > 0 && data.excluded_memories.length <= 10}
      >
        <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto">
          {data.excluded_memories.length > 0 ? (
            data.excluded_memories.map((memory, i) => renderMemoryEntry(memory, i))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noExcludedMemories')}</p>
          )}
        </div>
      </CollapsibleSection>

      {data.owner_id && (
        <Card className="p-4">
          <div className="text-sm">
            <span className="text-slate-500 dark:text-slate-400">{t('ownerId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.owner_id}
            </span>
          </div>
          <div className="text-sm mt-2">
            <span className="text-slate-500 dark:text-slate-400">{t('createdAt')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">
              {new Date(data.created_at).toLocaleString()}
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}