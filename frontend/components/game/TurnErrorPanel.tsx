'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { ErrorMessage } from '@/components/ui/ErrorMessage';

interface TurnErrorPanelProps {
  error: string | null;
  usedFallback: boolean;
  onDismiss: () => void;
}

export function TurnErrorPanel({ error, usedFallback, onDismiss }: TurnErrorPanelProps) {
  const t = useTranslations('Game');

  if (!error && !usedFallback) return null;

  return (
    <div className="space-y-2">
      {usedFallback && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3 text-sm text-yellow-800 dark:text-yellow-300">
          {t('streamingUnavailable')}
        </div>
      )}
      {error && (
        <ErrorMessage message={error} variant="card" onDismiss={onDismiss} />
      )}
    </div>
  );
}
