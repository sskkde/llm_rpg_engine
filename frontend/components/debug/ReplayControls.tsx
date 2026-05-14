'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { replaySession, createSnapshot, getReplayReport } from '@/lib/api';
import type {
  ReplayResultResponse,
  ReplayReportResponse,
  ReplayPerspective,
  ReplayStepResponse,
} from '@/types/api';

interface ReplayControlsProps {
  sessionId: string;
  maxTurn?: number;
}

export function ReplayControls({ sessionId, maxTurn = 100 }: ReplayControlsProps) {
  const t = useTranslations('Debug');

  const [startTurn, setStartTurn] = useState(1);
  const [endTurn, setEndTurn] = useState(10);
  const [perspective, setPerspective] = useState<ReplayPerspective>('admin');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [replayResult, setReplayResult] = useState<ReplayResultResponse | null>(null);
  const [reportResult, setReportResult] = useState<ReplayReportResponse | null>(null);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  const validateTurnRange = (): boolean => {
    if (startTurn < 1) {
      setError(t('invalidStartTurn'));
      return false;
    }
    if (endTurn < startTurn) {
      setError(t('invalidTurnRange'));
      return false;
    }
    if (endTurn > maxTurn) {
      setError(t('turnRangeExceedsMax', { max: maxTurn }));
      return false;
    }
    return true;
  };

  const handleStartReplay = async () => {
    if (!validateTurnRange()) return;

    setIsLoading(true);
    setError(null);
    setReplayResult(null);
    setReportResult(null);

    try {
      const result = await replaySession(sessionId, {
        start_turn: startTurn,
        end_turn: endTurn,
        perspective,
      });
      setReplayResult(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateSnapshot = async () => {
    setIsLoading(true);
    setError(null);

    try {
      await createSnapshot(sessionId, { turn_no: endTurn });
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('failedToCreateSnapshot'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleGenerateReport = async () => {
    if (!validateTurnRange()) return;

    setIsLoading(true);
    setError(null);
    setReportResult(null);

    try {
      const result = await getReplayReport(sessionId, {
        start_turn: startTurn,
        end_turn: endTurn,
        perspective,
      });
      setReportResult(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const perspectiveOptions = [
    {
      value: 'admin',
      label: t('perspectiveOptions.admin'),
      description: t('perspectiveOptions.adminDesc'),
    },
    {
      value: 'player',
      label: t('perspectiveOptions.player'),
      description: t('perspectiveOptions.playerDesc'),
    },
    {
      value: 'auditor',
      label: t('perspectiveOptions.auditor'),
      description: t('perspectiveOptions.auditorDesc'),
    },
  ];

  const renderStep = (step: ReplayStepResponse) => {
    const isExpanded = expandedStep === step.step_no;

    return (
      <Card key={step.step_no} className="p-4 mb-4">
        <button
          type="button"
          onClick={() => setExpandedStep(isExpanded ? null : step.step_no)}
          className="w-full text-left"
        >
          <div className="flex justify-between items-center">
            <h4 className="text-sm font-medium">
              {t('turn')} {step.turn_no}
            </h4>
            <span className="text-xs text-slate-500">
              {isExpanded ? '▼' : '▶'}
            </span>
          </div>
          {step.player_input && (
            <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">
              {step.player_input}
            </p>
          )}
        </button>

        {isExpanded && (
          <div className="mt-4 space-y-4">
            <div>
              <h5 className="text-xs font-medium text-slate-500 mb-1">
                {t('stateBefore')}
              </h5>
              <pre className="text-xs bg-slate-50 dark:bg-slate-800 p-2 rounded overflow-auto max-h-[200px]">
                {JSON.stringify(step.state_before, null, 2)}
              </pre>
            </div>

            <div>
              <h5 className="text-xs font-medium text-slate-500 mb-1">
                {t('stateAfter')}
              </h5>
              <pre className="text-xs bg-slate-50 dark:bg-slate-800 p-2 rounded overflow-auto max-h-[200px]">
                {JSON.stringify(step.state_after, null, 2)}
              </pre>
            </div>

            {step.events.length > 0 && (
              <div>
                <h5 className="text-xs font-medium text-slate-500 mb-1">
                  {t('events')}
                </h5>
                <div className="space-y-1">
                  {step.events.map((event) => (
                    <div
                      key={event.event_id}
                      className="text-xs p-2 bg-slate-50 dark:bg-slate-800 rounded"
                    >
                      <span className="text-slate-500">{event.event_type}</span>
                      : {event.summary}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {error && (
        <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />
      )}

      <Card className="p-6">
        <h3 className="text-lg font-semibold mb-4">{t('replayTool')}</h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('startTurn')}
            </label>
            <input
              type="number"
              min={1}
              max={maxTurn}
              value={startTurn}
              onChange={(e) => setStartTurn(parseInt(e.target.value, 10) || 1)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('endTurn')}
            </label>
            <input
              type="number"
              min={1}
              max={maxTurn}
              value={endTurn}
              onChange={(e) => setEndTurn(parseInt(e.target.value, 10) || 1)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('perspective')}
            </label>
            <select
              value={perspective}
              onChange={(e) => setPerspective(e.target.value as ReplayPerspective)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
            >
              {perspectiveOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 mt-1">
              {perspectiveOptions.find((o) => o.value === perspective)?.description}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <Button onClick={handleStartReplay} disabled={isLoading}>
            {t('startReplay')}
          </Button>
          <Button variant="outline" onClick={handleCreateSnapshot} disabled={isLoading}>
            {t('createSnapshot')}
          </Button>
          <Button variant="outline" onClick={handleGenerateReport} disabled={isLoading}>
            {t('generateReport')}
          </Button>
        </div>
      </Card>

      {isLoading && (
        <Card className="p-6">
          <p className="text-slate-500">{t('loadingDebugData')}</p>
        </Card>
      )}

      {replayResult && !isLoading && (
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">{t('replayResults')}</h3>

          <div className="mb-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-500">{t('totalSteps')}:</span>{' '}
              <span className="font-medium">{replayResult.total_steps}</span>
            </div>
            <div>
              <span className="text-slate-500">{t('totalEvents')}:</span>{' '}
              <span className="font-medium">{replayResult.total_events}</span>
            </div>
            <div>
              <span className="text-slate-500">{t('success')}:</span>{' '}
              <span className={replayResult.success ? 'text-green-600' : 'text-red-600'}>
                {replayResult.success ? t('pass') : t('fail')}
              </span>
            </div>
            {replayResult.replay_duration_ms && (
              <div>
                <span className="text-slate-500">{t('duration')}:</span>{' '}
                <span className="font-medium">{replayResult.replay_duration_ms}ms</span>
              </div>
            )}
          </div>

          {replayResult.error_message && (
            <div className="mb-4 p-2 bg-red-50 dark:bg-red-900/20 rounded text-red-700 dark:text-red-300 text-sm">
              {replayResult.error_message}
            </div>
          )}

          <div className="space-y-2">
            {replayResult.steps.map(renderStep)}
          </div>
        </Card>
      )}

      {reportResult && !isLoading && (
        <Card className="p-6">
          <h3 className="text-lg font-semibold mb-4">{t('replayReport')}</h3>

          <div className="mb-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-slate-500">{t('deterministic')}:</span>{' '}
              <span className={reportResult.deterministic ? 'text-green-600' : 'text-yellow-600'}>
                {reportResult.deterministic ? t('pass') : t('warning')}
              </span>
            </div>
            <div>
              <span className="text-slate-500">{t('llmCalls')}:</span>{' '}
              <span className="font-medium">{reportResult.llm_calls_made}</span>
            </div>
            <div>
              <span className="text-slate-500">{t('events')}:</span>{' '}
              <span className="font-medium">{reportResult.replayed_event_count}</span>
            </div>
          </div>

          {reportResult.warnings.length > 0 && (
            <div className="mb-4">
              <h5 className="text-xs font-medium text-slate-500 mb-1">{t('warnings')}</h5>
              <div className="space-y-1">
                {reportResult.warnings.map((warning, i) => (
                  <div key={i} className="text-xs p-2 bg-yellow-50 dark:bg-yellow-900/20 rounded text-yellow-700 dark:text-yellow-300">
                    {warning}
                  </div>
                ))}
              </div>
            </div>
          )}

          {reportResult.state_diff.entries.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-slate-500 mb-2">{t('stateDiff')}</h5>
              <div className="space-y-2 max-h-[400px] overflow-y-auto">
                {reportResult.state_diff.entries.map((entry, i) => (
                  <div key={i} className="text-xs p-2 bg-slate-50 dark:bg-slate-800 rounded">
                    <div className="font-medium text-slate-700 dark:text-slate-300 mb-1">
                      {entry.operation}: {entry.path}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <span className="text-red-500">-: </span>
                        <code className="text-xs">{JSON.stringify(entry.old_value)}</code>
                      </div>
                      <div>
                        <span className="text-green-500">+: </span>
                        <code className="text-xs">{JSON.stringify(entry.new_value)}</code>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
