'use client';

import React from 'react';
import {useFormatter, useTranslations} from 'next-intl';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Loading } from '@/components/ui/Loading';
import type { SessionSummary } from '@/types/api';

interface SessionListProps {
  sessions: SessionSummary[];
  isLoading: boolean;
  onLoadSession: (sessionId: string) => void;
}

export function SessionList({ sessions, isLoading, onLoadSession }: SessionListProps) {
  const t = useTranslations('Session');
  const format = useFormatter();

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loading size="md" text={t('loading')} />
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-slate-600 dark:text-slate-400">
          {t('noSessions')}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {sessions.map((session) => {
        const lastPlayed = format.dateTime(new Date(session.last_played_at), {
          dateStyle: 'medium',
          timeStyle: 'short',
        });
        const statusLabel = session.status === 'active'
          ? t('active')
          : session.status === 'inactive'
            ? t('inactive')
            : session.status;

        return (
          <div
            key={session.id}
            className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800 rounded-lg"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  {t('sessionId', {id: session.id.slice(0, 8)})}
                </span>
                <Badge
                  variant={session.status === 'active' ? 'success' : 'default'}
                  size="sm"
                >
                  {statusLabel}
                </Badge>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t('lastPlayed', {date: lastPlayed})}
              </p>
            </div>
            <Button
              size="sm"
              onClick={() => onLoadSession(session.id)}
            >
              {t('continue')}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
