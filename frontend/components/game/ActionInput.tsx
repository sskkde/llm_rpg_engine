'use client';

import React, { useState } from 'react';
import {useTranslations} from 'next-intl';
import { Button } from '@/components/ui/Button';

interface ActionInputProps {
  onSubmit: (action: string) => void;
  isDisabled: boolean;
}

export function ActionInput({ onSubmit, isDisabled }: ActionInputProps) {
  const t = useTranslations('Game');
  const [action, setAction] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (action.trim() && !isDisabled) {
      onSubmit(action.trim());
      setAction('');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:gap-3">
      <input
        type="text"
        value={action}
        onChange={(e) => setAction(e.target.value)}
        placeholder={t('whatDoYouDo')}
        disabled={isDisabled}
        className="flex-1 min-h-[44px] px-4 py-3 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
        data-testid="action-input"
      />
      <Button
        type="submit"
        disabled={isDisabled || !action.trim()}
        isLoading={isDisabled}
        data-testid="action-submit"
        className="w-full sm:w-auto"
      >
        {t('send')}
      </Button>
    </form>
  );
}
