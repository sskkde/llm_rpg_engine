'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getTurnDebug } from '@/lib/api';
import type { TurnDebugResponse, LLMStageEvidence } from '@/types/api';

interface TurnDebugViewerProps {
  sessionId: string;
  turnNo: number;
}

export function TurnDebugViewer({ sessionId, turnNo }: TurnDebugViewerProps) {
  const t = useTranslations('Debug');
  const [data, setData] = useState<TurnDebugResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    if (!sessionId || turnNo < 1) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getTurnDebug(sessionId, turnNo);
      setData(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else if (status === 404) {
        setError(t('turnNotFound'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  if (!sessionId || turnNo < 1) {
    return <DebugEmptyState message={t('emptyState.noTurn')} />;
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
          {t('loadTurnDebug')}
        </button>
      </Card>
    );
  }

  const renderLLMStage = (stage: LLMStageEvidence, index: number) => {
    const statusColor = stage.accepted
      ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200'
      : 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200';

    return (
      <div
        key={index}
        className="p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg space-y-2"
      >
        <div className="flex items-center justify-between">
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {stage.stage_name}
          </span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${statusColor}`}>
            {stage.accepted ? t('accepted') : t('rejected')}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('enabled')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">
              {stage.enabled ? t('yes') : t('no')}
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('timeout')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">
              {stage.timeout.toFixed(2)}s
            </span>
          </div>
        </div>
        {stage.fallback_reason && (
          <div className="text-sm">
            <span className="text-slate-500 dark:text-slate-400">{t('fallbackReason')}:</span>
            <span className="ml-1 text-yellow-700 dark:text-yellow-300">
              {stage.fallback_reason}
            </span>
          </div>
        )}
        {stage.validation_errors.length > 0 && (
          <div className="text-sm">
            <span className="text-slate-500 dark:text-slate-400">{t('validationErrors')}:</span>
            <ul className="mt-1 list-disc list-inside text-red-700 dark:text-red-300">
              {stage.validation_errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}
        {stage.model_call_id && (
          <div className="text-sm">
            <span className="text-slate-500 dark:text-slate-400">{t('modelCallId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {stage.model_call_id}
            </span>
          </div>
        )}
      </div>
    );
  };

  const renderStateDelta = (delta: TurnDebugResponse['state_deltas'][0], index: number) => {
    const opColor =
      delta.operation === 'add'
        ? 'text-green-600 dark:text-green-400'
        : delta.operation === 'remove'
          ? 'text-red-600 dark:text-red-400'
          : 'text-blue-600 dark:text-blue-400';

    return (
      <div key={index} className="p-2 bg-slate-50 dark:bg-slate-700/50 rounded text-sm">
        <div className="flex items-center gap-2 mb-1">
          <span className={`font-medium ${opColor}`}>{delta.operation.toUpperCase()}</span>
          <span className="font-mono text-xs text-slate-600 dark:text-slate-400">
            {delta.path}
          </span>
          {delta.validated && (
            <span className="px-1 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 rounded text-xs">
              {t('validated')}
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('oldValue')}:</span>
            <pre className="mt-1 text-xs bg-slate-100 dark:bg-slate-800 p-1 rounded overflow-x-auto">
              {JSON.stringify(delta.old_value, null, 2)}
            </pre>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('newValue')}:</span>
            <pre className="mt-1 text-xs bg-slate-100 dark:bg-slate-800 p-1 rounded overflow-x-auto">
              {JSON.stringify(delta.new_value, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    );
  };

  const renderModelCallRef = (call: TurnDebugResponse['model_call_references'][0], index: number) => {
    return (
      <div key={index} className="p-2 bg-slate-50 dark:bg-slate-700/50 rounded text-sm">
        <div className="flex items-center justify-between mb-1">
          <span className="font-mono text-xs text-slate-600 dark:text-slate-400">
            {call.call_id}
          </span>
          {call.prompt_type && (
            <span className="px-2 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded text-xs">
              {call.prompt_type}
            </span>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          {call.model_name && <div><span className="text-slate-500">{t('model')}:</span> {call.model_name}</div>}
          {call.provider && <div><span className="text-slate-500">{t('provider')}:</span> {call.provider}</div>}
          {call.latency_ms !== undefined && <div><span className="text-slate-500">{t('latency')}:</span> {call.latency_ms}ms</div>}
          {call.input_tokens !== undefined && <div><span className="text-slate-500">{t('inputTokens')}:</span> {call.input_tokens}</div>}
          {call.output_tokens !== undefined && <div><span className="text-slate-500">{t('outputTokens')}:</span> {call.output_tokens}</div>}
          {call.cost_estimate !== undefined && <div><span className="text-slate-500">{t('cost')}:</span> ${call.cost_estimate.toFixed(6)}</div>}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {t('turnDebugTitle', { turnNo: data.turn_no })}
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
            <span className="text-slate-500 dark:text-slate-400">{t('status')}:</span>
            <span className={`ml-1 ${data.status === 'completed' ? 'text-green-600 dark:text-green-400' : 'text-yellow-600 dark:text-yellow-400'}`}>
              {data.status}
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('transactionId')}:</span>
            <span className="ml-1 font-mono text-xs text-slate-700 dark:text-slate-300">
              {data.transaction_id.slice(0, 8)}...
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('duration')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">
              {data.turn_duration_ms ? `${data.turn_duration_ms}ms` : t('n/a')}
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('narrationLength')}:</span>
            <span className="ml-1 text-slate-700 dark:text-slate-300">
              {data.narration_length} {t('chars')}
            </span>
          </div>
        </div>

        <div className="text-sm">
          <span className="text-slate-500 dark:text-slate-400">{t('playerInput')}:</span>
          <p className="mt-1 bg-slate-50 dark:bg-slate-700/50 p-2 rounded text-slate-700 dark:text-slate-300">
            {data.player_input}
          </p>
        </div>
      </Card>

      <CollapsibleSection
        title={t('parsedIntent')}
        summary={data.parsed_intent ? t('parsed') : t('none')}
        defaultOpen={false}
      >
        <div className="p-4">
          {data.parsed_intent ? (
            <pre className="text-sm bg-slate-50 dark:bg-slate-700/50 p-3 rounded overflow-x-auto">
              {JSON.stringify(data.parsed_intent, null, 2)}
            </pre>
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noParsedIntent')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('llmStages')}
        summary={`${data.llm_stages.length} ${t('stages')}`}
        defaultOpen={data.llm_stages.length > 0}
      >
        <div className="p-4 space-y-3">
          {data.llm_stages.length > 0 ? (
            data.llm_stages.map((stage, i) => renderLLMStage(stage, i))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noLLMStages')}</p>
          )}
        </div>
      </CollapsibleSection>

      {data.fallback_reasons.length > 0 && (
        <CollapsibleSection
          title={t('fallbackReasons')}
          summary={`${data.fallback_reasons.length} ${t('reasons')}`}
          defaultOpen={true}
        >
          <div className="p-4">
            <ul className="list-disc list-inside text-sm space-y-1 text-yellow-700 dark:text-yellow-300">
              {data.fallback_reasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection
        title={t('modelCalls')}
        summary={`${data.model_call_references.length} ${t('calls')}`}
        defaultOpen={false}
      >
        <div className="p-4 space-y-2">
          {data.model_call_references.length > 0 ? (
            data.model_call_references.map((call, i) => renderModelCallRef(call, i))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noModelCalls')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('stateDeltas')}
        summary={`${data.state_deltas.length} ${t('deltas')}`}
        defaultOpen={false}
      >
        <div className="p-4 space-y-2 max-h-[400px] overflow-y-auto">
          {data.state_deltas.length > 0 ? (
            data.state_deltas.map((delta, i) => renderStateDelta(delta, i))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noStateDeltas')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('events')}
        summary={`${data.events.length} ${t('eventsCount')}`}
        defaultOpen={false}
      >
        <div className="p-4 space-y-2">
          {data.events.length > 0 ? (
            data.events.map((event, i) => (
              <div key={i} className="p-2 bg-slate-50 dark:bg-slate-700/50 rounded text-sm">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded text-xs">
                    {event.event_type}
                  </span>
                  {event.actor_id && (
                    <span className="text-slate-500 dark:text-slate-400">
                      {t('actor')}: {event.actor_id}
                    </span>
                  )}
                </div>
                {event.summary && (
                  <p className="mt-1 text-slate-700 dark:text-slate-300">{event.summary}</p>
                )}
              </div>
            ))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noEvents')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('contextBuilds')}
        summary={`${data.context_build_ids.length} ${t('builds')}`}
        defaultOpen={false}
      >
        <div className="p-4 space-y-2">
          {data.context_build_ids.length > 0 ? (
            data.context_build_ids.map((id, i) => (
              <div key={i} className="p-2 bg-slate-50 dark:bg-slate-700/50 rounded text-sm">
                <span className="font-mono text-xs text-slate-600 dark:text-slate-400">{id}</span>
                {data.context_hashes.find(h => h.build_id === id) && (
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {t('hash')}: {data.context_hashes.find(h => h.build_id === id)?.context_hash.slice(0, 16)}...
                  </div>
                )}
              </div>
            ))
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noContextBuilds')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('promptTemplates')}
        summary={`${data.prompt_template_ids.length} ${t('templates')}`}
        defaultOpen={false}
      >
        <div className="p-4">
          {data.prompt_template_ids.length > 0 ? (
            <ul className="list-disc list-inside text-sm space-y-1">
              {data.prompt_template_ids.map((id, i) => (
                <li key={i} className="font-mono text-xs text-slate-600 dark:text-slate-400">
                  {id}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-slate-500 dark:text-slate-400">{t('noPromptTemplates')}</p>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title={t('worldTime')}
        defaultOpen={false}
      >
        <div className="p-4 grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('before')}:</span>
            <pre className="mt-1 text-xs bg-slate-50 dark:bg-slate-700/50 p-2 rounded">
              {JSON.stringify(data.world_time_before, null, 2)}
            </pre>
          </div>
          <div>
            <span className="text-slate-500 dark:text-slate-400">{t('after')}:</span>
            <pre className="mt-1 text-xs bg-slate-50 dark:bg-slate-700/50 p-2 rounded">
              {data.world_time_after ? JSON.stringify(data.world_time_after, null, 2) : t('n/a')}
            </pre>
          </div>
        </div>
      </CollapsibleSection>
    </div>
  );
}
