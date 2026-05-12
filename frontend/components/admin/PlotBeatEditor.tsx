'use client';

import {useCallback, useEffect, useState} from 'react';
import {useTranslations} from 'next-intl';
import {Button} from '@/components/ui/Button';
import {Loading} from '@/components/ui/Loading';
import {ErrorMessage} from '@/components/ui/ErrorMessage';
import {
  getPlotBeats,
  createPlotBeat,
  updatePlotBeat,
  deletePlotBeat,
} from '@/lib/api/adminContent';
import type {
  PlotBeatListItem,
  PlotBeatCreateRequest,
  PlotBeatUpdateRequest,
  PlotBeatCondition,
  PlotBeatEffect,
} from '@/types/api';

export function PlotBeatEditor() {
  const t = useTranslations('Admin');
  const [plotBeats, setPlotBeats] = useState<PlotBeatListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const [formData, setFormData] = useState<{
    logical_id: string;
    world_id: string;
    title: string;
    conditions: string;
    effects: string;
    priority: number;
    visibility: string;
    status: string;
  }>({
    logical_id: '',
    world_id: '',
    title: '',
    conditions: '[]',
    effects: '[]',
    priority: 0,
    visibility: 'conditional',
    status: 'pending',
  });

  const loadPlotBeats = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getPlotBeats();
      setPlotBeats(data);
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
    void loadPlotBeats();
  }, [loadPlotBeats]);

  const resetForm = () => {
    setFormData({
      logical_id: '',
      world_id: '',
      title: '',
      conditions: '[]',
      effects: '[]',
      priority: 0,
      visibility: 'conditional',
      status: 'pending',
    });
  };

  const handleEdit = (plotBeat: PlotBeatListItem) => {
    setEditingId(plotBeat.id);
    setIsCreating(false);
    setFormData({
      logical_id: plotBeat.logical_id,
      world_id: plotBeat.world_id,
      title: plotBeat.title,
      conditions: '[]',
      effects: '[]',
      priority: plotBeat.priority,
      visibility: plotBeat.visibility,
      status: plotBeat.status,
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
      let conditions: PlotBeatCondition[];
      let effects: PlotBeatEffect[];

      try {
        conditions = JSON.parse(formData.conditions || '[]');
      } catch {
        setError(t('invalidJsonConditions'));
        setIsSaving(false);
        return;
      }

      try {
        effects = JSON.parse(formData.effects || '[]');
      } catch {
        setError(t('invalidJsonEffects'));
        setIsSaving(false);
        return;
      }

      if (isCreating) {
        const createData: PlotBeatCreateRequest = {
          logical_id: formData.logical_id,
          world_id: formData.world_id,
          title: formData.title,
          conditions,
          effects,
          priority: formData.priority,
          visibility: formData.visibility,
          status: formData.status,
        };
        await createPlotBeat(createData);
      } else if (editingId) {
        const updateData: PlotBeatUpdateRequest = {
          title: formData.title,
          conditions,
          effects,
          priority: formData.priority,
          visibility: formData.visibility,
          status: formData.status,
        };
        await updatePlotBeat(editingId, updateData);
      }

      setEditingId(null);
      setIsCreating(false);
      resetForm();
      await loadPlotBeats();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || t('failedToUpdate'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (beatId: string) => {
    setIsSaving(true);
    setError(null);

    try {
      await deletePlotBeat(beatId);
      setDeleteConfirmId(null);
      await loadPlotBeats();
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

  if (isLoading) return <Loading size="md" text={t('loadingPlotBeats')} />;
  if (error && !isCreating && !editingId) {
    return <ErrorMessage message={error} variant="card" onRetry={loadPlotBeats} />;
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
          {t('plotBeats')}
        </h2>
        {!isCreating && !editingId && (
          <Button onClick={handleCreate}>{t('createPlotBeat')}</Button>
        )}
      </div>

      {(isCreating || editingId) && (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
            {isCreating ? t('createPlotBeat') : t('editPlotBeat')}
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
                {t('title')} *
              </label>
              <input
                type="text"
                value={formData.title}
                onChange={(e) => setFormData(prev => ({ ...prev, title: e.target.value }))}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('priority')}
              </label>
              <input
                type="number"
                value={formData.priority}
                onChange={(e) => setFormData(prev => ({ ...prev, priority: parseInt(e.target.value) || 0 }))}
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
                <option value="conditional">{t('visibilityConditional')}</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('status')}
              </label>
              <select
                value={formData.status}
                onChange={(e) => setFormData(prev => ({ ...prev, status: e.target.value }))}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
              >
                <option value="pending">{t('statusPending')}</option>
                <option value="active">{t('statusActive')}</option>
                <option value="completed">{t('statusCompleted')}</option>
              </select>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('conditions')} (JSON)
              </label>
              <textarea
                value={formData.conditions}
                onChange={(e) => setFormData(prev => ({ ...prev, conditions: e.target.value }))}
                rows={4}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-mono"
              />
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t('conditionsHelp')}
              </p>
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                {t('effects')} (JSON)
              </label>
              <textarea
                value={formData.effects}
                onChange={(e) => setFormData(prev => ({ ...prev, effects: e.target.value }))}
                rows={4}
                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-mono"
              />
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t('effectsHelp')}
              </p>
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
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('title')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('priority')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('visibility')}</th>
              <th className="text-left p-3 text-slate-500 dark:text-slate-400">{t('actions')}</th>
            </tr>
          </thead>
          <tbody>
            {plotBeats.map((beat) => (
              <tr key={beat.id} className="border-b border-slate-100 dark:border-slate-800">
                <td className="p-3 text-slate-900 dark:text-slate-100">{beat.logical_id}</td>
                <td className="p-3 text-slate-900 dark:text-slate-100">{beat.title}</td>
                <td className="p-3 text-slate-900 dark:text-slate-100">{beat.priority}</td>
                <td className="p-3 text-slate-900 dark:text-slate-100">{beat.visibility}</td>
                <td className="p-3">
                  {deleteConfirmId === beat.id ? (
                    <div className="flex gap-2">
                      <Button size="sm" variant="danger" onClick={() => handleDelete(beat.id)} disabled={isSaving}>
                        {t('confirm')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDeleteConfirmId(null)}>
                        {t('cancel')}
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button size="sm" variant="ghost" onClick={() => handleEdit(beat)}>
                        {t('edit')}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setDeleteConfirmId(beat.id)}>
                        {t('delete')}
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {plotBeats.length === 0 && (
          <p className="text-center py-8 text-slate-500 dark:text-slate-400">{t('noPlotBeatsFound')}</p>
        )}
      </div>
    </div>
  );
}
