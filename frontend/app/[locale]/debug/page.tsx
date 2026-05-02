'use client';

import React, { useState, useCallback } from 'react';
import {useTranslations} from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
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
  const [logs, setLogs] = useState<DebugSessionLogsResponse | null>(null);
  const [state, setState] = useState<DebugSessionStateResponse | null>(null);
  const [modelCalls, setModelCalls] = useState<DebugModelCallsResponse | null>(null);
  const [errors, setErrors] = useState<DebugErrorsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSessionData = useCallback(async () => {
    if (!sessionId.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const [logsData, stateData] = await Promise.all([
        getDebugSessionLogs(sessionId),
        getDebugSessionState(sessionId),
      ]);
      setLogs(logsData);
      setState(stateData);
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
  }, [sessionId, t]);

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

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-8">{t('dashboard')}</h1>

      {error && <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />}

      <Card className="p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">{t('sessionInspector')}</h2>
        <div className="flex gap-3">
          <Input
            value={sessionId}
            onChange={e => setSessionId(e.target.value)}
            placeholder={t('enterSessionId')}
            className="flex-1"
          />
          <Button onClick={fetchSessionData} disabled={!sessionId.trim() || isLoading}>
            {t('load')}
          </Button>
          <Button variant="outline" onClick={fetchGlobalData} disabled={isLoading}>
            {t('loadGlobalData')}
          </Button>
        </div>
      </Card>

      {isLoading && <Loading size="md" text={t('loadingDebugData')} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {logs && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">{t('sessionLogs')}</h3>
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {logs.logs.map(log => (
                <div key={log.log_id} className="text-sm p-2 bg-slate-50 dark:bg-slate-800 rounded">
                  <span className="text-slate-500">{log.log_type}</span>: {log.message}
                </div>
              ))}
              {logs.logs.length === 0 && <p className="text-slate-500">{t('noLogs')}</p>}
            </div>
          </Card>
        )}

        {state && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">{t('sessionState')}</h3>
            <pre className="text-sm bg-slate-50 dark:bg-slate-800 p-4 rounded overflow-auto max-h-[300px]">
              {JSON.stringify(state, null, 2)}
            </pre>
          </Card>
        )}

        {modelCalls && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">{t('modelCalls')}</h3>
            <p className="text-sm text-slate-500 mb-2">{t('totalCost', {cost: modelCalls.total_cost.toFixed(4)})}</p>
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
          <Card className="p-6">
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
    </div>
  );
}
