'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { getPlayerInventory, getPlayerInventoryStats } from '@/lib/api';
import type { PlayerInventoryItem, InventoryStats } from '@/types/api';

interface InventoryPanelProps {
  sessionId: string;
}

const CATEGORY_ALL = 'all';
const CATEGORIES = [CATEGORY_ALL, 'consumable', 'equipment', 'quest_item', 'key_item'] as const;
type CategoryFilter = typeof CATEGORIES[number];

const RARITY_COLORS: Record<string, string> = {
  common: 'bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300',
  uncommon: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300',
  rare: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300',
  epic: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300',
  legendary: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
};

function getRarityColor(rarity: string): string {
  return RARITY_COLORS[rarity.toLowerCase()] || RARITY_COLORS.common;
}

export function InventoryPanel({ sessionId }: InventoryPanelProps) {
  const t = useTranslations('Game');
  const [items, setItems] = useState<PlayerInventoryItem[]>([]);
  const [stats, setStats] = useState<InventoryStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>(CATEGORY_ALL);
  const [selectedItem, setSelectedItem] = useState<PlayerInventoryItem | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const [inventoryData, statsData] = await Promise.all([
          getPlayerInventory(sessionId, selectedCategory === CATEGORY_ALL ? undefined : selectedCategory),
          getPlayerInventoryStats(sessionId),
        ]);
        if (!cancelled) {
          setItems(inventoryData);
          setStats(statsData);
        }
      } catch {
        if (!cancelled) {
          setError(t('inventoryLoadError'));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    fetch();
    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedCategory, t]);

  const handleCategoryChange = (category: CategoryFilter) => {
    setSelectedCategory(category);
    setSelectedItem(null);
  };

  const handleItemClick = (item: PlayerInventoryItem) => {
    setSelectedItem(selectedItem?.id === item.id ? null : item);
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('inventory')}
        </h3>
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('inventory')}
        </h3>
        <p className="text-red-500 dark:text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('inventory')}
      </h3>

      {stats && (
        <div className="mb-3 pb-3 border-b border-slate-200 dark:border-slate-700">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
            <span>{t('inventoryTotalItems')}: {stats.total_items}</span>
            <span>{t('inventoryUniqueItems')}: {stats.unique_items}</span>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-1 mb-3">
        {CATEGORIES.map((category) => (
          <button
            key={category}
            type="button"
            onClick={() => handleCategoryChange(category)}
            className={`px-2 py-1 text-xs rounded transition-colors ${
              selectedCategory === category
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600'
            }`}
          >
            {t(`inventoryCategory_${category}`)}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <p className="text-slate-400 dark:text-slate-500 text-sm">{t('inventoryEmpty')}</p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.id}>
              <button
                type="button"
                onClick={() => handleItemClick(item)}
                className="w-full text-left p-2 rounded border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${getRarityColor(item.rarity)}`}>
                      {item.rarity}
                    </span>
                    <span className="text-sm text-slate-900 dark:text-slate-100 truncate">
                      {item.name}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 dark:text-slate-400 flex-shrink-0">
                    x{item.quantity}
                  </span>
                </div>
              </button>

              {selectedItem?.id === item.id && (
                <div className="mt-1 p-2 bg-slate-50 dark:bg-slate-700/30 rounded border border-slate-200 dark:border-slate-700">
                  <p className="text-xs text-slate-600 dark:text-slate-300 mb-2">
                    {item.description}
                  </p>
                  {item.effects && Object.keys(item.effects).length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(item.effects).map(([effect, value]) => (
                        <span
                          key={effect}
                          className="px-1.5 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded text-xs"
                        >
                          {effect}: {value > 0 ? '+' : ''}{value}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
