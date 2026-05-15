'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { generateSceneAsset } from '@/lib/api';
import { AssetFallback } from '@/components/assets/AssetFallback';
import { AssetResponse, AssetGenerationStatus } from '@/types/api';

interface SceneBackgroundProps {
  locationId: string;
  sessionId?: string;
  weather?: string;
  timeOfDay?: string;
}

export function SceneBackground({ locationId, sessionId, weather, timeOfDay }: SceneBackgroundProps) {
  const t = useTranslations('Assets');
  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!locationId) return;

    let cancelled = false;

    async function fetchScene() {
      setIsLoading(true);
      setError(null);
      setAsset(null);
      try {
        const result = await generateSceneAsset({
          location_id: locationId,
          session_id: sessionId,
          time_of_day: timeOfDay || 'day',
          weather,
        });
        if (!cancelled) {
          setAsset(result);
        }
      } catch {
        if (!cancelled) {
          setError('error');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    fetchScene();

    return () => {
      cancelled = true;
    };
  }, [locationId, sessionId, weather, timeOfDay]);

  const gradientClass = timeOfDay === 'night'
    ? 'from-indigo-900 via-blue-900 to-slate-900'
    : weather === 'rainy'
    ? 'from-slate-400 via-slate-500 to-slate-600'
    : weather === 'snowy'
    ? 'from-blue-100 via-slate-200 to-white'
    : 'from-blue-300 via-blue-200 to-sky-100';

  const showLoading = isLoading;
  const showAsset = asset && asset.generation_status === AssetGenerationStatus.COMPLETED && asset.result_url;
  const showError = error || (asset && asset.generation_status === AssetGenerationStatus.FAILED);

  return (
    <div
      className={`w-full h-32 rounded-lg bg-gradient-to-br ${gradientClass} flex items-center justify-center`}
      data-location-id={locationId}
      data-session-id={sessionId}
    >
      {showLoading && <AssetFallback variant="loading" />}
      {showError && <span className="text-white/60 text-sm">{t('scenePlaceholder')}</span>}
      {showAsset && <span className="text-white/60 text-sm">{t('scenePlaceholder')}</span>}
      {!showLoading && !showError && !showAsset && <span className="text-white/60 text-sm">{t('scenePlaceholder')}</span>}
    </div>
  );
}
