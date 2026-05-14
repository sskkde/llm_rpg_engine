'use client';

import React, { useState } from 'react';
import { useTranslations } from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { ReplayControls } from '@/components/debug/ReplayControls';
import { getDebugSessionState } from '@/lib/api';

export default function ReplayPage() {
  return (
    <ProtectedRoute>
      <ReplayContent />
    </ProtectedRoute>
  );
}

function ReplayContent() {
  const t = useTranslations('Debug');
  const [sessionId, setSessionId] = useState('');
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);
  const [maxTurn, setMaxTurn] = useState(100);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLoadSession = async (id: string) => {
    if (!id.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      const state = await getDebugSessionState(id);
      setLoadedSessionId(id);
      const turnCount = state.player_state ? 50 : 10;
      setMaxTurn(turnCount);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else if (status === 404) {
        setError(t('sessionNotFound'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && sessionId.trim() && !isLoading) {
      handleLoadSession(sessionId.trim());
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-8">
        {t('replayTool')}
      </h1>

      {error && (
        <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />
      )}

      <Card className="p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">{t('sessionInspector')}</h2>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('enterSessionId')}
            className="flex-1"
            disabled={isLoading}
          />
          <Button
            onClick={() => handleLoadSession(sessionId.trim())}
            disabled={!sessionId.trim() || isLoading}
          >
            {t('load')}
          </Button>
        </div>
      </Card>

      {loadedSessionId && (
        <ReplayControls sessionId={loadedSessionId} maxTurn={maxTurn} />
      )}

      {!loadedSessionId && !isLoading && (
        <Card className="p-6">
          <p className="text-slate-500 dark:text-slate-400">
            {t('emptyState.noSession')}
          </p>
        </Card>
      )}
    </div>
  );
}
