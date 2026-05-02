'use client';

import { useState, useCallback, useRef } from 'react';
import { createTurnStream, executeTurn } from '@/lib/api';
import type { TurnResponse, SSEEventData } from '@/types/api';

interface TurnState {
  isStreaming: boolean;
  isPending: boolean;
  narration: string;
  error: string | null;
  usedFallback: boolean;
}

export function useTurnStream(sessionId: string | null) {
  const [state, setState] = useState<TurnState>({
    isStreaming: false,
    isPending: false,
    narration: '',
    error: null,
    usedFallback: false,
  });
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const fallbackTurn = useCallback(async (action: string): Promise<TurnResponse | null> => {
    if (!sessionId) return null;

    setState((prev) => ({
      ...prev,
      isPending: true,
      usedFallback: true,
    }));

    try {
      const response = await executeTurn(sessionId, { action });
      setState({
        isStreaming: false,
        isPending: false,
        narration: response.narration,
        error: null,
        usedFallback: true,
      });
      return response;
    } catch (err: unknown) {
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
    setState({
      isStreaming: true,
      isPending: true,
      narration: '',
      error: null,
      usedFallback: false,
    });

    try {
      const eventSource = createTurnStream(sessionId, action);
      eventSourceRef.current = eventSource;

      let accumulatedNarration = '';
      let turnResponse: TurnResponse | null = null;

      return new Promise<TurnResponse | null>((resolve) => {
        eventSource.onmessage = (event) => {
          try {
            const data: SSEEventData = JSON.parse(event.data);

            switch (data.event) {
              case 'narration_delta':
                accumulatedNarration += data.delta;
                setState((prev) => ({
                  ...prev,
                  narration: accumulatedNarration,
                }));
                break;

              case 'turn_completed':
                turnResponse = {
                  turn_index: data.turn_index,
                  narration: data.narration || accumulatedNarration,
                  world_time: data.world_time,
                  player_state: data.player_state,
                  events_committed: 0,
                  actions_committed: 0,
                  validation_passed: true,
                  transaction_id: '',
                };
                cleanup();
                setState({
                  isStreaming: false,
                  isPending: false,
                  narration: turnResponse.narration,
                  error: null,
                  usedFallback: false,
                });
                resolve(turnResponse);
                break;

              case 'turn_error':
                cleanup();
                setState((prev) => ({
                  ...prev,
                  isStreaming: false,
                  error: data.message || 'Turn failed',
                }));
                resolve(null);
                break;
            }
          } catch {
          }
        };

        eventSource.onerror = () => {
          cleanup();
          setState((prev) => ({
            ...prev,
            isStreaming: false,
            usedFallback: true,
          }));
          fallbackTurn(action).then(resolve);
        };
      });
    } catch {
      return fallbackTurn(action);
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
