'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import { Button } from '@/components/ui/Button';

interface RecommendedActionsProps {
  actions: string[];
  onSelect: (action: string) => void;
  isDisabled: boolean;
}

export function RecommendedActions({ actions, onSelect, isDisabled }: RecommendedActionsProps) {
  const t = useTranslations('Game');

  if (actions.length === 0) return null;

  return (
    <div>
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
        {t('recommendedActions')}
      </h3>
      <div className="flex flex-wrap gap-2">
        {actions.map((action, index) => (
          <Button
            key={index}
            variant="outline"
            size="sm"
            onClick={() => onSelect(action)}
            disabled={isDisabled}
          >
            {action}
          </Button>
        ))}
      </div>
    </div>
  );
}
