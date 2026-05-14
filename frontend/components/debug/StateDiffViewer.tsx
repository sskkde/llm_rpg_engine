'use client';

import React, { useState, useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { Badge } from '@/components/ui/Badge';
import type { StateDiffEntryResponse, StateDiffResponse } from '@/types/api';

interface StateDiffViewerProps {
  stateDiff: StateDiffResponse;
  maxEntries?: number;
}

type StateCategory = 'player' | 'npc' | 'inventory' | 'quest' | 'location' | 'other';

interface CategorizedDiff {
  category: StateCategory;
  entries: StateDiffEntryResponse[];
}

function categorizePath(path: string): StateCategory {
  if (path.startsWith('player_state.') || path.startsWith('player.')) return 'player';
  if (path.startsWith('npc_states.') || path.startsWith('npc.')) return 'npc';
  if (path.startsWith('inventory.') || path.startsWith('items.')) return 'inventory';
  if (path.startsWith('quest_states.') || path.startsWith('quests.')) return 'quest';
  if (path.startsWith('location_states.') || path.startsWith('locations.')) return 'location';
  return 'other';
}

function formatValue(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function DiffEntryRow({ entry }: { entry: StateDiffEntryResponse }) {
  const t = useTranslations('Debug');

  const getOperationStyles = () => {
    switch (entry.operation) {
      case 'add':
        return {
          badge: 'success' as const,
          border: 'border-l-green-500',
          bg: 'bg-green-50 dark:bg-green-900/20',
        };
      case 'remove':
        return {
          badge: 'error' as const,
          border: 'border-l-red-500',
          bg: 'bg-red-50 dark:bg-red-900/20',
        };
      case 'change':
        return {
          badge: 'warning' as const,
          border: 'border-l-amber-500',
          bg: 'bg-amber-50 dark:bg-amber-900/20',
        };
      default:
        return {
          badge: 'neutral' as const,
          border: 'border-l-slate-500',
          bg: 'bg-slate-50 dark:bg-slate-800',
        };
    }
  };

  const styles = getOperationStyles();

  const operationLabels: Record<string, string> = {
    add: t('added'),
    remove: t('removed'),
    change: t('changed'),
  };

  return (
    <div className={`p-3 border-l-4 ${styles.border} ${styles.bg} rounded-r`}>
      <div className="flex items-center gap-2 mb-2">
        <Badge variant={styles.badge} size="sm">
          {operationLabels[entry.operation] || entry.operation}
        </Badge>
        <code className="text-xs font-mono text-slate-700 dark:text-slate-300 flex-1 truncate">
          {entry.path}
        </code>
      </div>

      {entry.operation === 'change' && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className="text-xs text-red-600 dark:text-red-400 font-medium mb-1 block">
              {t('oldValue')}
            </span>
            <pre className="text-xs bg-white dark:bg-slate-900 p-2 rounded overflow-auto max-h-32 font-mono">
              {formatValue(entry.old_value)}
            </pre>
          </div>
          <div>
            <span className="text-xs text-green-600 dark:text-green-400 font-medium mb-1 block">
              {t('newValue')}
            </span>
            <pre className="text-xs bg-white dark:bg-slate-900 p-2 rounded overflow-auto max-h-32 font-mono">
              {formatValue(entry.new_value)}
            </pre>
          </div>
        </div>
      )}

      {entry.operation === 'add' && (
        <div>
          <span className="text-xs text-green-600 dark:text-green-400 font-medium mb-1 block">
            {t('newValue')}
          </span>
          <pre className="text-xs bg-white dark:bg-slate-900 p-2 rounded overflow-auto max-h-32 font-mono">
            {formatValue(entry.new_value)}
          </pre>
        </div>
      )}

      {entry.operation === 'remove' && (
        <div>
          <span className="text-xs text-red-600 dark:text-red-400 font-medium mb-1 block">
            {t('oldValue')}
          </span>
          <pre className="text-xs bg-white dark:bg-slate-900 p-2 rounded overflow-auto max-h-32 font-mono">
            {formatValue(entry.old_value)}
          </pre>
        </div>
      )}
    </div>
  );
}

export function StateDiffViewer({ stateDiff, maxEntries = 50 }: StateDiffViewerProps) {
  const t = useTranslations('Debug');
  const [expandedCategories, setExpandedCategories] = useState<Set<StateCategory>>(new Set());

  const categorizedDiffs = useMemo<CategorizedDiff[]>(() => {
    const categories: Map<StateCategory, StateDiffEntryResponse[]> = new Map();

    for (const entry of stateDiff.entries) {
      const category = categorizePath(entry.path);
      const existing = categories.get(category) || [];
      existing.push(entry);
      categories.set(category, existing);
    }

    const result: CategorizedDiff[] = [];
    const categoryOrder: StateCategory[] = ['player', 'npc', 'inventory', 'quest', 'location', 'other'];

    for (const category of categoryOrder) {
      const entries = categories.get(category);
      if (entries && entries.length > 0) {
        result.push({ category, entries });
      }
    }

    return result;
  }, [stateDiff.entries]);

  const categoryLabels: Record<StateCategory, string> = {
    player: t('playerCategory'),
    npc: t('npcCategory'),
    inventory: t('inventoryCategory'),
    quest: t('questCategory'),
    location: t('locationCategory'),
    other: t('otherCategory'),
  };

  const toggleCategory = (category: StateCategory) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  if (stateDiff.entries.length === 0) {
    return (
      <Card className="p-4">
        <p className="text-sm text-slate-500 dark:text-slate-400 text-center">
          {t('noStateChanges')}
        </p>
      </Card>
    );
  }

  const totalEntries = stateDiff.entries.length;
  const displayedEntries = Math.min(totalEntries, maxEntries);
  const hasMore = totalEntries > maxEntries;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm">
        <div className="flex items-center gap-2">
          <Badge variant="success">{t('added')}</Badge>
          <span className="text-slate-600 dark:text-slate-400">
            {stateDiff.added_keys.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="error">{t('removed')}</Badge>
          <span className="text-slate-600 dark:text-slate-400">
            {stateDiff.removed_keys.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="warning">{t('changed')}</Badge>
          <span className="text-slate-600 dark:text-slate-400">
            {stateDiff.changed_keys.length}
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {categorizedDiffs.map(({ category, entries }) => {
          const isExpanded = expandedCategories.has(category);
          const categoryEntries = entries.slice(0, maxEntries);

          return (
            <CollapsibleSection
              key={category}
              title={categoryLabels[category]}
              summary={`(${entries.length})`}
              open={isExpanded}
              onToggle={() => toggleCategory(category)}
            >
              <div className="p-4 space-y-3">
                {categoryEntries.map((entry, index) => (
                  <DiffEntryRow key={`${entry.path}-${index}`} entry={entry} />
                ))}
                {entries.length > maxEntries && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 text-center pt-2">
                    {t('showingEntries', { shown: maxEntries, total: entries.length })}
                  </p>
                )}
              </div>
            </CollapsibleSection>
          );
        })}
      </div>

      {hasMore && (
        <p className="text-xs text-slate-500 dark:text-slate-400 text-center">
          {t('showingEntries', { shown: displayedEntries, total: totalEntries })}
        </p>
      )}
    </div>
  );
}
