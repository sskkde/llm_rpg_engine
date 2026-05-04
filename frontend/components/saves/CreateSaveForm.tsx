'use client';

import React, { useState } from 'react';
import {useTranslations} from 'next-intl';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { APIError } from '@/lib/api';

interface CreateSaveFormProps {
  onSubmit: (name: string, slotNumber: number) => Promise<void>;
  onCancel: () => void;
  usedSlotNumbers: number[];
}

export function CreateSaveForm({ onSubmit, onCancel, usedSlotNumbers }: CreateSaveFormProps) {
  const t = useTranslations('Saves');
  const [name, setName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const defaultSlot = Array.from({ length: 10 }, (_, i) => i + 1).find(
    (n) => !usedSlotNumbers.includes(n)
  ) || 1;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);

    try {
      await onSubmit(name || t('saveSlot', {slotNumber: defaultSlot}), defaultSlot);
    } catch (err) {
      if (err instanceof APIError) {
        if (err.status === 409) {
          setError(t('saveSlotInUse'));
        } else {
          setError(err.detail || t('failedToCreate'));
        }
      } else {
        setError(t('unexpectedError'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />
      )}

      <Input
        label={t('saveName')}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('saveSlot', {slotNumber: defaultSlot})}
        disabled={isLoading}
      />

      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t('saveSlot', {slotNumber: defaultSlot})}
      </p>

      <div className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={isLoading} className="w-full sm:w-auto">
          {t('cancel')}
        </Button>
        <Button type="submit" isLoading={isLoading} className="w-full sm:w-auto">
          {t('createSave')}
        </Button>
      </div>
    </form>
  );
}
