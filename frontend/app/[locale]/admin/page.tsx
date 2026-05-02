'use client';

import React, { useState, useEffect } from 'react';
import {useTranslations} from 'next-intl';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Button } from '@/components/ui/Button';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { Tabs, TabList, Tab, TabPanel } from '@/components/ui/Tabs';
import {
  listWorlds, listChapters, listLocations,
  listNPCTemplates, listItemTemplates, listQuestTemplates,
  listEventTemplates, listPromptTemplates,
  updateWorld, updateChapter, updateLocation,
  updateNPCTemplate, updateItemTemplate, updateQuestTemplate,
  updateEventTemplate, updatePromptTemplate,
} from '@/lib/api';
import type {
  AdminWorld, AdminChapter, AdminLocation,
  AdminNPCTemplate, AdminItemTemplate, AdminQuestTemplate,
  AdminEventTemplate, AdminPromptTemplate,
} from '@/types/api';

export default function AdminPage() {
  return (
    <ProtectedRoute>
      <AdminContent />
    </ProtectedRoute>
  );
}

type AdminItem = AdminWorld | AdminChapter | AdminLocation | AdminNPCTemplate | AdminItemTemplate | AdminQuestTemplate | AdminEventTemplate | AdminPromptTemplate;

interface AdminSectionProps<T extends AdminItem> {
  title: string;
  fetchItems: () => Promise<T[]>;
  updateItem: (id: string, data: Partial<T>) => Promise<T>;
  columns: Array<{ key: keyof T; label: string }>;
}

function AdminSection<T extends AdminItem>({ title, fetchItems, updateItem, columns }: AdminSectionProps<T>) {
  const t = useTranslations('Admin');
  const [items, setItems] = useState<T[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Partial<T>>({});

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchItems();
      setItems(data);
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
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [fetchItems]);

  const handleEdit = (item: T) => {
    setEditingId(item.id);
    setEditValues(Object.fromEntries(columns.map(c => [c.key, item[c.key]])) as Partial<T>);
  };

  const handleSave = async () => {
    if (!editingId) return;
    try {
      await updateItem(editingId, editValues);
      setEditingId(null);
      await load();
    } catch {
      setError(t('failedToUpdate'));
    }
  };

  if (isLoading) return <Loading size="md" text={t('loading', {name: title})} />;
  if (error) return <ErrorMessage message={error} variant="card" onRetry={load} />;

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700">
              {columns.map(col => (
                <th key={String(col.key)} className="text-left p-2 text-slate-500 dark:text-slate-400">{col.label}</th>
              ))}
              <th className="text-left p-2 text-slate-500 dark:text-slate-400">{t('actions')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.id} className="border-b border-slate-100 dark:border-slate-800">
                {columns.map(col => (
                  <td key={String(col.key)} className="p-2">
                    {editingId === item.id ? (
                      <input
                        value={String(editValues[col.key] || '')}
                        onChange={e => setEditValues(prev => ({ ...prev, [col.key]: e.target.value }))}
                        className="px-2 py-1 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded text-sm w-full"
                      />
                    ) : (
                      String(item[col.key] || '-')
                    )}
                  </td>
                ))}
                <td className="p-2">
                  {editingId === item.id ? (
                    <div className="flex gap-1">
                      <Button size="sm" onClick={handleSave}>{t('save')}</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>{t('cancel')}</Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => handleEdit(item)}>{t('edit')}</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 && (
        <p className="text-center py-4 text-slate-500 dark:text-slate-400">{t('noItemsFound')}</p>
      )}
    </div>
  );
}

function AdminContent() {
  const t = useTranslations('Admin');
  const tabIds = ['worlds', 'chapters', 'locations', 'npcs', 'items', 'quests', 'events', 'prompts'];
  void tabIds;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-8">{t('dashboard')}</h1>

      <Tabs defaultTab="worlds">
        <TabList>
          <Tab value="worlds">{t('worlds')}</Tab>
          <Tab value="chapters">{t('chapters')}</Tab>
          <Tab value="locations">{t('locations')}</Tab>
          <Tab value="npcs">{t('npcs')}</Tab>
          <Tab value="items">{t('items')}</Tab>
          <Tab value="quests">{t('quests')}</Tab>
          <Tab value="events">{t('events')}</Tab>
          <Tab value="prompts">{t('prompts')}</Tab>
        </TabList>

        <TabPanel value="worlds">
          <AdminSection
            title={t('worlds')}
            fetchItems={listWorlds}
            updateItem={updateWorld}
            columns={[{ key: 'name', label: t('name') }]}
          />
        </TabPanel>
        <TabPanel value="chapters">
          <AdminSection
            title={t('chapters')}
            fetchItems={listChapters}
            updateItem={updateChapter}
            columns={[{ key: 'name', label: t('name') }, { key: 'sequence', label: t('sequence') }]}
          />
        </TabPanel>
        <TabPanel value="locations">
          <AdminSection
            title={t('locations')}
            fetchItems={listLocations}
            updateItem={updateLocation}
            columns={[{ key: 'name', label: t('name') }]}
          />
        </TabPanel>
        <TabPanel value="npcs">
          <AdminSection
            title={t('npcs')}
            fetchItems={listNPCTemplates}
            updateItem={updateNPCTemplate}
            columns={[{ key: 'name', label: t('name') }, { key: 'personality', label: t('personality') }]}
          />
        </TabPanel>
        <TabPanel value="items">
          <AdminSection
            title={t('items')}
            fetchItems={listItemTemplates}
            updateItem={updateItemTemplate}
            columns={[{ key: 'name', label: t('name') }, { key: 'rarity', label: t('rarity') }]}
          />
        </TabPanel>
        <TabPanel value="quests">
          <AdminSection
            title={t('quests')}
            fetchItems={listQuestTemplates}
            updateItem={updateQuestTemplate}
            columns={[{ key: 'name', label: t('name') }, { key: 'quest_type', label: t('type') }]}
          />
        </TabPanel>
        <TabPanel value="events">
          <AdminSection
            title={t('events')}
            fetchItems={listEventTemplates}
            updateItem={updateEventTemplate}
            columns={[{ key: 'name', label: t('name') }, { key: 'trigger_type', label: t('trigger') }]}
          />
        </TabPanel>
        <TabPanel value="prompts">
          <AdminSection
            title={t('prompts')}
            fetchItems={listPromptTemplates}
            updateItem={updatePromptTemplate}
            columns={[{ key: 'name', label: t('name') }, { key: 'purpose', label: t('purpose') }]}
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}
