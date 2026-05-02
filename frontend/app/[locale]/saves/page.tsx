'use client';

import React, { useState, useEffect } from 'react';
import {useTranslations} from 'next-intl';
import {useRouter} from '@/i18n/navigation';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { SaveSlotList } from '@/components/saves/SaveSlotList';
import { CreateSaveForm } from '@/components/saves/CreateSaveForm';
import { listSaveSlots, createSaveSlot, deleteSaveSlot } from '@/lib/api';
import type { SaveSlot } from '@/types/api';

export default function SavesPage() {
  return (
    <ProtectedRoute>
      <SavesContent />
    </ProtectedRoute>
  );
}

function SavesContent() {
  const router = useRouter();
  const t = useTranslations('Saves');
  const [saves, setSaves] = useState<SaveSlot[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SaveSlot | null>(null);

  const fetchSaves = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listSaveSlots();
      setSaves(data);
    } catch {
      setError(t('failedToLoad'));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchSaves();
  }, []);

  const handleCreateSave = async (name: string, slotNumber: number) => {
    const save = await createSaveSlot({ slot_number: slotNumber, name });
    setSaves((prev) => [...prev, { ...save, session_count: 0 }]);
    setShowCreateForm(false);
  };

  const handleDeleteSave = async () => {
    if (!deleteTarget) return;
    try {
      await deleteSaveSlot(deleteTarget.id);
      setSaves((prev) => prev.filter((s) => s.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch {
      setError(t('failedToDelete'));
    }
  };

  const handleSelectSave = (save: SaveSlot) => {
    router.push(`/saves/${save.id}`);
  };

  const usedSlotNumbers = saves.map((s) => s.slot_number);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100">
            {t('yourSaves')}
          </h1>
          <p className="mt-1 text-slate-600 dark:text-slate-400">
            {t('manageSaves')}
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          {t('newSave')}
        </Button>
      </div>

      {showCreateForm && (
        <div className="mb-8 p-6 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <h2 className="text-xl font-semibold mb-4">{t('createNewSave')}</h2>
          <CreateSaveForm
            onSubmit={handleCreateSave}
            onCancel={() => setShowCreateForm(false)}
            usedSlotNumbers={usedSlotNumbers}
          />
        </div>
      )}

      <SaveSlotList
        saves={saves}
        isLoading={isLoading}
        error={error}
        onSelect={handleSelectSave}
        onDelete={setDeleteTarget}
        onRetry={fetchSaves}
      />

      <Modal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title={t('deleteSave')}
      >
        <p className="text-slate-600 dark:text-slate-400 mb-4">
          {t('deleteConfirmation', {name: deleteTarget?.name || t('saveSlot', {slotNumber: deleteTarget?.slot_number || 0})})}
        </p>
        <div className="flex gap-3 justify-end">
          <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
            {t('cancel')}
          </Button>
          <Button variant="danger" onClick={handleDeleteSave}>
            {t('delete')}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
