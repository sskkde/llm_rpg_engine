'use client';

import { useState, useEffect, useCallback, use } from 'react';
import {useTranslations} from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Loading } from '@/components/ui/Loading';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { NarrationPanel } from '@/components/game/NarrationPanel';
import { ActionInput } from '@/components/game/ActionInput';
import { RecommendedActions } from '@/components/game/RecommendedActions';
import { StatePanel } from '@/components/game/StatePanel';
import { LogPanel } from '@/components/game/LogPanel';
import { ConnectionStatus } from '@/components/game/ConnectionStatus';
import { TurnErrorPanel } from '@/components/game/TurnErrorPanel';
import { useTurnStream } from '@/hooks/useTurnStream';
import { getSessionSnapshot, getAdventureLog } from '@/lib/api';
import type { SessionSnapshot, AdventureLogEntry } from '@/types/api';

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
  const [logEntries, setLogEntries] = useState<AdventureLogEntry[]>([]);
  const [selectedLogEntryId, setSelectedLogEntryId] = useState<string | null>(null);
  const [recommendedActions, setRecommendedActions] = useState<string[]>([]);

  const { isStreaming, isPending, narration, error, usedFallback, submitTurn, clearError } = useTurnStream(sessionId);
  const t = useTranslations('Game');

  const defaultRecommendedActions = useCallback(() => [
    t('defaultActions.lookAround'),
    t('defaultActions.checkStatus'),
    t('continueForward'),
  ], [t]);

  const syncRecommendedActions = useCallback((entries: AdventureLogEntry[]) => {
    const latestActions = entries.length > 0 ? entries[entries.length - 1].recommended_actions ?? [] : [];
    setRecommendedActions(latestActions.length > 0 ? latestActions : defaultRecommendedActions());
  }, [defaultRecommendedActions]);

  const refreshSnapshot = useCallback(async () => {
    try {
      const data = await getSessionSnapshot(sessionId);
      setSnapshot(data);
    } catch {
      // Snapshot refresh failed; loading state handles this gracefully
    }
  }, [sessionId]);

  useEffect(() => {
    const load = async () => {
      setIsLoading(true);
      await refreshSnapshot();
      try {
        const entries = await getAdventureLog(sessionId);
        setLogEntries(entries);
        syncRecommendedActions(entries);
      } catch {
        // Adventure log load failed; empty state handles this gracefully
        setRecommendedActions(defaultRecommendedActions());
      }
      setIsLoading(false);
    };
    load();
  }, [refreshSnapshot, sessionId, syncRecommendedActions, defaultRecommendedActions]);

  const handleAction = useCallback(async (action: string) => {
    setSelectedLogEntryId(null);
    const result = await submitTurn(action);
    if (result) {
      const resultActions = result.recommended_actions ?? [];
      setRecommendedActions(
        resultActions.length > 0 ? resultActions : defaultRecommendedActions()
      );
      try {
        const entries = await getAdventureLog(sessionId);
        setLogEntries(entries);
        if (resultActions.length === 0) {
          syncRecommendedActions(entries);
        }
      } catch {
        // Refresh failed after successful turn; stale log is acceptable
      }
      await refreshSnapshot();
    }
  }, [submitTurn, refreshSnapshot, sessionId, syncRecommendedActions, defaultRecommendedActions]);

  const selectedLogEntry = selectedLogEntryId
    ? logEntries.find((entry) => entry.id === selectedLogEntryId)
    : undefined;

  const currentNarration = isStreaming
    ? narration
    : selectedLogEntry
      ? selectedLogEntry.narration
      : logEntries.length > 0
      ? logEntries[logEntries.length - 1].narration
      : '';

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loading size="lg" text={t('loadingGameSession')} />
      </div>
    );
  }

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
          <NarrationPanel narration={currentNarration} isStreaming={isStreaming} />
          <RecommendedActions
            actions={recommendedActions}
            onSelect={handleAction}
            isDisabled={isPending}
          />
          <ActionInput onSubmit={handleAction} isDisabled={isPending} />

          {/* Mobile: Collapsible State and Log sections below main content */}
          <div className="lg:hidden space-y-4 pt-2">
            <CollapsibleSection
              id="mobile-state-section"
              title={t('characterState')}
              defaultOpen={true}
              summary={
                snapshot?.player_state && snapshot?.session_state
                  ? `${t('hp')}: ${snapshot.player_state.hp}/${snapshot.player_state.max_hp} · ${snapshot.session_state.active_mode}`
                  : undefined
              }
            >
              <div className="px-4 pb-4">
                <StatePanel snapshot={snapshot} />
              </div>
            </CollapsibleSection>

            <CollapsibleSection
              id="mobile-log-section"
              title={t('adventureLog')}
              defaultOpen={false}
              summary={logEntries.length > 0 ? t('logEntryCount', { count: logEntries.length }) : undefined}
            >
              <div className="px-4 pb-4">
                <LogPanel
                  entries={logEntries}
                  selectedEntryId={selectedLogEntryId}
                  onSelectEntry={(entry) => setSelectedLogEntryId(entry.id)}
                />
              </div>
            </CollapsibleSection>
          </div>
        </div>

        {/* Desktop: Side panel with State and Log */}
        <div className="hidden lg:block space-y-4">
          <StatePanel snapshot={snapshot} />
          <LogPanel
            entries={logEntries}
            selectedEntryId={selectedLogEntryId}
            onSelectEntry={(entry) => setSelectedLogEntryId(entry.id)}
          />
        </div>
      </div>
    </div>
  );
}
