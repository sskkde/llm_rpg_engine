'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import type { CombatEvent } from '@/types/api';

interface CombatEventFeedProps {
  events: CombatEvent[];
}

export function CombatEventFeed({ events }: CombatEventFeedProps) {
  const t = useTranslations('Combat');

  if (events.length === 0) {
    return (
      <div className="text-center py-4 text-sm text-slate-500 dark:text-slate-400">
        {t('noEventsYet')}
      </div>
    );
  }

  return (
    <div className="space-y-2 max-h-[200px] overflow-y-auto">
      {events.map((event) => (
        <div
          key={event.event_id}
          className="text-sm p-2 bg-slate-50 dark:bg-slate-800 rounded"
        >
          <span className="text-slate-500 dark:text-slate-400">
            {t('round', {roundNumber: event.round})}:
          </span>{' '}
          <span className="text-slate-700 dark:text-slate-300">
            {event.event_type}
          </span>
        </div>
      ))}
    </div>
  );
}
