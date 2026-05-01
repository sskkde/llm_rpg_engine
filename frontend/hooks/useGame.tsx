'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import type { SessionSnapshot, TurnResponse } from '@/types/api';
import { getSessionSnapshot, executeTurn } from '@/lib/api';

interface TurnResult {
  turnIndex: number;
  narration: string;
  worldTime: {
    calendar?: string;
    season?: string;
    day?: number;
    period?: string;
  };
  playerState: {
    entityId?: string;
    name?: string;
    locationId?: string;
  };
}

interface GameContextType {
  sessionId: string | null;
  session: SessionSnapshot | null;
  isLoading: boolean;
  currentTurn: TurnResult | null;
  turnHistory: TurnResult[];
  loadSession: (sessionId: string) => Promise<void>;
  executeTurn: (action: string) => Promise<void>;
  refreshSession: () => Promise<void>;
}

const GameContext = createContext<GameContextType | undefined>(undefined);

export function GameProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [currentTurn, setCurrentTurn] = useState<TurnResult | null>(null);
  const [turnHistory, setTurnHistory] = useState<TurnResult[]>([]);

  const loadSession = useCallback(async (id: string) => {
    setIsLoading(true);
    try {
      const snapshot = await getSessionSnapshot(id);
      setSessionId(id);
      setSession(snapshot);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refreshSession = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    try {
      const snapshot = await getSessionSnapshot(sessionId);
      setSession(snapshot);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const executeGameTurn = useCallback(async (action: string) => {
    if (!sessionId) return;
    setIsLoading(true);
    try {
      const response: TurnResponse = await executeTurn(sessionId, { action });
      const turnResult: TurnResult = {
        turnIndex: response.turn_index,
        narration: response.narration,
        worldTime: response.world_time,
        playerState: {
          entityId: response.player_state.entity_id,
          name: response.player_state.name,
          locationId: response.player_state.location_id,
        },
      };
      setCurrentTurn(turnResult);
      setTurnHistory((prev) => [...prev, turnResult]);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  return (
    <GameContext.Provider
      value={{
        sessionId,
        session,
        isLoading,
        currentTurn,
        turnHistory,
        loadSession,
        executeTurn: executeGameTurn,
        refreshSession,
      }}
    >
      {children}
    </GameContext.Provider>
  );
}

export function useGame() {
  const context = useContext(GameContext);
  if (context === undefined) {
    throw new Error('useGame must be used within a GameProvider');
  }
  return context;
}
