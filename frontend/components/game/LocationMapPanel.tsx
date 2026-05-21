'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { getPlayerLocations } from '@/lib/api';
import type { PlayerLocation } from '@/types/api';

interface LocationMapPanelProps {
  sessionId: string;
  currentLocationId?: string;
}


function DangerBadge({ level, t }: { level: PlayerLocation['danger_level']; t: ReturnType<typeof useTranslations<'Game'>> }) {
  const config = {
    safe: {
      bg: 'bg-emerald-100 dark:bg-emerald-900/30',
      text: 'text-emerald-700 dark:text-emerald-300',
      dot: 'bg-emerald-500',
      label: t('dangerSafe'),
    },
    dangerous: {
      bg: 'bg-amber-100 dark:bg-amber-900/30',
      text: 'text-amber-700 dark:text-amber-300',
      dot: 'bg-amber-500',
      label: t('dangerDangerous'),
    },
    lethal: {
      bg: 'bg-red-100 dark:bg-red-900/30',
      text: 'text-red-700 dark:text-red-300',
      dot: 'bg-red-500',
      label: t('dangerLethal'),
    },
  };
  const { bg, text, dot, label } = config[level];
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${bg} ${text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}


function ConnectionGraph({ locations, currentLocationId }: {
  locations: PlayerLocation[];
  currentLocationId?: string;
}) {
  const t = useTranslations('Game');
  const locationMap = useMemo(
    () => new Map(locations.map(loc => [loc.location_id, loc])),
    [locations],
  );

  const renderedEdges = useMemo(() => {
    const seen = new Set<string>();
    const edges: Array<{ from: PlayerLocation; to: PlayerLocation }> = [];
    for (const loc of locations) {
      for (const connId of loc.connections) {
        const key = [loc.location_id, connId].sort().join('|');
        if (!seen.has(key) && locationMap.has(connId)) {
          seen.add(key);
          edges.push({ from: loc, to: locationMap.get(connId)! });
        }
      }
    }
    return edges;
  }, [locations, locationMap]);

  if (locations.length === 0) return null;

  const isCurrent = (loc: PlayerLocation) =>
    loc.is_current || loc.location_id === currentLocationId;

  return (
    <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700">
      <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">
        {t('connectionsTitle')}
      </h4>
      <div className="space-y-1 font-mono text-xs leading-relaxed">
        {locations.map(loc => {
          const connected = loc.connections
            .map(id => locationMap.get(id))
            .filter(Boolean) as PlayerLocation[];

          if (connected.length === 0) {
            return (
              <div key={loc.location_id} className="flex items-center gap-1.5">
                <span className={isCurrent(loc) ? 'text-indigo-600 dark:text-indigo-400 font-bold' : 'text-slate-600 dark:text-slate-300'}>
                  {isCurrent(loc) ? '◆' : '◇'} {loc.name}
                </span>
              </div>
            );
          }

          return (
            <div key={loc.location_id}>
              <div className="flex items-center gap-1.5">
                <span className={isCurrent(loc) ? 'text-indigo-600 dark:text-indigo-400 font-bold' : 'text-slate-600 dark:text-slate-300'}>
                  {isCurrent(loc) ? '◆' : '◇'} {loc.name}
                </span>
              </div>
              {connected.map((target, i) => (
                <div key={target.location_id} className="flex items-center gap-1.5 ml-3">
                  <span className="text-slate-400 dark:text-slate-500">
                    {i === connected.length - 1 ? '└' : '├'}
                  </span>
                  <span className="text-slate-400 dark:text-slate-500">──</span>
                  <span className={isCurrent(target) ? 'text-indigo-600 dark:text-indigo-400 font-bold' : 'text-slate-500 dark:text-slate-400'}>
                    {isCurrent(target) ? '◆' : '○'} {target.name}
                  </span>
                  {!target.accessible && (
                    <span className="text-slate-400 dark:text-slate-500" title={t('statusBlocked')}>🔒</span>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}


function LocationItem({
  location,
  isCurrent,
  isExpanded,
  onToggle,
  t,
}: {
  location: PlayerLocation;
  isCurrent: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  t: ReturnType<typeof useTranslations<'Game'>>;
}) {
  return (
    <div
      className={`rounded border transition-colors duration-200 ${
        isCurrent
          ? 'bg-indigo-50 dark:bg-indigo-950/30 border-indigo-300 dark:border-indigo-700'
          : location.accessible
            ? 'bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            : 'bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700 opacity-60'
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left px-3 py-2 flex items-center justify-between gap-2 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-indigo-500 dark:focus:ring-indigo-400 rounded"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2 min-w-0">
          {isCurrent ? (
            <span className="flex-shrink-0 w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          ) : (
            <span className={`flex-shrink-0 w-2 h-2 rounded-full ${location.accessible ? 'bg-slate-300 dark:bg-slate-600' : 'bg-slate-200 dark:bg-slate-700'}`} />
          )}
          <span className={`text-sm truncate ${
            isCurrent
              ? 'font-semibold text-indigo-700 dark:text-indigo-300'
              : location.accessible
                ? 'text-slate-700 dark:text-slate-200'
                : 'text-slate-400 dark:text-slate-500'
          }`}>
            {location.name}
          </span>
          {!location.accessible && (
            <span className="text-xs text-slate-400 dark:text-slate-500" title={t('statusBlocked')}>🔒</span>
          )}
        </div>
        <DangerBadge level={location.danger_level} t={t} />
      </button>

      {isExpanded && (
        <div className="px-3 pb-2 space-y-1.5">
          <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
            {location.description}
          </p>
          {location.connections.length > 0 && (
            <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
              <span>{t('connectionsLabel')}:</span>
              <span className="text-slate-600 dark:text-slate-300">
                {location.connections.length}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


export function LocationMapPanel({ sessionId, currentLocationId }: LocationMapPanelProps) {
  const t = useTranslations('Game');
  const [locations, setLocations] = useState<PlayerLocation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showGraph, setShowGraph] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loadLocations = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getPlayerLocations(sessionId);
        if (!cancelled) {
          setLocations(data);
          const current = data.find(
            loc => loc.is_current || loc.location_id === currentLocationId
          );
          if (current) setExpandedId(current.location_id);
        }
      } catch {
        if (!cancelled) setError(t('locationsLoadError'));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    loadLocations();
    return () => { cancelled = true; };
  }, [sessionId, currentLocationId, t]);

  const handleToggle = useCallback((locationId: string) => {
    setExpandedId(prev => prev === locationId ? null : locationId);
  }, []);

  const { currentLocation, otherLocations } = useMemo(() => {
    const current = locations.find(
      loc => loc.is_current || loc.location_id === currentLocationId
    );
    const others = locations.filter(
      loc => !loc.is_current && loc.location_id !== currentLocationId
    );
    return { currentLocation: current, otherLocations: others };
  }, [locations, currentLocationId]);

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('locationMap')}
        </h3>
        <div className="flex items-center gap-2 text-sm text-slate-400 dark:text-slate-500">
          <span className="flex gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 animate-bounce" style={{ animationDelay: '300ms' }} />
          </span>
          <span>{t('loading')}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-red-200 dark:border-red-900/50 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-2">
          {t('locationMap')}
        </h3>
        <p className="text-red-500 dark:text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (locations.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
          {t('locationMap')}
        </h3>
        <div className="flex flex-col items-center py-4 text-slate-400 dark:text-slate-500">
          <svg className="w-8 h-8 mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          <p className="text-sm">{t('noLocationsDiscovered')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
          {t('locationMap')}
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {t('locationsCount', { count: locations.length })}
          </span>
          <button
            type="button"
            onClick={() => setShowGraph(prev => !prev)}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              showGraph
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-600'
            }`}
            title={showGraph ? t('hideGraph') : t('showGraph')}
          >
            {showGraph ? t('hideGraph') : t('showGraph')}
          </button>
        </div>
      </div>

      <div className="p-3 space-y-2">
        {currentLocation && (
          <div className="mb-1">
            <div className="flex items-center gap-1.5 mb-1.5 px-1">
              <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400 uppercase tracking-wide">
                {t('currentLocation')}
              </span>
            </div>
            <LocationItem
              location={currentLocation}
              isCurrent={true}
              isExpanded={expandedId === currentLocation.location_id}
              onToggle={() => handleToggle(currentLocation.location_id)}
              t={t}
            />
          </div>
        )}

        {otherLocations.length > 0 && (
          <div>
            {currentLocation && (
              <div className="flex items-center gap-2 my-2 px-1">
                <div className="flex-1 h-px bg-slate-200 dark:bg-slate-700" />
                <span className="text-xs text-slate-400 dark:text-slate-500">{t('otherLocations')}</span>
                <div className="flex-1 h-px bg-slate-200 dark:bg-slate-700" />
              </div>
            )}
            <div className="space-y-1.5">
              {otherLocations.map(loc => (
                <LocationItem
                  key={loc.location_id}
                  location={loc}
                  isCurrent={false}
                  isExpanded={expandedId === loc.location_id}
                  onToggle={() => handleToggle(loc.location_id)}
                  t={t}
                />
              ))}
            </div>
          </div>
        )}

        {showGraph && (
          <ConnectionGraph
            locations={locations}
            currentLocationId={currentLocationId}
          />
        )}
      </div>
    </div>
  );
}
