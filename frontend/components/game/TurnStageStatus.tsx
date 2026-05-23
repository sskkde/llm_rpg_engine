'use client';

import React from 'react';
import type { TurnStageState } from '@/types/api';

interface TurnStageStatusProps {
  currentStage: TurnStageState | null;
}

export function TurnStageStatus({ currentStage }: TurnStageStatusProps) {
  if (!currentStage) return null;

  let displayText = currentStage.label;
  if (currentStage.actorName && currentStage.label) {
    const cleanLabel = currentStage.label.replace(/\.\.\./g, '');
    displayText = `${currentStage.actorName}\u6B63\u5728${cleanLabel}`;
  }

  const hasProgress = currentStage.progress !== undefined && currentStage.progress !== null;

  return (
    <div className="bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800 rounded-lg px-4 py-3">
      <div className="flex items-center gap-2">
        <div className="animate-spin w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full" />
        <span className="text-sm text-indigo-700 dark:text-indigo-300">
          {displayText}
        </span>
      </div>
      {hasProgress && (
        <div className="mt-2 w-full h-1 bg-indigo-200 dark:bg-indigo-800 rounded overflow-hidden">
          <div
            className="h-full bg-indigo-500 transition-all duration-300"
            style={{ width: `${currentStage.progress}%` }}
          />
        </div>
      )}
    </div>
  );
}
