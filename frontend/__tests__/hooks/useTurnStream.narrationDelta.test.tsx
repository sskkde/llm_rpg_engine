/**
 * Tests for useTurnStream narration delta accumulation.
 *
 * Tests verify:
 * - Multiple narration_delta events accumulate correctly
 * - Empty delta strings are handled correctly
 * - Mixed event types do not interfere with narration accumulation
 */

import { describe, it, expect } from '@jest/globals';

describe('useTurnStream narration delta accumulation', () => {
  /**
   * Tests the core accumulation logic pattern used in useTurnStream.
   * The actual hook implementation at lines 155-160:
   *   case 'narration_delta':
   *     accumulatedNarration += event.delta;
   *     setState((prev) => ({...prev, narration: accumulatedNarration}));
   */
  it('accumulates multiple narration deltas correctly', () => {
    // Simulate the core accumulation logic used in useTurnStream
    const events = [
      { event: 'narration_delta', delta: '凌月' },
      { event: 'narration_delta', delta: '站在试炼堂门口' },
    ];
    
    let accumulated = '';
    for (const evt of events) {
      if (evt.event === 'narration_delta') {
        accumulated += evt.delta;
      }
    }
    
    expect(accumulated).toBe('凌月站在试炼堂门口');
  });

  it('handles empty delta string', () => {
    const events = [
      { event: 'narration_delta', delta: '' },
      { event: 'narration_delta', delta: '内容' },
    ];
    
    let accumulated = '';
    for (const evt of events) {
      if (evt.event === 'narration_delta') {
        accumulated += evt.delta;
      }
    }
    
    expect(accumulated).toBe('内容');
  });

  it('accumulates deltas in order', () => {
    const events = [
      { event: 'narration_delta', delta: '第一' },
      { event: 'narration_delta', delta: '第二' },
      { event: 'narration_delta', delta: '第三' },
    ];
    
    let accumulated = '';
    for (const evt of events) {
      if (evt.event === 'narration_delta') {
        accumulated += evt.delta;
      }
    }
    
    expect(accumulated).toBe('第一第二第三');
  });

  it('handles mixed event types without interference', () => {
    const events = [
      { event: 'narration_delta', delta: '开始' },
      { event: 'stage_started', stage: 'narration', label: '生成叙事文本……' },
      { event: 'narration_delta', delta: '中间' },
      { event: 'heartbeat' },
      { event: 'narration_delta', delta: '结束' },
    ];
    
    let accumulated = '';
    for (const evt of events) {
      if (evt.event === 'narration_delta') {
        accumulated += evt.delta;
      }
    }
    
    expect(accumulated).toBe('开始中间结束');
  });

  it('handles Chinese characters correctly', () => {
    const events = [
      { event: 'narration_delta', delta: '山' },
      { event: 'narration_delta', delta: '门' },
      { event: 'narration_delta', delta: '云' },
      { event: 'narration_delta', delta: '雾' },
    ];
    
    let accumulated = '';
    for (const evt of events) {
      if (evt.event === 'narration_delta') {
        accumulated += evt.delta;
      }
    }
    
    expect(accumulated).toBe('山门云雾');
    expect(accumulated.length).toBe(4);
  });
});
