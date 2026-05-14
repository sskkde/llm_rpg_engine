'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';

interface DebugEmptyStateProps {
  message?: string;
  className?: string;
}

export function DebugEmptyState({ message, className = '' }: DebugEmptyStateProps) {
  const t = useTranslations('Debug');

  return (
    <Card className={`p-8 text-center ${className}`}>
      <div className="flex flex-col items-center gap-3">
        <svg
          className="w-12 h-12 text-slate-300 dark:text-slate-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <p className="text-slate-500 dark:text-slate-400">
          {message ?? t('emptyState.noData')}
        </p>
      </div>
    </Card>
  );
}
