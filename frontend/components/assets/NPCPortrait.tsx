'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { generatePortrait } from '@/lib/api';
import { AssetFallback } from '@/components/assets/AssetFallback';
import type { AssetResponse } from '@/types/api';

interface NPCPortraitProps {
  npcId: string;
  sessionId?: string;
  mood?: string;
  artStyle?: string;
  debug?: boolean;
}

export function NPCPortrait({ npcId, sessionId, mood, artStyle, debug }: NPCPortraitProps) {
  const t = useTranslations('Assets');
  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(!!npcId);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!npcId) return;
    let cancelled = false;
    generatePortrait({
      npc_id: npcId,
      style: artStyle || 'anime',
      session_id: sessionId,
    })
      .then((result) => {
        if (!cancelled) setAsset(result);
      })
      .catch(() => {
        if (!cancelled) setError('error');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [npcId, sessionId, artStyle]);

  if (isLoading) {
    return <AssetFallback variant="loading" message={t('generating')} />;
  }

  if (error || (asset && asset.generation_status === 'failed')) {
    return (
      <AssetFallback
        variant="error"
        message={asset?.error_message || (error ? t('failed') : undefined)}
        onRetry={() => {
          setAsset(null);
          setError(null);
          setIsLoading(true);
          generatePortrait({
            npc_id: npcId,
            style: artStyle || 'anime',
            session_id: sessionId,
          })
            .then((result) => {
              setAsset(result);
            })
            .catch(() => {
              setError('error');
            })
            .finally(() => {
              setIsLoading(false);
            });
        }}
      />
    );
  }

  return (
    <div className="relative inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-blue-400 to-purple-500">
      <span className="text-2xl text-white select-none">
        {mood === 'happy' ? '😊' : mood === 'angry' ? '😠' : mood === 'sad' ? '😢' : '🧑'}
      </span>
      {debug && asset && (
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] text-slate-400 whitespace-nowrap">
          {asset.cache_hit ? 'cached' : asset.generation_status}
        </div>
      )}
    </div>
  );
}
