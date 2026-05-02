'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { Loading } from '@/components/ui/Loading';

interface NarrationPanelProps {
  narration: string;
  isStreaming: boolean;
}

export function NarrationPanel({ narration, isStreaming }: NarrationPanelProps) {
  const t = useTranslations('Game');

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 min-h-[200px]">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('narration')}
      </h3>
      {isStreaming && !narration && (
        <Loading size="sm" text={t('storyUnfolds')} />
      )}
      {narration && (
        <div className="prose dark:prose-invert max-w-none">
          <p className="text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
            {narration}
            {isStreaming && <span className="animate-pulse">|</span>}
          </p>
        </div>
      )}
      {!isStreaming && !narration && (
        <p className="text-slate-400 dark:text-slate-500 italic">
          {t('enterActionToBegin')}
        </p>
      )}
    </div>
  );
}
