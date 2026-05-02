'use client';

import React, { useState } from 'react';
import {useTranslations} from 'next-intl';
import { Button } from '@/components/ui/Button';
import type { CombatActionRequest } from '@/types/api';

interface CombatActionFormProps {
  onSubmit: (action: CombatActionRequest) => void;
  isDisabled: boolean;
  hasTarget: boolean;
}

export function CombatActionForm({ onSubmit, isDisabled, hasTarget }: CombatActionFormProps) {
  const t = useTranslations('Combat');
  const [actionType, setActionType] = useState<CombatActionRequest['action_type']>('attack');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({ action_type: actionType });
  };

  const actions: Array<{ value: CombatActionRequest['action_type']; label: string }> = [
    { value: 'attack', label: t('attack') },
    { value: 'defend', label: t('defend') },
    { value: 'skill', label: t('skill') },
    { value: 'item', label: t('item') },
    { value: 'flee', label: t('flee') },
  ];

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <Button
            key={action.value}
            type="button"
            variant={actionType === action.value ? 'primary' : 'outline'}
            size="sm"
            onClick={() => setActionType(action.value)}
            disabled={isDisabled}
          >
            {action.label}
          </Button>
        ))}
      </div>
      {actionType === 'attack' && !hasTarget && (
        <p className="text-sm text-yellow-600 dark:text-yellow-400">
          {t('selectTarget')}
        </p>
      )}
      <Button
        type="submit"
        disabled={isDisabled || (actionType === 'attack' && !hasTarget)}
        isLoading={isDisabled}
        className="w-full"
      >
        {t('executeAction')}
      </Button>
    </form>
  );
}
