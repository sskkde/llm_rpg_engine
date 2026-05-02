'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { SaveSlotCard } from './SaveSlotCard';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import type { SaveSlot } from '@/types/api';

interface SaveSlotListProps {
  saves: SaveSlot[];
  isLoading: boolean;
  error: string | null;
  onSelect: (save: SaveSlot) => void;
  onDelete: (save: SaveSlot) => void;
  onRetry: () => void;
}

export function SaveSlotList({ saves, isLoading, error, onSelect, onDelete, onRetry }: SaveSlotListProps) {
  const t = useTranslations('Saves');

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loading size="lg" text={t('loadingSaves')} />
      </div>
    );
  }

  if (error) {
    return <ErrorMessage message={error} variant="card" onRetry={onRetry} />;
  }

  if (saves.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-16 h-16 bg-slate-100 dark:bg-slate-800 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg
            className="w-8 h-8 text-slate-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
            />
          </svg>
        </div>
        <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100 mb-2">
          {t('noSavesYet')}
        </h3>
        <p className="text-slate-600 dark:text-slate-400">
          {t('createFirstSave')}
        </p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {saves.map((save) => (
        <SaveSlotCard
          key={save.id}
          save={save}
          onSelect={onSelect}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
