'use client';

import React from 'react';
import {useFormatter, useTranslations} from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import type { SaveSlot } from '@/types/api';

interface SaveSlotCardProps {
  save: SaveSlot;
  onSelect: (save: SaveSlot) => void;
  onDelete: (save: SaveSlot) => void;
}

export function SaveSlotCard({ save, onSelect, onDelete }: SaveSlotCardProps) {
  const t = useTranslations('Saves');
  const format = useFormatter();
  const formattedDate = format.dateTime(new Date(save.created_at), {
    dateStyle: 'medium',
    timeStyle: 'short',
  });

  return (
    <Card className="p-4 hover:shadow-lg transition-shadow cursor-pointer" onClick={() => onSelect(save)}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {save.name || t('saveSlot', {slotNumber: save.slot_number})}
            </h3>
            <Badge variant="info" size="sm">
              {t('slotNumber', {slotNumber: save.slot_number})}
            </Badge>
          </div>
          <div className="text-sm text-slate-600 dark:text-slate-400 space-y-1">
            <p>{t('created', {date: formattedDate})}</p>
            <p>{t('sessionCount', {count: save.session_count})}</p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(save);
          }}
          className="text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20"
        >
          {t('delete')}
        </Button>
      </div>
    </Card>
  );
}
