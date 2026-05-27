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
import { LocationMapPanel } from '@/components/game/LocationMapPanel';
import { InventoryPanel } from '@/components/game/InventoryPanel';
import { ConnectionStatus } from '@/components/game/ConnectionStatus';
import { TurnErrorPanel } from '@/components/game/TurnErrorPanel';

import { QuestJournalEntryPoint } from '@/components/game/QuestJournalEntryPoint';
import { QuestJournalPanel } from '@/components/game/QuestJournalPanel';
import { RelationshipPanel } from '@/components/game/RelationshipPanel';
import { SceneBackground } from '@/components/assets/SceneBackground';
import { BGMControl } from '@/components/assets/BGMControl';
import { SettingsPanel } from '@/components/game/SettingsPanel';
import { NPCPortrait } from '@/components/assets/NPCPortrait';
import { useTurnStream } from '@/hooks/useTurnStream';
import { getSessionSnapshot, getAdventureLog, listSessionNpcs } from '@/lib/api';
import type { SessionSnapshot, AdventureLogEntry, SessionNPC } from '@/types/api';

/**
 * Extracts time of day from a time string.
 * Used to determine scene background gradient and lighting.
 */
function extractTimeOfDay(currentTime?: string): string | undefined {
  if (!currentTime) return undefined;
  const lower = currentTime.toLowerCase();
  if (lower.includes('night') || lower.includes('evening')) return 'night';
  if (lower.includes('morning') || lower.includes('dawn')) return 'morning';
  if (lower.includes('afternoon')) return 'afternoon';
  return undefined;
}

export default function GameSessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params);
  return (
    <ProtectedRoute>
      <GameSessionContent sessionId={sessionId} />
    </ProtectedRoute>
  );
}

export function GameSessionContent({ sessionId }: { sessionId: string }) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [npcs, setNpcs] = useState<SessionNPC[]>([]);
  const [logEntries, setLogEntries] = useState<AdventureLogEntry[]>([]);
  const [selectedLogEntryId, setSelectedLogEntryId] = useState<string | null>(null);
  const [recommendedActions, setRecommendedActions] = useState<string[]>([]);

  const { isStreaming, isPending, isComplete, narration, error, usedFallback, streamingDuration, currentStage, streamFallbackNotice, submitTurn, clearError } = useTurnStream(sessionId);
  const stageLabel = currentStage?.label ?? null;
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
        const npcData = await listSessionNpcs(sessionId);
        setNpcs(npcData.npcs);
      } catch {
        // NPC list load failed; empty state handles this gracefully
      }
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

  const currentLocationId = snapshot?.session_state?.current_location_id;
  const timeOfDay = extractTimeOfDay(snapshot?.session_state?.current_time);
  const npcsAtLocation = currentLocationId
    ? npcs.filter((npc) => npc.location_id === currentLocationId)
    : [];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t('adventure')}
        </h1>
        <div className="flex items-center gap-4">
          <BGMControl locationId={currentLocationId} sessionId={sessionId} />
          <ConnectionStatus isStreaming={isStreaming} usedFallback={usedFallback} />
          <SettingsPanel sessionId={sessionId} />
        </div>
      </div>

      {currentLocationId && (
        <SceneBackground
          locationId={currentLocationId}
          sessionId={sessionId}
          timeOfDay={timeOfDay}
        />
      )}

      {npcsAtLocation.length > 0 && (
        <div data-testid="npc-portraits" className="flex gap-3 mt-3">
          {npcsAtLocation.map((npc) => (
            <NPCPortrait
              key={npc.npc_id}
              npcId={npc.npc_id}
              sessionId={sessionId}
            />
          ))}
        </div>
      )}

      <TurnErrorPanel error={error} usedFallback={usedFallback} onDismiss={clearError} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-4">
        <div className="lg:col-span-2 space-y-4">
          <NarrationPanel narration={currentNarration} isStreaming={isStreaming} isComplete={isComplete} streamingDuration={streamingDuration} stageLabel={stageLabel} fallbackNotice={streamFallbackNotice} />
          {/* TurnStageStatus removed - stage display is now integrated into NarrationPanel */}
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
              id="mobile-inventory-section"
              title={t('inventory')}
              defaultOpen={false}
            >
              <div className="px-4 pb-4">
                <InventoryPanel sessionId={sessionId} />
              </div>
            </CollapsibleSection>

            <CollapsibleSection
              id="mobile-location-section"
              title={t('locationMap')}
              defaultOpen={false}
            >
              <div className="px-4 pb-4">
                <LocationMapPanel sessionId={sessionId} currentLocationId={currentLocationId} />
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

            <QuestJournalEntryPoint sessionId={sessionId}>
              <CollapsibleSection
                id="mobile-quest-section"
                title={t('questJournal')}
                defaultOpen={false}
              >
                <div className="px-4 pb-4">
          <QuestJournalEntryPoint sessionId={sessionId} />
                </div>
              </CollapsibleSection>
            </QuestJournalEntryPoint>

            <CollapsibleSection
              id="mobile-relationship-section"
              title={t('relationships')}
              defaultOpen={false}
            >
              <div className="px-4 pb-4">
                <RelationshipPanel sessionId={sessionId} />
              </div>
            </CollapsibleSection>
           </div>
         </div>

        {/* Desktop: Side panel with State and Log */}
        <div className="hidden lg:block space-y-4">
          <StatePanel snapshot={snapshot} />
          <InventoryPanel sessionId={sessionId} />
          <LocationMapPanel sessionId={sessionId} currentLocationId={currentLocationId} />
          <LogPanel
            entries={logEntries}
            selectedEntryId={selectedLogEntryId}
            onSelectEntry={(entry) => setSelectedLogEntryId(entry.id)}
          />
          <QuestJournalPanel sessionId={sessionId} />
          <RelationshipPanel sessionId={sessionId} />
        </div>
      </div>
    </div>
  );
}
