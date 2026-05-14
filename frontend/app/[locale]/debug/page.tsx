'use client';

import React, { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { Tabs, TabList, Tab, TabPanel } from '@/components/ui/Tabs';
import { DebugSessionSelector } from '@/components/debug/DebugSessionSelector';
import { DebugErrorBoundary } from '@/components/debug/DebugErrorBoundary';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { DebugLoading } from '@/components/debug/DebugLoading';
import { PromptInspector } from '@/components/debug/PromptInspector';
import { TimelineViewer } from '@/components/debug/TimelineViewer';
import { NPCMindInspector } from '@/components/debug/NPCMindInspector';
import { TurnDebugViewer } from '@/components/debug/TurnDebugViewer';
import { ContextBuildAudit } from '@/components/debug/ContextBuildAudit';
import { ValidationAuditViewer } from '@/components/debug/ValidationAuditViewer';
import { getDebugSessionLogs, getDebugSessionState, getDebugModelCalls, getDebugErrors } from '@/lib/api';
import type { DebugSessionLogsResponse, DebugSessionStateResponse, DebugModelCallsResponse, DebugErrorsResponse } from '@/types/api';

export default function DebugPage() {
  return (
    <ProtectedRoute>
      <DebugContent />
    </ProtectedRoute>
  );
}

function DebugContent() {
  const t = useTranslations('Debug');
  const [sessionId, setSessionId] = useState('');
  const [turnNo, setTurnNo] = useState(1);
  const [validationId, setValidationId] = useState('');
  const [contextBuildId, setContextBuildId] = useState('');
  const [logs, setLogs] = useState<DebugSessionLogsResponse | null>(null);
  const [state, setState] = useState<DebugSessionStateResponse | null>(null);
  const [modelCalls, setModelCalls] = useState<DebugModelCallsResponse | null>(null);
  const [errors, setErrors] = useState<DebugErrorsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSessionData = useCallback(async (id: string) => {
    if (!id.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const [logsData, stateData] = await Promise.all([
        getDebugSessionLogs(id),
        getDebugSessionState(id),
      ]);
      setLogs(logsData);
      setState(stateData);
      setSessionId(id);
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
  }, [t]);

  const fetchGlobalData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [callsData, errorsData] = await Promise.all([
        getDebugModelCalls(),
        getDebugErrors(),
      ]);
      setModelCalls(callsData);
      setErrors(errorsData);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        setError(t('failedToLoadGlobal'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  const hasSession = sessionId.trim() !== '';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-8">{t('dashboard')}</h1>

      {error && <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />}

      <DebugSessionSelector
        onLoad={fetchSessionData}
        isLoading={isLoading}
        currentSessionId={sessionId}
      />

      <Card className="p-4 mb-6">
        <Button variant="outline" onClick={fetchGlobalData} disabled={isLoading}>
          {t('loadGlobalData')}
        </Button>
      </Card>

      {isLoading && <DebugLoading />}

      <Tabs defaultTab="logs">
        <TabList>
          <Tab value="logs">{t('logs')}</Tab>
          <Tab value="state">{t('state')}</Tab>
          <Tab value="timeline">{t('timeline')}</Tab>
          <Tab value="npcMind">{t('npcMind')}</Tab>
          <Tab value="turnDebug">{t('turnDebug')}</Tab>
          <Tab value="validationAudit">{t('validationAudit')}</Tab>
          <Tab value="promptInspector">{t('promptInspector')}</Tab>
        </TabList>

        <TabPanel value="logs">
          <DebugErrorBoundary>
            {logs ? (
              <Card className="p-6">
                <h3 className="text-lg font-semibold mb-4">{t('sessionLogs')}</h3>
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                  {logs.logs.map(log => (
                    <div key={log.log_id} className="text-sm p-2 bg-slate-50 dark:bg-slate-800 rounded">
                      <span className="text-slate-500">{log.log_type}</span>: {log.message}
                    </div>
                  ))}
                  {logs.logs.length === 0 && <p className="text-slate-500">{t('noLogs')}</p>}
                </div>
              </Card>
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="state">
          <DebugErrorBoundary>
            {state ? (
              <Card className="p-6">
                <h3 className="text-lg font-semibold mb-4">{t('sessionState')}</h3>
                <pre className="text-sm bg-slate-50 dark:bg-slate-800 p-4 rounded overflow-auto max-h-[400px]">
                  {JSON.stringify(state, null, 2)}
                </pre>
              </Card>
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="timeline">
          <DebugErrorBoundary>
            {hasSession ? (
              <TimelineViewer sessionId={sessionId} />
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="npcMind">
          <DebugErrorBoundary>
            {hasSession ? (
              <NPCMindInspector sessionId={sessionId} />
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="turnDebug">
          <DebugErrorBoundary>
            {hasSession ? (
              <div className="space-y-6">
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <label className="text-sm text-slate-600 dark:text-slate-400">{t('turnNumber')}</label>
                    <input
                      type="number"
                      min={1}
                      value={turnNo}
                      onChange={(e) => setTurnNo(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-20 px-2 py-1 text-sm border rounded dark:bg-slate-800 dark:border-slate-600"
                    />
                  </div>
                  <TurnDebugViewer sessionId={sessionId} turnNo={turnNo} />
                </div>
                <div className="space-y-4">
                  <h3 className="text-lg font-semibold">{t('contextBuildAudit')}</h3>
                  <div className="flex items-center gap-2">
                    <label className="text-sm text-slate-600 dark:text-slate-400">{t('contextBuildId')}</label>
                    <input
                      type="text"
                      value={contextBuildId}
                      onChange={(e) => setContextBuildId(e.target.value)}
                      placeholder={t('contextBuildIdPlaceholder')}
                      className="flex-1 px-2 py-1 text-sm border rounded dark:bg-slate-800 dark:border-slate-600"
                    />
                  </div>
                  {contextBuildId ? (
                    <ContextBuildAudit sessionId={sessionId} buildId={contextBuildId} />
                  ) : (
                    <DebugEmptyState message={t('emptyState.noContextBuildId')} />
                  )}
                </div>
              </div>
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="validationAudit">
          <DebugErrorBoundary>
            {hasSession ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <label className="text-sm text-slate-600 dark:text-slate-400">{t('validationId')}</label>
                  <input
                    type="text"
                    value={validationId}
                    onChange={(e) => setValidationId(e.target.value)}
                    placeholder={t('validationIdPlaceholder')}
                    className="flex-1 px-2 py-1 text-sm border rounded dark:bg-slate-800 dark:border-slate-600"
                  />
                </div>
                {validationId ? (
                  <ValidationAuditViewer sessionId={sessionId} validationId={validationId} />
                ) : (
                  <DebugEmptyState message={t('emptyState.noValidationId')} />
                )}
              </div>
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>

        <TabPanel value="promptInspector">
          <DebugErrorBoundary>
            {hasSession ? (
              <PromptInspector sessionId={sessionId} />
            ) : (
              <DebugEmptyState message={t('emptyState.noSession')} />
            )}
          </DebugErrorBoundary>
        </TabPanel>
      </Tabs>

      {modelCalls && (
        <Card className="p-6 mt-6">
          <h3 className="text-lg font-semibold mb-4">{t('modelCalls')}</h3>
          <p className="text-sm text-slate-500 mb-2">{t('totalCost', { cost: modelCalls.total_cost.toFixed(4) })}</p>
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {modelCalls.calls.map(call => (
              <div key={call.call_id} className="text-sm p-2 bg-slate-50 dark:bg-slate-800 rounded">
                <p>{call.model_name} - {call.latency_ms}ms</p>
                <p className="text-slate-500">Tokens: {call.token_usage_input}+{call.token_usage_output}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {errors && (
        <Card className="p-6 mt-6">
          <h3 className="text-lg font-semibold mb-4">{t('recentErrors')}</h3>
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {errors.errors.map(err => (
              <div key={err.error_id} className="text-sm p-2 bg-red-50 dark:bg-red-900/20 rounded">
                <p className="font-medium text-red-700 dark:text-red-300">{err.error_type}</p>
                <p className="text-red-600 dark:text-red-400">{err.message}</p>
              </div>
            ))}
            {errors.errors.length === 0 && <p className="text-slate-500">{t('noErrors')}</p>}
          </div>
        </Card>
      )}
    </div>
  );
}
