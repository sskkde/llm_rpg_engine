'use client';

import {useCallback, useEffect, useState} from 'react';
import {useTranslations} from 'next-intl';
import {Button} from '@/components/ui/Button';
import {Loading} from '@/components/ui/Loading';
import {ErrorMessage} from '@/components/ui/ErrorMessage';
import {
  getFactions,
  createFaction,
  updateFaction,
  deleteFaction,
} from '@/lib/api/adminContent';
import type {
  FactionListItem,
  FactionCreateRequest,
  FactionUpdateRequest,
  FactionGoal,
} from '@/types/api';

export function FactionEditor() {
  const t = useTranslations('Admin');
  const [factions, setFactions] = useState<FactionListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const [formData, setFormData] = useState<{
    logical_id: string;
    world_id: string;
    name: string;
    ideology: string;
    goals: string;
    visibility: string;
    status: string;
  }>({
    logical_id: '',
    world_id: '',
    name: '',
    ideology: '{}',
    goals: '[]',
    visibility: 'public',
    status: 'active',
  });

  const loadFactions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getFactions();
      setFactions(data);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadFactions();
  }, [loadFactions]);

  const resetForm = () => {
    setFormData({
      logical_id: '',
      world_id: '',
      name: '',
      ideology: '{}',
      goals: '[]',
      visibility: 'public',
      status: 'active',
    });
  };

  const handleEdit = (faction: FactionListItem) => {
    setEditingId(faction.id);
    setIsCreating(false);
    setFormData({
      logical_id: faction.logical_id,
      world_id: faction.world_id,
      name: faction.name,
      ideology: '{}',
      goals: '[]',
      visibility: faction.visibility,
      status: faction.status,
    });
  };

  const handleCreate = () => {
    setIsCreating(true);
    setEditingId(null);
    resetForm();
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);

    try {
      let ideology: Record<string, unknown>;
      let goals: FactionGoal[];

      try {
        ideology = JSON.parse(formData.ideology || '{}');
      } catch {
        setError(t('invalidJsonIdeology'));
        setIsSaving(false);
        return;
      }

      try {
        goals = JSON.parse(formData.goals || '[]');
      } catch {
        setError(t('invalidJsonGoals'));
        setIsSaving(false);
        return;
      }

      if (isCreating) {
        const createData: FactionCreateRequest = {
          logical_id: formData.logical_id,
          world_id: formData.world_id,
          name: formData.name,
          ideology,
          goals,
          visibility: formData.visibility,
          status: formData.status,
        };
        await createFaction(createData);
      } else if (editingId) {
        const updateData: FactionUpdateRequest = {
          name: formData.name,
          ideology,
          goals,
          visibility: formData.visibility,
          status: formData.status,
        };
        await updateFaction(editingId, updateData);
      }

      setEditingId(null);
      setIsCreating(false);
      resetForm();
      await loadFactions();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || t('failedToUpdate'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (factionId: string) => {
    setIsSaving(true);
    setError(null);

    try {
      await deleteFaction(factionId);
      setDeleteConfirmId(null);
      await loadFactions();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || t('failedToDelete'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setEditingId(null);
    setIsCreating(false);
    resetForm();
    setError(null);
  };

  if (isLoading) return <Loading size="md" text={t('loadingFactions')} />;
  if (error && !isCreating && !editingId) {
    return <ErrorMessage message={error} variant="card" onRetry={loadFactions} />;
  }

  return (
    <div className="space-y-6">
      {error && (isCreating || editingId) && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <p className="text-red-800 dark:text-red-200">{error}</p>
        </div>
      )}

      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t('factions')}
        </h2>
        {!isCreating && !editingId && (
          <Button onClick={handleCreate}>{t('createFaction')}</Button>
        )}
      </div>

      {(isCreating || editingId) && (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
            {isCreating ? t('createFaction') : t('editFaction')}
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('logicalId')} *
              </label>
              <input
                type="text"
                value={formData.logical_id}
                onChange={(e) => setFormData(prev => ({ ...prev, logical_id: e.target.value }))}
                disabled={!isCreating}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm disabled:opacity-50"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('worldId')} *
              </label>
              <input
                type="text"
                value={formData.world_id}
                onChange={(e) => setFormData(prev => ({ ...prev, world_id: e.target.value }))}
                disabled={!isCreating}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm disabled:opacity-50"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('name')} *
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('visibility')}
              </label>
              <select
                value={formData.visibility}
                onChange={(e) => setFormData(prev => ({ ...prev, visibility: e.target.value }))}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
              >
                <option value="public">{t('visibilityPublic')}</option>
                <option value="hidden">{t('visibilityHidden')}</option>
              </select>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('ideology')} (JSON)
              </label>
              <textarea
                value={formData.ideology}
                onChange={(e) => setFormData(prev => ({ ...prev, ideology: e.target.value }))}
                rows={3}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-mono"
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('goals')} (JSON)
              </label>
              <textarea
                value={formData.goals}
                onChange={(e) => setFormData(prev => ({ ...prev, goals: e.target.value }))}
                rows={3}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end gap-2 mt-4">
            <Button variant="ghost" onClick={handleCancel}>{t('cancel')}</Button>
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? t('saving') : t('save')}
            </Button>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700">
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('logicalId')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('name')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('worldId')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('visibility')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('actions')}</th>
            </tr>
          </thead>
          <tbody>
            {factions.map((faction) => (
              <tr key={faction.id} className="border-b border-slate-100 dark:border-slate-800">
                <td className="p-3 text-slate-900 dark:text-slate-100">{faction.logical_id}</td>
                <td className="p-3 text-slate-900 dark:text-slate-100">{faction.name}</td>
                <td className="p-3 text-slate-600 dark:text-slate-400 text-xs">{faction.world_id}</td>
                <td className="p-3 text-slate-900 dark:text-slate-100">{faction.visibility}</td>
                <td className="p-3">
                  {deleteConfirmId === faction.id ? (
                    <div className="flex gap-2">
                      <Button size="sm" variant="danger" onClick={() => handleDelete(faction.id)} disabled={isSaving}>
                        {t('confirm')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDeleteConfirmId(null)}>
                        {t('cancel')}
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => handleEdit(faction)}>
                        {t('edit')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDeleteConfirmId(faction.id)}>
                        {t('delete')}
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {factions.length === 0 && (
          <p className="text-center py-8 text-slate-500 dark:text-slate-400">{t('noFactionsFound')}</p>
        )}
      </div>
    </div>
  );
}
