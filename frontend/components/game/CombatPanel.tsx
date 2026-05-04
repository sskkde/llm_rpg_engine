'use client';

import React, {useCallback, useEffect, useState} from 'react';
import {useTranslations} from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { CombatParticipantCard } from './CombatParticipantCard';
import { CombatActionForm } from './CombatActionForm';
import { CombatEventFeed } from './CombatEventFeed';
import { getCombat, submitCombatAction, endCombat, getCombatEvents } from '@/lib/api';
import type { CombatSession, CombatActionRequest, CombatEvent } from '@/types/api';

interface CombatPanelProps {
  combatId: string;
  onCombatEnd: () => void;
}

export function CombatPanel({ combatId, onCombatEnd }: CombatPanelProps) {
  const t = useTranslations('Combat');
  const [combat, setCombat] = useState<CombatSession | null>(null);
  const [events, setEvents] = useState<CombatEvent[]>([]);
  const [selectedTarget, setSelectedTarget] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshCombat = useCallback(async () => {
    try {
      const [combatData, eventsData] = await Promise.all([
        getCombat(combatId),
        getCombatEvents(combatId),
      ]);
      setCombat(combatData);
      setEvents(eventsData.events || []);
    } catch {
      setError(t('failedToLoad'));
    }
  }, [combatId, t]);

  useEffect(() => {
    const loadCombat = async () => {
      setIsLoading(true);
      await refreshCombat();
      setIsLoading(false);
    };
    loadCombat();
  }, [refreshCombat]);

  const handleAction = async (action: CombatActionRequest) => {
    setIsSubmitting(true);
    setError(null);
    try {
      await submitCombatAction(combatId, { ...action, target_id: selectedTarget || undefined });
      await refreshCombat();
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || t('actionFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEndCombat = async () => {
    try {
      await endCombat(combatId);
      onCombatEnd();
    } catch {
      setError(t('failedToEnd'));
    }
  };

  if (isLoading) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (!combat) {
    return <ErrorMessage message={t('notFound')} variant="card" />;
  }

  const isActive = combat.status === 'active';
  const player = combat.participants.find((p) => p.is_player);
  const enemies = combat.participants.filter((p) => !p.is_player);

  return (
    <Card className="p-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-4">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          {t('title')}
        </h2>
        <Badge variant={isActive ? 'warning' : 'success'} className="self-start sm:self-auto">
          {combat.status}
        </Badge>
      </div>

      {error && <ErrorMessage message={error} variant="card" onDismiss={() => setError(null)} />}

      <div className="mb-4">
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-2">
          {t('round', {roundNumber: combat.current_round})}
        </p>
      </div>

      {player && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">{t('you')}</h3>
          <CombatParticipantCard
            participant={player}
            isSelected={false}
            onSelect={() => {}}
            isPlayer={true}
          />
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">{t('enemies')}</h3>
        <div className="space-y-2">
          {enemies.map((enemy) => (
            <CombatParticipantCard
              key={enemy.entity_id}
              participant={enemy}
              isSelected={selectedTarget === enemy.entity_id}
              onSelect={setSelectedTarget}
              isPlayer={false}
            />
          ))}
        </div>
      </div>

      {isActive && (
        <CombatActionForm
          onSubmit={handleAction}
          isDisabled={isSubmitting}
          hasTarget={!!selectedTarget}
        />
      )}

      {!isActive && (
        <Button onClick={handleEndCombat} className="w-full">
          {t('returnToGame')}
        </Button>
      )}

      <div className="mt-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">{t('events')}</h3>
        <CombatEventFeed events={events} />
      </div>
    </Card>
  );
}
