'use client';

import React, { useState } from 'react';
import {useTranslations} from 'next-intl';
import { AdventureLogEntry } from '@/types/api';

interface LogPanelProps {
  entries: AdventureLogEntry[];
}

export function LogPanel({ entries }: LogPanelProps) {
  const t = useTranslations('Game');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleEntry = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

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
        {entries.map((entry) => {
          const isExpanded = expandedIds.has(entry.id);
          const isInitialScene = entry.event_type === 'initial_scene';
          
          return (
            <div key={entry.id} className="text-sm border-l-2 border-indigo-300 dark:border-indigo-600 pl-3">
              <button
                aria-expanded={isExpanded}
                aria-controls={`log-entry-${entry.id}`}
                onClick={() => toggleEntry(entry.id)}
                className="w-full text-left focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 rounded"
                aria-label={isExpanded ? t('collapseLogEntry') : t('expandLogEntry')}
              >
                <p className="font-medium text-slate-700 dark:text-slate-300">
                  {isInitialScene 
                    ? t('initialScene')
                    : t('turn', {turnIndex: entry.turn_no}) + (entry.action ? `: ${entry.action}` : '')
                  }
                </p>
                {!isExpanded && (
                  <p className="text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                    {entry.narration}
                  </p>
                )}
              </button>
              
              {isExpanded && (
                <div id={`log-entry-${entry.id}`} className="mt-2 space-y-2">
                  {isInitialScene ? (
                    <p className="text-slate-600 dark:text-slate-300">
                      {entry.narration}
                    </p>
                  ) : (
                    <>
                      {entry.action && (
                        <div>
                          <span className="font-medium text-slate-500 dark:text-slate-400">
                            {t('playerAction')}:
                          </span>
                          <p className="text-slate-700 dark:text-slate-300">
                            {entry.action}
                          </p>
                        </div>
                      )}
                      <div>
                        <span className="font-medium text-slate-500 dark:text-slate-400">
                          {t('turnNarration')}:
                        </span>
                        <p className="text-slate-600 dark:text-slate-300">
                          {entry.narration}
                        </p>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}