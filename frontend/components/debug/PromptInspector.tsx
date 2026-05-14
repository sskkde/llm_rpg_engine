'use client';

import React, { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { getPromptInspector } from '@/lib/api';
import type {
  PromptInspectorResponse,
  PromptInspectorModelCallEntry,
  PromptInspectorContextBuildEntry,
  ValidationInspectorEntry,
  ProposalInspectorEntry,
} from '@/types/api';

interface PromptInspectorProps {
  sessionId: string;
}

function formatJson(data: unknown): string {
  return JSON.stringify(data, null, 2);
}

function JsonDisplay({ data, maxHeight = 300 }: { data: unknown; maxHeight?: number }) {
  return (
    <pre
      className="text-xs bg-slate-50 dark:bg-slate-900 p-3 rounded overflow-auto font-mono"
      style={{ maxHeight }}
    >
      <code>{formatJson(data)}</code>
    </pre>
  );
}

function MemoryTable({
  memories,
  title,
}: {
  memories: Array<{
    memory_id: string;
    memory_type: string;
    reason: string;
    relevance_score?: number;
    forbidden_knowledge_flag: boolean;
  }>;
  title: string;
}) {
  const t = useTranslations('Debug');

  return (
    <div className="mt-3">
      <h5 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">{title}</h5>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700">
              <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('memories')}</th>
              <th className="text-left p-2 text-slate-500 dark:text-slate-400">Type</th>
              <th className="text-left p-2 text-slate-500 dark:text-slate-400">Reason</th>
              <th className="text-left p-2 text-slate-500 dark:text-slate-400">Score</th>
            </tr>
          </thead>
          <tbody>
            {memories.map((m) => (
              <tr key={m.memory_id} className="border-b border-slate-100 dark:border-slate-800">
                <td className="p-2 truncate max-w-[150px]">{m.memory_id}</td>
                <td className="p-2">{m.memory_type}</td>
                <td className="p-2">{m.reason}</td>
                <td className="p-2">
                  {m.relevance_score?.toFixed(2) ?? '-'}
                  {m.forbidden_knowledge_flag && (
                    <span className="ml-1 text-red-500">{t('forbiddenKnowledge')}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PromptInspector({ sessionId }: PromptInspectorProps) {
  const t = useTranslations('Debug');
  const [data, setData] = useState<PromptInspectorResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startTurn, setStartTurn] = useState<number | undefined>(undefined);
  const [endTurn, setEndTurn] = useState<number | undefined>(undefined);
  const [expandedCall, setExpandedCall] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!sessionId.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getPromptInspector(sessionId, startTurn, endTurn);
      setData(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else if (status === 404) {
        setError(t('failedToLoad'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, startTurn, endTurn, t]);

  const handleRowClick = (callId: string) => {
    setExpandedCall(expandedCall === callId ? null : callId);
  };

  if (isLoading) return <Loading size="md" text={t('loading')} />;
  if (error) return <ErrorMessage message={error} variant="card" onRetry={loadData} />;
  if (!data) {
    return (
      <Card className="p-6">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('startTurn')}
            </label>
            <input
              type="number"
              min={1}
              value={startTurn ?? ''}
              onChange={(e) => setStartTurn(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-24 px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('endTurn')}
            </label>
            <input
              type="number"
              min={1}
              value={endTurn ?? ''}
              onChange={(e) => setEndTurn(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-24 px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>
          <Button onClick={loadData} disabled={!sessionId.trim()}>
            {t('load')}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('startTurn')}
            </label>
            <input
              type="number"
              min={1}
              value={startTurn ?? ''}
              onChange={(e) => setStartTurn(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-24 px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('endTurn')}
            </label>
            <input
              type="number"
              min={1}
              value={endTurn ?? ''}
              onChange={(e) => setEndTurn(e.target.value ? parseInt(e.target.value) : undefined)}
              className="w-24 px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>
          <Button onClick={loadData} disabled={isLoading}>
            {isLoading ? t('loading') : t('load')}
          </Button>
        </div>
      </Card>

      <Card className="p-4">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
          {t('llmCalls')} - {t('totalCost', { cost: data.aggregates.total_cost.toFixed(4) })}
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-3">
            <p className="text-xs text-slate-500 dark:text-slate-400">{t('inputTokens')}</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {data.model_calls.reduce((sum, c) => sum + (c.input_tokens ?? 0), 0)}
            </p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-3">
            <p className="text-xs text-slate-500 dark:text-slate-400">{t('outputTokens')}</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {data.model_calls.reduce((sum, c) => sum + (c.output_tokens ?? 0), 0)}
            </p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-3">
            <p className="text-xs text-slate-500 dark:text-slate-400">{t('cost')}</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              ${data.aggregates.total_cost.toFixed(4)}
            </p>
          </div>
          <div className="bg-slate-50 dark:bg-slate-900 rounded-lg p-3">
            <p className="text-xs text-slate-500 dark:text-slate-400">{t('latency')}</p>
            <p className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {Math.round(data.aggregates.total_latency_ms / 1000)}s
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-4">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">Turn</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">Type</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">Model</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('tokens')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('cost')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('latency')}</th>
                <th className="text-left p-2 text-slate-500 dark:text-slate-400">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.model_calls.map((call) => (
                <ModelCallRow
                  key={call.id}
                  call={call}
                  isExpanded={expandedCall === call.id}
                  onToggle={() => handleRowClick(call.id)}
                  contextBuilds={data.context_builds.filter((cb) => cb.turn_no === call.turn_no)}
                  validations={data.validations.filter((v) => v.turn_no === call.turn_no)}
                  proposals={data.proposals.filter((p) => p.turn_no === call.turn_no)}
                />
              ))}
            </tbody>
          </table>
          {data.model_calls.length === 0 && (
            <p className="text-center py-4 text-slate-500 dark:text-slate-400">{t('noData')}</p>
          )}
        </div>
      </Card>
    </div>
  );
}

function ModelCallRow({
  call,
  isExpanded,
  onToggle,
  contextBuilds,
  validations,
  proposals,
}: {
  call: PromptInspectorModelCallEntry;
  isExpanded: boolean;
  onToggle: () => void;
  contextBuilds: PromptInspectorContextBuildEntry[];
  validations: ValidationInspectorEntry[];
  proposals: ProposalInspectorEntry[];
}) {
  const t = useTranslations('Debug');

  const tokens = (call.input_tokens ?? 0) + (call.output_tokens ?? 0);
  const cost = call.cost_estimate?.toFixed(4) ?? '-';
  const latency = call.latency_ms ? `${call.latency_ms}ms` : '-';

  return (
    <>
      <tr
        className="border-b border-slate-100 dark:border-slate-800 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50"
        onClick={onToggle}
      >
        <td className="p-2">{call.turn_no}</td>
        <td className="p-2">{call.prompt_type ?? '-'}</td>
        <td className="p-2 truncate max-w-[150px]">{call.model_name ?? '-'}</td>
        <td className="p-2">{tokens}</td>
        <td className="p-2">${cost}</td>
        <td className="p-2">{latency}</td>
        <td className="p-2">
          {call.success ? (
            <span className="text-green-600 dark:text-green-400">{t('pass')}</span>
          ) : (
            <span className="text-red-600 dark:text-red-400">{t('fail')}</span>
          )}
        </td>
      </tr>
      {isExpanded && (
        <tr className="border-b border-slate-200 dark:border-slate-700">
          <td colSpan={7} className="p-4 bg-slate-50 dark:bg-slate-900/50">
            <div className="space-y-4">
              {proposals.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    Proposals
                  </h4>
                  {proposals.map((prop) => (
                    <div key={prop.audit_id} className="mb-3 p-3 bg-white dark:bg-slate-800 rounded-lg">
                      <div className="flex flex-wrap gap-2 mb-2">
                        <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-700">
                          {prop.proposal_type}
                        </span>
                        {prop.parse_success ? (
                          <span className="text-xs px-2 py-1 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">
                            Parse OK
                          </span>
                        ) : (
                          <span className="text-xs px-2 py-1 rounded bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300">
                            Parse Failed
                          </span>
                        )}
                        {prop.validation_passed ? (
                          <span className="text-xs px-2 py-1 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">
                            Validation OK
                          </span>
                        ) : (
                          <span className="text-xs px-2 py-1 rounded bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300">
                            Validation Failed
                          </span>
                        )}
                        {prop.fallback_used && (
                          <span className="text-xs px-2 py-1 rounded bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300">
                            Fallback
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                        Tokens: {prop.input_tokens}+{prop.output_tokens} | Latency: {prop.latency_ms}ms
                        | Confidence: {prop.confidence.toFixed(2)}
                      </div>
                      {prop.raw_output_preview && (
                        <div>
                          <h5 className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Raw Output Preview
                          </h5>
                          <pre className="text-xs bg-slate-50 dark:bg-slate-900 p-2 rounded overflow-auto max-h-[150px] font-mono">
                            {prop.raw_output_preview}
                          </pre>
                        </div>
                      )}
                      {prop.parsed_proposal && (
                        <div className="mt-2">
                          <h5 className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                            Parsed Proposal
                          </h5>
                          <JsonDisplay data={prop.parsed_proposal} maxHeight={200} />
                        </div>
                      )}
                      {(prop.validation_errors.length > 0 || prop.validation_warnings.length > 0) && (
                        <div className="mt-2">
                          {prop.validation_errors.map((e, i) => (
                            <p key={i} className="text-xs text-red-600 dark:text-red-400">
                              Error: {e}
                            </p>
                          ))}
                          {prop.validation_warnings.map((w, i) => (
                            <p key={i} className="text-xs text-yellow-600 dark:text-yellow-400">
                              Warning: {w}
                            </p>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {contextBuilds.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('memoryDecisions')}
                  </h4>
                  {contextBuilds.map((ctx) => (
                    <div key={ctx.build_id} className="mb-3 p-3 bg-white dark:bg-slate-800 rounded-lg">
                      <div className="flex flex-wrap gap-2 mb-2">
                        <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-700">
                          {ctx.perspective_type}: {ctx.perspective_id}
                        </span>
                        <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-700">
                          {ctx.included_count}/{ctx.excluded_count} memories
                        </span>
                        <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-700">
                          {ctx.context_token_count} tokens
                        </span>
                      </div>
                      {ctx.included_memories.length > 0 && (
                        <MemoryTable memories={ctx.included_memories} title={t('included')} />
                      )}
                      {ctx.excluded_memories.length > 0 && (
                        <MemoryTable memories={ctx.excluded_memories} title={t('excluded')} />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {validations.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('validationChecks')}
                  </h4>
                  {validations.map((val) => (
                    <div key={val.validation_id} className="mb-3 p-3 bg-white dark:bg-slate-800 rounded-lg">
                      <div className="flex flex-wrap gap-2 mb-2">
                        <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-700">
                          {val.validation_target}
                        </span>
                        {val.overall_status === 'pass' ? (
                          <span className="text-xs px-2 py-1 rounded bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">
                            {t('pass')}
                          </span>
                        ) : (
                          <span className="text-xs px-2 py-1 rounded bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-400">
                            {t('fail')}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                        Errors: {val.error_count} | Warnings: {val.warning_count}
                      </div>
                      {val.errors.map((e, i) => (
                        <p key={i} className="text-xs text-red-600 dark:text-red-400 mb-1">
                          {e}
                        </p>
                      ))}
                      {val.warnings.map((w, i) => (
                        <p key={i} className="text-xs text-yellow-600 dark:text-yellow-400 mb-1">
                          {w}
                        </p>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              {proposals.length === 0 && contextBuilds.length === 0 && validations.length === 0 && (
                <p className="text-sm text-slate-500 dark:text-slate-400">{t('noData')}</p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}