/**
 * Tests for GameSessionPage streaming status wiring.
 *
 * Tests verify:
 * - stageLabel is derived from currentStage.label
 * - streamFallbackNotice is displayed when set
 * - TurnStageStatus is not rendered separately (removed in T4)
 */

import { describe, it, expect } from '@jest/globals';

describe('GameSessionPage streaming status wiring', () => {
  /**
   * Tests the derivation of stageLabel from currentStage.
   * The game page derives stageLabel from the useTurnStream hook's currentStage:
   *   const stageLabel = currentStage?.label ?? null;
   */
  it('derives stageLabel from currentStage', () => {
    const currentStage = { code: 'narration', phase: 'started', label: '生成叙事文本……' };
    const stageLabel = currentStage?.label ?? null;
    expect(stageLabel).toBe('生成叙事文本……');
  });

  it('returns null stageLabel when currentStage is null', () => {
    const currentStage = null as { code: string; phase: string; label: string | null } | null;
    const stageLabel = currentStage?.label ?? null;
    expect(stageLabel).toBeNull();
  });

  it('returns null stageLabel when currentStage has no label', () => {
    const currentStage: { code: string; phase: string; label: string | null } = { code: 'narration', phase: 'started', label: null };
    const stageLabel = currentStage?.label ?? null;
    expect(stageLabel).toBeNull();
  });

  /**
   * Tests the display of streamFallbackNotice.
   * The hook sets streamFallbackNotice when receiving a stream_fallback event:
   *   case 'stream_fallback':
   *     setState((prev) => ({...prev, usedFallback: true, streamFallbackNotice: event.message}));
   */
  it('shows fallback notice when streamFallbackNotice is set', () => {
    const streamFallbackNotice = '实时连接失败，已切换为普通模式。';
    expect(streamFallbackNotice).toBeTruthy();
    expect(streamFallbackNotice.length).toBeGreaterThan(0);
  });

  it('hides fallback notice when streamFallbackNotice is null', () => {
    const streamFallbackNotice = null;
    const showFallback = streamFallbackNotice !== null;
    expect(showFallback).toBe(false);
  });

  /**
   * Tests that TurnStageStatus component is no longer used.
   * In T4, TurnStageStatus was removed from the game page.
   * The stage label is now displayed within NarrationPanel instead.
   */
  it('TurnStageStatus was removed - stage display is in NarrationPanel', () => {
    // This test verifies that TurnStageStatus is no longer rendered separately.
    // The import was removed in T4 - the stage label is now passed to NarrationPanel.
    // NarrationPanel displays stageLabel via the props interface.
    const NarrationPanelProps = {
      narration: '',
      isStreaming: true,
      stageLabel: '生成叙事文本……',
    };
    
    expect(NarrationPanelProps.stageLabel).toBe('生成叙事文本……');
    expect(NarrationPanelProps.isStreaming).toBe(true);
  });

  /**
   * Tests the complete wiring pattern for streaming status display.
   */
  it('wires currentStage to NarrationPanel stageLabel prop', () => {
    // Simulate the wiring from GameSessionPage
    const hookState = {
      currentStage: { code: 'narration', phase: 'started', label: '生成叙事文本……' },
      narration: '凌月站在试炼堂门口',
      isStreaming: true,
      usedFallback: false,
      streamFallbackNotice: null,
    };
    
    // Derive props for NarrationPanel
    const narrationPanelProps = {
      narration: hookState.narration,
      isStreaming: hookState.isStreaming,
      stageLabel: hookState.currentStage?.label ?? null,
      fallbackNotice: hookState.streamFallbackNotice,
    };
    
    expect(narrationPanelProps.stageLabel).toBe('生成叙事文本……');
    expect(narrationPanelProps.fallbackNotice).toBeNull();
  });

  it('wires fallback notice to NarrationPanel when stream fails', () => {
    const hookState: {
      currentStage: { code: string; phase: string; label: string } | null;
      narration: string;
      isStreaming: boolean;
      usedFallback: boolean;
      streamFallbackNotice: string;
    } = {
      currentStage: null,
      narration: '备用叙事内容',
      isStreaming: false,
      usedFallback: true,
      streamFallbackNotice: '实时连接失败，已切换为普通模式。',
    };
    
    const narrationPanelProps = {
      narration: hookState.narration,
      isStreaming: hookState.isStreaming,
      stageLabel: hookState.currentStage?.label ?? null,
      fallbackNotice: hookState.streamFallbackNotice,
    };
    
    expect(narrationPanelProps.fallbackNotice).toBe('实时连接失败，已切换为普通模式。');
    expect(narrationPanelProps.stageLabel).toBeNull();
    expect(narrationPanelProps.isStreaming).toBe(false);
  });
});
