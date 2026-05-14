'use client';

import React, { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';

interface DebugSessionSelectorProps {
  onLoad: (sessionId: string) => void;
  isLoading?: boolean;
  currentSessionId?: string;
}

export function DebugSessionSelector({
  onLoad,
  isLoading = false,
  currentSessionId,
}: DebugSessionSelectorProps) {
  const t = useTranslations('Debug');
  const [sessionId, setSessionId] = useState(currentSessionId ?? '');

  const handleLoad = () => {
    if (sessionId.trim()) {
      onLoad(sessionId.trim());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && sessionId.trim() && !isLoading) {
      handleLoad();
    }
  };

  return (
    <Card className="p-6 mb-6">
      <h2 className="text-xl font-semibold mb-4">{t('sessionInspector')}</h2>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Input
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('enterSessionId')}
          className="flex-1"
          disabled={isLoading}
        />
        <Button onClick={handleLoad} disabled={!sessionId.trim() || isLoading}>
          {t('load')}
        </Button>
      </div>
    </Card>
  );
}
