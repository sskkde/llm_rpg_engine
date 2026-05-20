'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { generatePortrait, createPortraitJob } from '@/lib/api';
import { useAssetJob } from '@/hooks/useAssetJob';
import { AssetFallback } from '@/components/assets/AssetFallback';
import type { AssetResponse, AssetJobResponse } from '@/types/api';

interface NPCPortraitProps {
  npcId: string;
  sessionId?: string;
  mood?: string;
  artStyle?: string;
  debug?: boolean;
}

function getMoodEmoji(mood?: string): string {
  if (mood === 'happy') return '😊';
  if (mood === 'angry') return '😠';
  if (mood === 'sad') return '😢';
  return '🧑';
}

export function NPCPortrait({ npcId, sessionId, mood, artStyle, debug }: NPCPortraitProps) {
  const t = useTranslations('Assets');

  // Track the session identity for async job flow
  const sessionKey = useMemo(
    () => (npcId && sessionId) ? `${npcId}:${sessionId}:${artStyle ?? ''}` : null,
    [npcId, sessionId, artStyle],
  );

  const [internalJobId, setInternalJobId] = useState<string | null>(null);
  const [internalJobInitError, setInternalJobInitError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);

  // Derive effective values: null when no valid session
  const jobId = sessionKey ? internalJobId : null;
  const jobInitError = sessionKey ? internalJobInitError : null;

  // Adjust state when sessionKey changes (React-recommended pattern)
  // See: https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const prevSessionKeyRef = useRef(sessionKey);
  if (sessionKey !== prevSessionKeyRef.current) {
    prevSessionKeyRef.current = sessionKey;
    setInternalJobId(null);
    setInternalJobInitError(null);
    setImageError(false);
  }

  const [asset, setAsset] = useState<AssetResponse | null>(null);
  const [isLoading, setIsLoading] = useState(!!npcId && !sessionId);
  const [error, setError] = useState<string | null>(null);

  const { job, isLoading: isJobLoading, error: jobError, retry } = useAssetJob({ jobId });

  useEffect(() => {
    if (!sessionKey) return;

    let cancelled = false;

    async function initJob() {
      setInternalJobInitError(null);
      try {
        const result = await createPortraitJob({
          npc_id: npcId,
          style: artStyle || 'anime',
          session_id: sessionId!,
        });

        if (!cancelled && 'job_id' in result) {
          setImageError(false);
          setInternalJobId((result as AssetJobResponse).job_id);
        }
      } catch (err) {
        if (!cancelled) {
          setInternalJobInitError(err instanceof Error ? err.message : 'Failed to create job');
        }
      }
    }

    initJob();
    return () => { cancelled = true; };
  }, [sessionKey, npcId, sessionId, artStyle]);

  useEffect(() => {
    if (!npcId || sessionId) return;

    let cancelled = false;
    generatePortrait({
      npc_id: npcId,
      style: artStyle || 'anime',
    })
      .then((result) => { if (!cancelled) setAsset(result); })
      .catch(() => { if (!cancelled) setError('error'); })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [npcId, sessionId, artStyle]);

  const handleAsyncRetry = useCallback(async () => {
    setImageError(false);
    if (jobId) {
      await retry();
    } else if (npcId && sessionId) {
      setInternalJobInitError(null);
      try {
        const result = await createPortraitJob({
          npc_id: npcId,
          style: artStyle || 'anime',
          session_id: sessionId,
        });
        if ('job_id' in result) {
          setImageError(false);
          setInternalJobId((result as AssetJobResponse).job_id);
        }
      } catch (err) {
        setInternalJobInitError(err instanceof Error ? err.message : 'Failed to create job');
      }
    }
  }, [jobId, retry, npcId, sessionId, artStyle]);

  const handleSyncRetry = useCallback(() => {
    setAsset(null);
    setError(null);
    setIsLoading(true);
    generatePortrait({
      npc_id: npcId,
      style: artStyle || 'anime',
    })
      .then((result) => { setAsset(result); })
      .catch(() => { setError('error'); })
      .finally(() => { setIsLoading(false); });
  }, [npcId, artStyle]);

  if (sessionId) {
    if (!jobId && !jobInitError) {
      return <AssetFallback variant="loading" message={t('generating')} />;
    }

    if (jobInitError) {
      return <AssetFallback variant="error" message={jobInitError} onRetry={handleAsyncRetry} />;
    }

    if (isJobLoading || (job && (job.status === 'pending' || job.status === 'processing'))) {
      return <AssetFallback variant="loading" message={t('generating')} />;
    }

    if (jobError || (job && (job.status === 'failed' || job.status === 'dead_lettered'))) {
      return (
        <AssetFallback
          variant="error"
          message={job?.error_message || jobError || t('failed')}
          onRetry={handleAsyncRetry}
        />
      );
    }

    const resultUrl = job?.result_url;
    const showImage = resultUrl && !imageError;

    return (
      <div className="relative inline-flex items-center justify-center w-24 h-24 rounded-full bg-gradient-to-br from-blue-400 to-purple-500 overflow-hidden">
        {showImage ? (
          <img
            src={resultUrl}
            alt="NPC Portrait"
            className="w-full h-full object-cover"
            onError={() => setImageError(true)}
          />
        ) : (
          <span className="text-3xl text-white select-none">
            {getMoodEmoji(mood)}
          </span>
        )}
        {debug && job && (
          <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] text-slate-400 whitespace-nowrap">
            {job.status}
          </div>
        )}
      </div>
    );
  }

  if (isLoading) {
    return <AssetFallback variant="loading" message={t('generating')} />;
  }

  if (error || (asset && asset.generation_status === 'failed')) {
    return (
      <AssetFallback
        variant="error"
        message={asset?.error_message || (error ? t('failed') : undefined)}
        onRetry={handleSyncRetry}
      />
    );
  }

  return (
    <div className="relative inline-flex items-center justify-center w-16 h-16 rounded-full bg-gradient-to-br from-blue-400 to-purple-500">
      <span className="text-2xl text-white select-none">
        {getMoodEmoji(mood)}
      </span>
      {debug && asset && (
        <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 text-[8px] text-slate-400 whitespace-nowrap">
          {asset.cache_hit ? 'cached' : asset.generation_status}
        </div>
      )}
    </div>
  );
}
