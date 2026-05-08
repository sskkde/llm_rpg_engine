'use client';

import { useState, useCallback, useRef } from 'react';
import { createTurnStream, executeTurn } from '@/lib/api';
import type { TurnResponse } from '@/types/api';

interface TurnState {
  isStreaming: boolean;
  isPending: boolean;
  narration: string;
  error: string | null;
  usedFallback: boolean;
}

function generateIdempotencyKey(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function useTurnStream(sessionId: string | null) {
  const [state, setState] = useState<TurnState>({
    isStreaming: false,
    isPending: false,
    narration: '',
    error: null,
    usedFallback: false,
  });
  const streamRef = useRef<{ abort(): void } | null>(null);
  const pendingKeyRef = useRef<string | null>(null);

  const cleanup = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.abort();
      streamRef.current = null;
    }
  }, []);

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
      setState({
        isStreaming: false,
        isPending: false,
        narration: response.narration,
        error: null,
        usedFallback: true,
      });
      return response;
    } catch (err: unknown) {
      if (pendingKeyRef.current !== idempotencyKey) return null;
      const detail = (err as { detail?: string })?.detail;
      const errorMessage = detail || 'Failed to execute turn';
      setState({
        isStreaming: false,
        isPending: false,
        narration: '',
        error: errorMessage,
        usedFallback: true,
      });
      return null;
    }
  }, [sessionId]);

  const submitTurn = useCallback(async (action: string): Promise<TurnResponse | null> => {
    if (!sessionId) return null;

    cleanup();
    const idempotencyKey = generateIdempotencyKey();
    pendingKeyRef.current = idempotencyKey;
    setState({
      isStreaming: true,
      isPending: true,
      narration: '',
      error: null,
      usedFallback: false,
    });

    try {
      const handle = createTurnStream(sessionId, action, false, idempotencyKey);
      streamRef.current = handle;

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
                narration: turnResponse.narration,
                error: null,
                usedFallback: false,
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
                error: event.message || 'Turn failed',
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
        usedFallback: true,
      }));
      return fallbackTurn(action, idempotencyKey);
    } catch {
      if (pendingKeyRef.current !== idempotencyKey) return null;
      cleanup();
      return fallbackTurn(action, idempotencyKey);
    }
  }, [sessionId, cleanup, fallbackTurn]);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  return {
    ...state,
    submitTurn,
    clearError,
  };
}
