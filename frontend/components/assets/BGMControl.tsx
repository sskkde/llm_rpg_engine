'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { generateBGM } from '@/lib/api';
import { AssetFallback } from '@/components/assets/AssetFallback';
import type { AssetResponse } from '@/types/api';

const BGM_MUTED_KEY = 'llm_rpg_bgm_muted';

interface BGMControlProps {
  locationId?: string;
  sessionId?: string;
  muted?: boolean;
}

export function BGMControl({ locationId, sessionId, muted: mutedProp = false }: BGMControlProps) {
  const t = useTranslations('Assets');
  const [isMuted, setIsMuted] = useState(() => {
    if (mutedProp) return true;
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(BGM_MUTED_KEY) === 'true';
  });
  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(!isMuted && !mutedProp);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    localStorage.setItem(BGM_MUTED_KEY, String(isMuted));
  }, [isMuted]);

  useEffect(() => {
    if (isMuted || mutedProp) return;
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
  }, [locationId, sessionId, isMuted, mutedProp]);

  const toggleMute = () => setIsMuted(!isMuted);

  if (isMuted || mutedProp) {
    return (
      <div className="inline-flex items-center gap-2 text-xs text-slate-400">
        <span>🔇</span>
        <span>{t('bgmMuted')}</span>
        <button
          onClick={toggleMute}
          className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          aria-label={t('play')}
        >
          🔊
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="inline-flex items-center gap-2">
        <AssetFallback variant="loading" message={t('generating')} />
        <button
          onClick={toggleMute}
          className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          aria-label={t('bgmMuted')}
        >
          🔇
        </button>
      </div>
    );
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
        <button
          onClick={toggleMute}
          className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          aria-label={t('bgmMuted')}
        >
          🔇
        </button>
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-2 text-xs text-slate-400">
      <span>🎵</span>
      <span>{t('bgmUnavailable')}</span>
      <button
        onClick={toggleMute}
        className="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
        aria-label={t('bgmMuted')}
      >
        🔇
      </button>
    </div>
  );
}
