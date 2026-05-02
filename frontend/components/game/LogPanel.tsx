'use client';

import React from 'react';
import {useTranslations} from 'next-intl';

interface LogEntry {
  turnIndex: number;
  action: string;
  narration: string;
}

interface LogPanelProps {
  entries: LogEntry[];
}

export function LogPanel({ entries }: LogPanelProps) {
  const t = useTranslations('Game');

  if (entries.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('adventureLog')}
        </h3>
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('noTurnsYet')}</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('adventureLog')}
      </h3>
      <div className="space-y-3 max-h-[300px] overflow-y-auto">
        {entries.map((entry, index) => (
          <div key={index} className="text-sm border-l-2 border-indigo-300 dark:border-indigo-600 pl-3">
            <p className="font-medium text-slate-700 dark:text-slate-300">
              {t('turn', {turnIndex: entry.turnIndex})}: {entry.action}
            </p>
            <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
              {entry.narration}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
