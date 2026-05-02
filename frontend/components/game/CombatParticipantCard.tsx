'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { Badge } from '@/components/ui/Badge';
import type { CombatParticipant } from '@/types/api';

interface CombatParticipantCardProps {
  participant: CombatParticipant;
  isSelected: boolean;
  onSelect: (id: string) => void;
  isPlayer: boolean;
}

export function CombatParticipantCard({ participant, isSelected, onSelect, isPlayer }: CombatParticipantCardProps) {
  const t = useTranslations('Combat');
  const hpPercent = participant.max_hp > 0 ? (participant.hp / participant.max_hp) * 100 : 0;
  const hpColor = hpPercent > 50 ? 'bg-green-500' : hpPercent > 25 ? 'bg-yellow-500' : 'bg-red-500';

  return (
    <div
      className={`p-3 rounded-lg border cursor-pointer transition-all ${
        isSelected
          ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
          : participant.is_defeated
            ? 'border-slate-200 dark:border-slate-700 opacity-50'
            : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
      } ${isPlayer ? 'border-l-4 border-l-blue-500' : ''}`}
      onClick={() => !participant.is_defeated && onSelect(participant.entity_id)}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-slate-900 dark:text-slate-100">
          {participant.name}
        </span>
        <div className="flex gap-1">
          {isPlayer && <Badge variant="info" size="sm">{t('player')}</Badge>}
          {participant.is_defeated && <Badge variant="error" size="sm">{t('defeated')}</Badge>}
        </div>
      </div>
      <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${hpColor}`}
          style={{ width: `${hpPercent}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        {participant.hp}/{participant.max_hp} {t('hp')}
      </p>
    </div>
  );
}
