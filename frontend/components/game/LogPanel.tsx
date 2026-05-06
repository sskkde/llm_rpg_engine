'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { AdventureLogEntry } from '@/types/api';

interface LogPanelProps {
  entries: AdventureLogEntry[];
  selectedEntryId?: string | null;
  onSelectEntry?: (entry: AdventureLogEntry) => void;
}

export function LogPanel({ entries, selectedEntryId, onSelectEntry }: LogPanelProps) {
  const t = useTranslations('Game');

  if (entries.length === 0) {
    return (
      <div data-testid="adventure-log" className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('adventureLog')}
        </h3>
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('noTurnsYet')}</p>
      </div>
    );
  }

  return (
    <div data-testid="adventure-log" className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('adventureLog')}
      </h3>
      <div className="space-y-3 max-h-[300px] overflow-y-auto">
        {entries.map((entry) => {
          const isInitialScene = entry.event_type === 'initial_scene';
          const isSelected = selectedEntryId === entry.id;
          const title = isInitialScene
            ? t('initialScene')
            : t('turn', {turnIndex: entry.turn_no}) + (entry.action ? `: ${entry.action}` : '');
          
          return (
            <div
              key={entry.id}
              data-testid="adventure-log-entry"
              className={`text-sm border-l-2 pl-3 ${
                isSelected
                  ? 'border-indigo-500 dark:border-indigo-400'
                  : 'border-indigo-300 dark:border-indigo-600'
              }`}
            >
              <button
                aria-pressed={isSelected}
                onClick={() => onSelectEntry?.(entry)}
                className={`w-full rounded px-2 py-1 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
                  isSelected
                    ? 'bg-indigo-50 dark:bg-indigo-950/40'
                    : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                }`}
                aria-label={`${t('showLogEntry')}: ${title}`}
              >
                <p className="font-medium text-slate-700 dark:text-slate-300">
                  {title}
                </p>
                <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                  {entry.narration}
                </p>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
