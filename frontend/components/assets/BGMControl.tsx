'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { generateBGM } from '@/lib/api';
import { AssetFallback } from '@/components/assets/AssetFallback';
import type { AssetResponse } from '@/types/api';

interface BGMControlProps {
  locationId?: string;
  sessionId?: string;
  muted?: boolean;
}

export function BGMControl({ locationId, sessionId, muted = false }: BGMControlProps) {
  const t = useTranslations('Assets');
  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(!muted);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (muted) return;
    let cancelled = false;
    generateBGM({
      location_id: locationId,
      mood: 'calm',
      session_id: sessionId,
    })
      .then((result) => {
        if (!cancelled) setAsset(result);
      })
      .catch(() => {
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [locationId, sessionId, muted]);

  if (muted) {
    return (
      <div className="inline-flex items-center gap-2 text-xs text-slate-400">
        <span>🔇</span>
        <span>{t('bgmMuted')}</span>
      </div>
    );
  }

  if (isLoading) {
    return <AssetFallback variant="loading" message={t('generating')} />;
  }

  if (asset && asset.generation_status === 'completed') {
    return (
      <div className="inline-flex items-center gap-2 text-xs">
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          className="px-2 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          aria-label={isPlaying ? t('pause') : t('play')}
        >
          {isPlaying ? '⏸' : '▶️'}
        </button>
        <span className="text-slate-600 dark:text-slate-400">{t('bgmAvailable')}</span>
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-2 text-xs text-slate-400">
      <span>🎵</span>
      <span>{t('bgmUnavailable')}</span>
    </div>
  );
}
