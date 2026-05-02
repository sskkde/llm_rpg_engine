'use client';

import React, {use, useCallback, useEffect, useState} from 'react';
import {useFormatter, useTranslations} from 'next-intl';
import {useRouter} from '@/i18n/navigation';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { SessionList } from '@/components/saves/SessionList';
import {getSaveSlot, getWorldState, loadSession, manualSave} from '@/lib/api';
import type { SaveSlotDetail } from '@/types/api';

export default function SaveDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <ProtectedRoute>
      <SaveDetailContent saveId={id} />
    </ProtectedRoute>
  );
}

function SaveDetailContent({ saveId }: { saveId: string }) {
  const router = useRouter();
  const t = useTranslations('Saves');
  const format = useFormatter();
  const [save, setSave] = useState<SaveSlotDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isStartingGame, setIsStartingGame] = useState(false);

  const fetchSave = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getSaveSlot(saveId);
      setSave(data);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 404) {
        setError(t('saveNotFound'));
      } else if (status === 403) {
        setError(t('noPermission'));
      } else {
        setError(t('failedToLoadDetails'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [saveId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchSave();
  }, [fetchSave]);

  const handleLoadSession = async (sessionId: string) => {
    try {
      await loadSession(sessionId);
      router.push(`/game/${sessionId}`);
    } catch {
      setError(t('failedToLoadSession'));
    }
  };

  const handleStartNewGame = async () => {
    if (!save) return;

    setIsStartingGame(true);
    setError(null);

    try {
      const worldState = await getWorldState();
      const result = await manualSave({
        world_id: worldState.world.id,
        save_slot_id: save.id,
        current_chapter_id: worldState.chapters[0]?.id,
      });
      await loadSession(result.session_id);
      router.push(`/game/${result.session_id}`);
    } catch {
      setError(t('failedToStartGame'));
    } finally {
      setIsStartingGame(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loading size="lg" text={t('loadingDetails')} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <ErrorMessage message={error} variant="card" onRetry={fetchSave} />
        <div className="mt-4">
          <Button variant="ghost" onClick={() => router.push('/saves')}>
            {t('backToSaves')}
          </Button>
        </div>
      </div>
    );
  }

  if (!save) return null;

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="mb-6">
        <Button variant="ghost" onClick={() => router.push('/saves')}>
          &larr; {t('backToSaves')}
        </Button>
      </div>

      <Card className="p-6 mb-8">
        <div className="flex items-center gap-3 mb-4">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
            {save.name || t('saveSlot', {slotNumber: save.slot_number})}
          </h1>
          <Badge variant="info">{t('slotNumber', {slotNumber: save.slot_number})}</Badge>
        </div>
        <p className="text-slate-600 dark:text-slate-400">
          {t('created', {date: format.dateTime(new Date(save.created_at), {dateStyle: 'medium', timeStyle: 'short'})})}
        </p>
      </Card>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
        <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
          {t('sessions')}
        </h2>
        <Button onClick={handleStartNewGame} isLoading={isStartingGame} disabled={isStartingGame}>
          {isStartingGame ? t('startingGame') : t('startNewGame')}
        </Button>
      </div>
      <SessionList
        sessions={save.sessions || []}
        isLoading={false}
        onLoadSession={handleLoadSession}
      />
    </div>
  );
}
