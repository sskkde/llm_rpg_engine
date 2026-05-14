'use client';

import { useTranslations } from 'next-intl';

interface SceneBackgroundProps {
  locationId: string;
  sessionId?: string;
  weather?: string;
  timeOfDay?: string;
}

export function SceneBackground({ locationId, sessionId, weather, timeOfDay }: SceneBackgroundProps) {
  const t = useTranslations('Assets');

  const gradientClass = timeOfDay === 'night'
    ? 'from-indigo-900 via-blue-900 to-slate-900'
    : weather === 'rainy'
    ? 'from-slate-400 via-slate-500 to-slate-600'
    : weather === 'snowy'
    ? 'from-blue-100 via-slate-200 to-white'
    : 'from-blue-300 via-blue-200 to-sky-100';

  return (
    <div
      className={`w-full h-32 rounded-lg bg-gradient-to-br ${gradientClass} flex items-center justify-center`}
      data-location-id={locationId}
      data-session-id={sessionId}
    >
      <span className="text-white/60 text-sm">{t('scenePlaceholder')}</span>
    </div>
  );
}
