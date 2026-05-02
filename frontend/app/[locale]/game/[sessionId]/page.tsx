'use client';

import { useState, useEffect, useCallback, use } from 'react';
import {useTranslations} from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Loading } from '@/components/ui/Loading';
import { NarrationPanel } from '@/components/game/NarrationPanel';
import { ActionInput } from '@/components/game/ActionInput';
import { RecommendedActions } from '@/components/game/RecommendedActions';
import { StatePanel } from '@/components/game/StatePanel';
import { LogPanel } from '@/components/game/LogPanel';
import { ConnectionStatus } from '@/components/game/ConnectionStatus';
import { TurnErrorPanel } from '@/components/game/TurnErrorPanel';
import { useTurnStream } from '@/hooks/useTurnStream';
import { getSessionSnapshot } from '@/lib/api';
import type { SessionSnapshot } from '@/types/api';

export default function GameSessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  return (
    <ProtectedRoute>
      <GameSessionContent sessionId={sessionId} />
    </ProtectedRoute>
  );
}

function GameSessionContent({ sessionId }: { sessionId: string }) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [logEntries, setLogEntries] = useState<Array<{ turnIndex: number; action: string; narration: string }>>([]);

  const { isStreaming, isPending, narration, error, usedFallback, submitTurn, clearError } = useTurnStream(sessionId);

  const refreshSnapshot = useCallback(async () => {
    try {
      const data = await getSessionSnapshot(sessionId);
      setSnapshot(data);
    } catch {
    }
  }, [sessionId]);

  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      await refreshSnapshot();
      setIsLoading(false);
    };
    load();
  }, [refreshSnapshot]);

  const handleAction = useCallback(async (action: string) => {
    const result = await submitTurn(action);
    if (result) {
      setLogEntries((prev) => [
        ...prev,
        { turnIndex: result.turn_index, action, narration: result.narration },
      ]);
      await refreshSnapshot();
    }
  }, [submitTurn, refreshSnapshot]);

  const t = useTranslations('Game');

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loading size="lg" text={t('loadingGameSession')} />
      </div>
    );
  }

  const recommendedActions = [
    t('defaultActions.lookAround'),
    t('defaultActions.checkStatus'),
    t('continueForward'),
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t('adventure')}
        </h1>
        <ConnectionStatus isStreaming={isStreaming} usedFallback={usedFallback} />
      </div>

      <TurnErrorPanel error={error} usedFallback={usedFallback} onDismiss={clearError} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-4">
        <div className="lg:col-span-2 space-y-4">
          <NarrationPanel narration={narration} isStreaming={isStreaming} />
          <RecommendedActions
            actions={recommendedActions}
            onSelect={handleAction}
            isDisabled={isPending}
          />
          <ActionInput onSubmit={handleAction} isDisabled={isPending} />
        </div>

        <div className="space-y-4">
          <StatePanel snapshot={snapshot} />
          <LogPanel entries={logEntries} />
        </div>
      </div>
    </div>
  );
}
