'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import type { SessionSnapshot } from '@/types/api';

interface StatePanelProps {
  snapshot: SessionSnapshot | null;
}

export function StatePanel({ snapshot }: StatePanelProps) {
  const t = useTranslations('Game');

  if (!snapshot) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('state')}
        </h3>
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('noStateLoaded')}</p>
      </div>
    );
  }

  const player = snapshot.player_state;
  const session = snapshot.session_state;

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('characterState')}
      </h3>
      {player && (
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">{t('hp')}</span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {player.hp}/{player.max_hp}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">{t('realm')}</span>
            <span className="font-medium text-slate-900 dark:text-slate-100">{player.realm_stage}</span>
          </div>
          {player.conditions && player.conditions.length > 0 && (
            <div>
              <span className="text-slate-500 dark:text-slate-400">{t('conditions')}</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {player.conditions.map((c, i) => (
                  <span key={i} className="px-2 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded text-xs">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {session && (
        <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700 space-y-2 text-sm">
          {session.current_time && (
            <div className="flex justify-between">
              <span className="text-slate-500 dark:text-slate-400">{t('time')}</span>
              <span className="text-slate-900 dark:text-slate-100">{session.current_time}</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-slate-500 dark:text-slate-400">{t('mode')}</span>
            <span className="text-slate-900 dark:text-slate-100">{session.active_mode}</span>
          </div>
        </div>
      )}
    </div>
  );
}
