'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { getSessionTimeline, getTurnTimeline } from '@/lib/api';
import type { TimelineTurn, TurnTimelineDetail, TimelineResponse } from '@/types/api';

interface TimelineViewerProps {
  sessionId: string;
}

const PAGE_SIZE = 20;

export function TimelineViewer({ sessionId }: TimelineViewerProps) {
  const t = useTranslations('Debug');
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [selectedTurn, setSelectedTurn] = useState<TurnTimelineDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingTurn, setIsLoadingTurn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [turnError, setTurnError] = useState<string | null>(null);
  const [startTurn, setStartTurn] = useState<string>('');
  const [endTurn, setEndTurn] = useState<string>('');
  const [offset, setOffset] = useState(0);

  const loadTimeline = useCallback(async (newOffset = 0) => {
    if (!sessionId.trim()) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await getSessionTimeline(
        sessionId,
        startTurn ? Number(startTurn) : undefined,
        endTurn ? Number(endTurn) : undefined,
        PAGE_SIZE,
        newOffset,
      );
      setTimeline(data);
      setOffset(newOffset);
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
  }, [sessionId, startTurn, endTurn, t]);

  useEffect(() => {
    if (sessionId.trim()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOffset(0);
      void loadTimeline(0);
    }
  }, [sessionId, loadTimeline]);

  const handleTurnClick = async (turn: TimelineTurn) => {
    setIsLoadingTurn(true);
    setTurnError(null);
    try {
      const detail = await getTurnTimeline(sessionId, turn.turn_no);
      setSelectedTurn(detail);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setTurnError(t('adminRequired'));
      } else {
        setTurnError(t('failedToLoad'));
      }
    } finally {
      setIsLoadingTurn(false);
    }
  };

  const handleFilter = () => {
    setOffset(0);
    void loadTimeline(0);
  };

  const handlePrevPage = () => {
    const newOffset = Math.max(0, offset - PAGE_SIZE);
    void loadTimeline(newOffset);
  };

  const handleNextPage = () => {
    void loadTimeline(offset + PAGE_SIZE);
  };

  const handleBackToList = () => {
    setSelectedTurn(null);
    setTurnError(null);
  };

  if (!sessionId.trim()) {
    return <DebugEmptyState message={t('emptyState.noSession')} />;
  }

  if (isLoading && !timeline) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error) {
    return <ErrorMessage message={error} variant="card" onRetry={() => loadTimeline(0)} />;
  }

  if (selectedTurn) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('turn', { turnIndex: selectedTurn.turn_no })}
          </h3>
          <Button variant="ghost" onClick={handleBackToList}>
            {t('backToList')}
          </Button>
        </div>

        {turnError && <ErrorMessage message={turnError} variant="card" />}

        <Card className="p-4">
          <div className="space-y-4">
            <div>
              <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t('timestamp')}:
              </span>
              <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">
                {selectedTurn.timestamp}
              </span>
            </div>

            <div>
              <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t('eventType')}:
              </span>
              <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">
                {selectedTurn.event_type}
              </span>
            </div>

            {selectedTurn.player_action && (
              <div>
                <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                  {t('playerAction')}:
                </span>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 p-2 rounded">
                  {selectedTurn.player_action}
                </p>
              </div>
            )}

            <div>
              <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t('narration')}:
              </span>
              <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 p-2 rounded whitespace-pre-wrap">
                {selectedTurn.narration}
              </p>
            </div>

            {selectedTurn.npc_actions.length > 0 && (
              <div>
                <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                  {t('npcActions')}:
                </span>
                <ul className="mt-1 space-y-1">
                  {selectedTurn.npc_actions.map((action, idx) => (
                    <li key={idx} className="text-sm text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 p-2 rounded">
                      {action}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t('eventsCommitted')}:
              </span>
              <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">
                {selectedTurn.events_committed}
              </span>
            </div>

            {selectedTurn.world_time && (
              <div>
                <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
                  {t('worldTime')}:
                </span>
                <div className="mt-1 text-sm text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 p-2 rounded">
                  {selectedTurn.world_time.calendar && <span>{selectedTurn.world_time.calendar} </span>}
                  {selectedTurn.world_time.season && <span>{selectedTurn.world_time.season} </span>}
                  {selectedTurn.world_time.day !== undefined && <span>Day {selectedTurn.world_time.day} </span>}
                  {selectedTurn.world_time.period && <span>{selectedTurn.world_time.period}</span>}
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3 items-end">
        <div className="flex-1">
          <Input
            label={t('startTurn')}
            type="number"
            min={1}
            value={startTurn}
            onChange={(e) => setStartTurn(e.target.value)}
            placeholder="1"
          />
        </div>
        <div className="flex-1">
          <Input
            label={t('endTurn')}
            type="number"
            min={1}
            value={endTurn}
            onChange={(e) => setEndTurn(e.target.value)}
            placeholder="100"
          />
        </div>
        <Button onClick={handleFilter} disabled={isLoading}>
          {t('filter')}
        </Button>
      </div>

      {isLoading && <Loading size="sm" text={t('loading')} />}

      {timeline && (
        <>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {t('totalTurns', { count: timeline.total_turns })}
          </div>

          <div className="space-y-3 max-h-[500px] overflow-y-auto">
            {timeline.turns.map((turn) => (
              <button
                key={turn.turn_no}
                onClick={() => handleTurnClick(turn)}
                disabled={isLoadingTurn}
                className="w-full text-left bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 hover:border-indigo-300 dark:hover:border-indigo-600 transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center text-sm font-medium text-indigo-600 dark:text-indigo-400">
                      {turn.turn_no}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                        {t('turn', { turnIndex: turn.turn_no })}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {turn.timestamp}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs px-2 py-1 bg-slate-100 dark:bg-slate-700 rounded text-slate-600 dark:text-slate-400">
                    {turn.event_type}
                  </span>
                </div>

                {turn.npc_actions && turn.npc_actions.length > 0 && (
                  <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {t('npcActions')}: {turn.npc_actions.join(', ')}
                  </div>
                )}

                {turn.narration_excerpt && (
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 line-clamp-2">
                    {turn.narration_excerpt}
                  </p>
                )}
              </button>
            ))}

            {timeline.turns.length === 0 && (
              <DebugEmptyState message={t('noTurnsFound')} />
            )}
          </div>

          <div className="flex items-center justify-between pt-4">
            <Button
              variant="outline"
              onClick={handlePrevPage}
              disabled={offset === 0 || isLoading}
            >
              {t('previous')}
            </Button>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {t('showingTurns', { start: offset + 1, end: offset + timeline.turns.length })}
            </span>
            <Button
              variant="outline"
              onClick={handleNextPage}
              disabled={!timeline.has_more || isLoading}
            >
              {t('next')}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
