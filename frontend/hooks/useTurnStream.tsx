'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { createTurnStream, executeTurn } from '@/lib/api';
import type { TurnResponse } from '@/types/api';

interface TurnState {
  isStreaming: boolean;
  isPending: boolean;
  isComplete: boolean;
  narration: string;
  error: string | null;
  usedFallback: boolean;
  streamingDuration: number;
}

function generateIdempotencyKey(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function useTurnStream(sessionId: string | null) {
  const [state, setState] = useState<TurnState>({
    isStreaming: false,
    isPending: false,
    isComplete: false,
    narration: '',
    error: null,
    usedFallback: false,
    streamingDuration: 0,
  });
  const streamRef = useRef<{ abort(): void } | null>(null);
  const pendingKeyRef = useRef<string | null>(null);
  const streamStartRef = useRef<number | null>(null);
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearDurationTimer = useCallback(() => {
    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }
  }, []);

  const startDurationTimer = useCallback(() => {
    clearDurationTimer();
    streamStartRef.current = Date.now();
    durationTimerRef.current = setInterval(() => {
      if (streamStartRef.current) {
        const elapsed = Math.round((Date.now() - streamStartRef.current) / 1000);
        setState((prev) => ({ ...prev, streamingDuration: elapsed }));
      }
    }, 1000);
  }, [clearDurationTimer]);

  const cleanup = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.abort();
      streamRef.current = null;
    }
    clearDurationTimer();
    streamStartRef.current = null;
  }, [clearDurationTimer]);

  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.abort();
      }
      clearDurationTimer();
    };
  }, [clearDurationTimer]);

  const fallbackTurn = useCallback(async (action: string, idempotencyKey: string): Promise<TurnResponse | null> => {
    if (!sessionId) return null;

    setState((prev) => ({
      ...prev,
      isPending: true,
      usedFallback: true,
    }));

    try {
      const response = await executeTurn(sessionId, { action, idempotency_key: idempotencyKey });
      if (pendingKeyRef.current !== idempotencyKey) return null;
      cleanup();
      setState({
        isStreaming: false,
        isPending: false,
        isComplete: true,
        narration: response.narration,
        error: null,
        usedFallback: true,
        streamingDuration: 0,
      });
      return response;
    } catch (err: unknown) {
      if (pendingKeyRef.current !== idempotencyKey) return null;
      cleanup();
      const detail = (err as { detail?: string })?.detail;
      const errorMessage = detail || 'Failed to execute turn';
      setState({
        isStreaming: false,
        isPending: false,
        isComplete: false,
        narration: '',
        error: errorMessage,
        usedFallback: true,
        streamingDuration: 0,
      });
      return null;
    }
  }, [sessionId, cleanup]);

  const submitTurn = useCallback(async (action: string): Promise<TurnResponse | null> => {
    if (!sessionId) return null;

    cleanup();
    const idempotencyKey = generateIdempotencyKey();
    pendingKeyRef.current = idempotencyKey;
    setState({
      isStreaming: true,
      isPending: true,
      isComplete: false,
      narration: '',
      error: null,
      usedFallback: false,
      streamingDuration: 0,
    });

    try {
      const handle = createTurnStream(sessionId, action, false, idempotencyKey);
      streamRef.current = handle;
      startDurationTimer();

      let accumulatedNarration = '';

      try {
        for await (const event of handle.events) {
          if (pendingKeyRef.current !== idempotencyKey) return null;
          switch (event.event) {
            case 'narration_delta':
              accumulatedNarration += event.delta;
              setState((prev) => ({
                ...prev,
                narration: accumulatedNarration,
              }));
              break;

            case 'turn_completed': {
              const turnResponse: TurnResponse = {
                turn_index: event.turn_index,
                narration: event.narration || accumulatedNarration,
                recommended_actions: event.recommended_actions ?? [],
                world_time: event.world_time,
                player_state: event.player_state,
                events_committed: 0,
                actions_committed: 0,
                validation_passed: true,
                transaction_id: '',
              };
              if (pendingKeyRef.current !== idempotencyKey) return null;
              cleanup();
              setState({
                isStreaming: false,
                isPending: false,
                isComplete: true,
                narration: turnResponse.narration,
                error: null,
                usedFallback: false,
                streamingDuration: 0,
              });
              return turnResponse;
            }

            case 'turn_error':
              if (pendingKeyRef.current !== idempotencyKey) return null;
              cleanup();
              setState((prev) => ({
                ...prev,
                isStreaming: false,
                isPending: false,
                isComplete: false,
                error: event.message || 'Turn failed',
                streamingDuration: 0,
              }));
              return null;
          }
        }
      } catch (err) {
        console.warn('Turn stream failed, falling back to non-streaming turn', err);
      }

      if (pendingKeyRef.current !== idempotencyKey) return null;
      cleanup();
      setState((prev) => ({
        ...prev,
        isStreaming: false,
        isComplete: false,
        usedFallback: true,
        streamingDuration: 0,
      }));
      return fallbackTurn(action, idempotencyKey);
    } catch {
      if (pendingKeyRef.current !== idempotencyKey) return null;
      cleanup();
      return fallbackTurn(action, idempotencyKey);
    }
  }, [sessionId, cleanup, fallbackTurn, startDurationTimer]);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    ...state,
    submitTurn,
    clearError,
  };
}
