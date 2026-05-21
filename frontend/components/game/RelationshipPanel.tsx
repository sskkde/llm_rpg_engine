'use client';

import React, { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Loading } from '@/components/ui/Loading';
import {
  getPlayerRelationships,
  getPlayerRelationshipsSummary,
} from '@/lib/api';
import type { PlayerRelationship, RelationshipSummary } from '@/types/api';

interface RelationshipPanelProps {
  sessionId: string;
}

type SortMode = 'trust' | 'respect' | 'fear';

function getScoreColor(score: number): string {
  if (score >= 70) return 'bg-emerald-500';
  if (score >= 40) return 'bg-amber-500';
  return 'bg-rose-500';
}

function getScoreTextColor(score: number): string {
  if (score >= 70) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= 40) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

function getScoreBgLight(score: number): string {
  if (score >= 70) return 'bg-emerald-50 dark:bg-emerald-900/20';
  if (score >= 40) return 'bg-amber-50 dark:bg-amber-900/20';
  return 'bg-rose-50 dark:bg-rose-900/20';
}

export function RelationshipPanel({ sessionId }: RelationshipPanelProps) {
  const t = useTranslations('Game');

  const [relationships, setRelationships] = useState<PlayerRelationship[]>([]);
  const [summary, setSummary] = useState<RelationshipSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>('trust');
  const [expandedNpcId, setExpandedNpcId] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const fetchData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const [relsData, summaryData] = await Promise.all([
          getPlayerRelationships(sessionId, sortMode),
          getPlayerRelationshipsSummary(sessionId),
        ]);
        if (mounted) {
          setRelationships(relsData);
          setSummary(summaryData);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load relationships');
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      mounted = false;
    };
  }, [sessionId, sortMode]);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [relsData, summaryData] = await Promise.all([
        getPlayerRelationships(sessionId, sortMode),
        getPlayerRelationshipsSummary(sessionId),
      ]);
      setRelationships(relsData);
      setSummary(summaryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load relationships');
    } finally {
      setIsLoading(false);
    }
  };

  const toggleExpand = (npcId: string) => {
    setExpandedNpcId(expandedNpcId === npcId ? null : npcId);
  };

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('relationships')}
        </h3>
        <Loading size="sm" text={t('loading')} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('relationships')}
        </h3>
        <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
        <button
          onClick={fetchData}
          className="mt-2 text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
        >
          {t('retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('relationships')}
      </h3>

      {relationships.length === 0 ? (
        <p className="text-slate-400 dark:text-slate-500 text-sm italic">
          {t('noRelationships')}
        </p>
      ) : (
        <>
          {summary && (
            <div className="mb-4 p-3 bg-slate-50 dark:bg-slate-700/50 rounded-lg space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-slate-500 dark:text-slate-400">{t('totalNpcs')}</span>
                <span className="font-medium text-slate-700 dark:text-slate-300">{summary.total_npcs}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-500 dark:text-slate-400">{t('avgTrust')}</span>
                <span className={`font-medium ${getScoreTextColor(summary.average_trust)}`}>
                  {summary.average_trust.toFixed(1)}
                </span>
              </div>
              {summary.highest_trust && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500 dark:text-slate-400">{t('highestTrust')}</span>
                  <span className="font-medium text-emerald-600 dark:text-emerald-400">
                    {summary.highest_trust.npc_name} ({summary.highest_trust.trust_score})
                  </span>
                </div>
              )}
              {summary.lowest_trust && (
                <div className="flex justify-between text-xs">
                  <span className="text-slate-500 dark:text-slate-400">{t('lowestTrust')}</span>
                  <span className="font-medium text-rose-600 dark:text-rose-400">
                    {summary.lowest_trust.npc_name} ({summary.lowest_trust.trust_score})
                  </span>
                </div>
              )}
            </div>
          )}

          <div className="flex gap-1 mb-3">
            {(['trust', 'respect', 'fear'] as SortMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => setSortMode(mode)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  sortMode === mode
                    ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600'
                }`}
              >
                {t(`sortBy${mode.charAt(0).toUpperCase() + mode.slice(1)}`)}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            {relationships.map((rel) => (
              <div key={rel.npc_id}>
                <button
                  onClick={() => toggleExpand(rel.npc_id)}
                  className={`w-full text-left p-2 rounded-lg transition-colors hover:bg-slate-50 dark:hover:bg-slate-700/50 ${getScoreBgLight(rel.trust_score)}`}
                >
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      {rel.npc_name}
                    </span>
                    <span className={`text-xs font-medium ${getScoreTextColor(rel.trust_score)}`}>
                      {rel.trust_score}
                    </span>
                  </div>
                  <div className="w-full bg-slate-200 dark:bg-slate-600 rounded-full h-1.5">
                    <div
                      className={`h-1.5 rounded-full transition-all ${getScoreColor(rel.trust_score)}`}
                      style={{ width: `${Math.min(100, Math.max(0, rel.trust_score))}%` }}
                    />
                  </div>
                </button>

                {expandedNpcId === rel.npc_id && (
                  <div className="mt-1 p-2 bg-slate-50 dark:bg-slate-700/30 rounded-lg text-xs space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 dark:text-slate-400">{t('trustScore')}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-16 bg-slate-200 dark:bg-slate-600 rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${getScoreColor(rel.trust_score)}`}
                            style={{ width: `${Math.min(100, Math.max(0, rel.trust_score))}%` }}
                          />
                        </div>
                        <span className={`font-medium ${getScoreTextColor(rel.trust_score)}`}>
                          {rel.trust_score}
                        </span>
                      </div>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 dark:text-slate-400">{t('respectScore')}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-16 bg-slate-200 dark:bg-slate-600 rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${getScoreColor(rel.respect_score)}`}
                            style={{ width: `${Math.min(100, Math.max(0, rel.respect_score))}%` }}
                          />
                        </div>
                        <span className={`font-medium ${getScoreTextColor(rel.respect_score)}`}>
                          {rel.respect_score}
                        </span>
                      </div>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 dark:text-slate-400">{t('fearScore')}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-16 bg-slate-200 dark:bg-slate-600 rounded-full h-1.5">
                          <div
                            className={`h-1.5 rounded-full ${getScoreColor(rel.fear_score)}`}
                            style={{ width: `${Math.min(100, Math.max(0, rel.fear_score))}%` }}
                          />
                        </div>
                        <span className={`font-medium ${getScoreTextColor(rel.fear_score)}`}>
                          {rel.fear_score}
                        </span>
                      </div>
                    </div>
                    {rel.last_interaction_turn !== undefined && (
                      <div className="flex justify-between pt-1 border-t border-slate-200 dark:border-slate-600">
                        <span className="text-slate-500 dark:text-slate-400">{t('lastInteraction')}</span>
                        <span className="text-slate-600 dark:text-slate-400">
                          {t('turn', { turnIndex: rel.last_interaction_turn })}
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
