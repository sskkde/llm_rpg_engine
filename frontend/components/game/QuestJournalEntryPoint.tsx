'use client';

import { useEffect, useState } from 'react';
import { QuestJournalPanel } from './QuestJournalPanel';
import { getPlayerQuests } from '@/lib/api';

interface Props {
  sessionId: string;
  children?: React.ReactNode;
}

export function QuestJournalEntryPoint({ sessionId, children }: Props) {
  const [hasVisibleQuests, setHasVisibleQuests] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;

    getPlayerQuests(sessionId)
      .then((quests) => {
        if (mounted) setHasVisibleQuests(quests.length > 0);
      })
      .catch(() => {
        if (mounted) setHasVisibleQuests(false);
      });

    return () => {
      mounted = false;
    };
  }, [sessionId]);

  if (hasVisibleQuests !== true) {
    return null;
  }

  return children ? <>{children}</> : <QuestJournalPanel sessionId={sessionId} />;
}
