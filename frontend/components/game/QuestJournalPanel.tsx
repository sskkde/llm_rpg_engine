'use client';

import React, { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Loading } from '@/components/ui/Loading';
import { getPlayerQuests, getPlayerQuestDetail } from '@/lib/api';
import type { PlayerQuestSummary, PlayerQuestDetail } from '@/types/api';

interface QuestJournalPanelProps {
  sessionId: string;
}

type GameTranslator = ReturnType<typeof useTranslations<'Game'>>;

function StatusBadge({ status, t }: { status: string; t: GameTranslator }) {
  const statusConfig: Record<string, { bg: string; text: string; label: string }> = {
    active: {
      bg: 'bg-emerald-100 dark:bg-emerald-900/30',
      text: 'text-emerald-700 dark:text-emerald-300',
      label: t('questActive'),
    },
    completed: {
      bg: 'bg-blue-100 dark:bg-blue-900/30',
      text: 'text-blue-700 dark:text-blue-300',
      label: t('questCompleted'),
    },
    failed: {
      bg: 'bg-red-100 dark:bg-red-900/30',
      text: 'text-red-700 dark:text-red-300',
      label: t('questFailed'),
    },
    abandoned: {
      bg: 'bg-slate-100 dark:bg-slate-700/50',
      text: 'text-slate-500 dark:text-slate-400',
      label: t('questAbandoned'),
    },
  };

  const config = statusConfig[status] || statusConfig.active;

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${config.bg} ${config.text}`}>
      {config.label}
    </span>
  );
}

function ObjectiveItem({ objective }: { objective: { step_no: number; objective: string; completed: boolean } }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className={`flex-shrink-0 w-4 h-4 mt-0.5 rounded border ${
        objective.completed
          ? 'bg-emerald-500 border-emerald-500 text-white'
          : 'border-slate-300 dark:border-slate-600'
      } flex items-center justify-center`}>
        {objective.completed && (
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        )}
      </span>
      <span className={objective.completed ? 'text-slate-400 dark:text-slate-500 line-through' : 'text-slate-700 dark:text-slate-300'}>
        {objective.objective}
      </span>
    </div>
  );
}

function QuestListItem({
  quest,
  isSelected,
  onSelect,
  t,
}: {
  quest: PlayerQuestSummary;
  isSelected: boolean;
  onSelect: () => void;
  t: GameTranslator;
}) {
  const completedObjectives = quest.objectives.filter(o => o.completed).length;
  const totalObjectives = quest.objectives.length;

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-2 rounded transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
        isSelected
          ? 'bg-indigo-50 dark:bg-indigo-950/40'
          : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
      }`}
      aria-pressed={isSelected}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-900 dark:text-slate-100 truncate">
            {quest.title}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-1">
            {quest.description}
          </p>
        </div>
        <StatusBadge status={quest.status} t={t} />
      </div>
      {totalObjectives > 0 && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
          <span>{completedObjectives}/{totalObjectives}</span>
          <div className="flex-1 h-1 bg-slate-200 dark:bg-slate-700 rounded overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${(completedObjectives / totalObjectives) * 100}%` }}
            />
          </div>
        </div>
      )}
    </button>
  );
}

function QuestDetailView({
  quest,
  t,
}: {
  quest: PlayerQuestDetail;
  t: GameTranslator;
}) {
  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {quest.description}
        </p>
      </div>

      <div className="flex items-center gap-3 text-xs text-slate-400 dark:text-slate-500">
        <StatusBadge status={quest.status} t={t} />
        <span>{t('questStage', { stage: quest.stage })}</span>
      </div>

      {quest.started_at && (
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {t('questStarted', { date: new Date(quest.started_at).toLocaleDateString() })}
        </p>
      )}
      {quest.completed_at && (
        <p className="text-xs text-slate-400 dark:text-slate-500">
          {t('questCompletedDate', { date: new Date(quest.completed_at).toLocaleDateString() })}
        </p>
      )}

      {quest.objectives.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('questObjectives')}
          </h4>
          <div className="space-y-1.5">
            {quest.objectives.map((objective) => (
              <ObjectiveItem key={objective.step_no} objective={objective} />
            ))}
          </div>
        </div>
      )}

      {quest.steps && quest.steps.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {t('questSteps')}
          </h4>
          <div className="space-y-1">
            {(quest.steps || []).map((step, index) => (
              <div
                key={index}
                className={`flex items-start gap-2 text-sm ${
                  step.completed ? 'text-slate-400 dark:text-slate-500' : 'text-slate-700 dark:text-slate-300'
                }`}
              >
                <span className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium ${
                  step.completed
                    ? 'bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                    : 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                }`}>
                  {step.stage}
                </span>
                <span className={step.completed ? 'line-through' : ''}>
                  {step.description}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function QuestJournalPanel({ sessionId }: QuestJournalPanelProps) {
  const t = useTranslations('Game');
  const [quests, setQuests] = useState<PlayerQuestSummary[]>([]);
  const [selectedQuest, setSelectedQuest] = useState<PlayerQuestDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const fetchQuests = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getPlayerQuests(sessionId);
        if (mounted) {
          setQuests(data);
          if (data.length > 0) {
            const detail = await getPlayerQuestDetail(sessionId, data[0].quest_id);
            if (mounted) {
              setSelectedQuest(detail);
            }
          }
        }
      } catch {
        if (mounted) {
          setError(t('questsLoadError'));
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    fetchQuests();

    return () => {
      mounted = false;
    };
  }, [sessionId, t]);

  const handleSelectQuest = async (questId: string) => {
    setIsLoadingDetail(true);
    try {
      const detail = await getPlayerQuestDetail(sessionId, questId);
      setSelectedQuest(detail);
    } catch {
    } finally {
      setIsLoadingDetail(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('questJournal')}
        </h3>
        <div className="flex justify-center py-4">
          <Loading size="md" text={t('loadingQuests')} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('questJournal')}
        </h3>
        <p className="text-red-500 dark:text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (quests.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('questJournal')}
        </h3>
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('noQuestsYet')}</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
      <div className="p-4 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t('questJournal')}
          </h3>
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {t('questCount', { count: quests.length })}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-slate-200 dark:divide-slate-700">
        <div className="max-h-[300px] overflow-y-auto">
          <div className="p-2 space-y-1">
            {quests.map((quest) => (
              <QuestListItem
                key={quest.quest_id}
                quest={quest}
                isSelected={selectedQuest?.quest_id === quest.quest_id}
                onSelect={() => handleSelectQuest(quest.quest_id)}
                t={t}
              />
            ))}
          </div>
        </div>

        <div className="max-h-[300px] overflow-y-auto">
          {isLoadingDetail ? (
            <div className="flex justify-center py-8">
              <Loading size="sm" />
            </div>
          ) : selectedQuest ? (
            <div className="p-4">
              <QuestDetailView quest={selectedQuest} t={t} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full min-h-[200px] text-slate-400 dark:text-slate-500 text-sm">
              {t('selectQuest')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
