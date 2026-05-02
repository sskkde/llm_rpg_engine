'use client';

import React from 'react';
import {useTranslations} from 'next-intl';

interface ConnectionStatusProps {
  isStreaming: boolean;
  usedFallback: boolean;
}

export function ConnectionStatus({ isStreaming, usedFallback }: ConnectionStatusProps) {
  const t = useTranslations('Game');

  return (
    <div className="flex items-center gap-2 text-xs">
      <div className={`w-2 h-2 rounded-full ${
        isStreaming
          ? 'bg-green-500 animate-pulse'
          : usedFallback
            ? 'bg-yellow-500'
            : 'bg-slate-400'
      }`} />
      <span className="text-slate-500 dark:text-slate-400">
        {isStreaming
          ? t('streaming')
          : usedFallback
            ? t('fallbackMode')
            : t('ready')}
      </span>
    </div>
  );
}
