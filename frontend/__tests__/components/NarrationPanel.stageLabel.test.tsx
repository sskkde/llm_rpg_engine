/**
 * Tests for NarrationPanel stage label rendering.
 *
 * Tests verify:
 * - stageLabel renders when streaming and no narration
 * - processingTurn renders when stageLabel is absent
 * - fallbackNotice renders when provided
 * - Old storyUnfolds text is not rendered in typing area
 */

import { screen } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { NarrationPanel } from '@/components/game/NarrationPanel';

describe('NarrationPanel stage label', () => {
  it('renders stageLabel when streaming and no narration', () => {
    renderWithIntl(
      <NarrationPanel
        narration=""
        isStreaming={true}
        stageLabel="NPC 思考中……"
      />
    );
    expect(screen.getByText('NPC 思考中……')).toBeTruthy();
  });

  it('renders processingTurn when stageLabel absent', () => {
    renderWithIntl(
      <NarrationPanel
        narration=""
        isStreaming={true}
      />
    );
    expect(screen.getByText('正在处理当前回合……')).toBeTruthy();
  });

  it('renders fallbackNotice when provided', () => {
    renderWithIntl(
      <NarrationPanel
        narration=""
        isStreaming={true}
        fallbackNotice="实时连接失败，已切换为普通模式。"
      />
    );
    expect(screen.getByText('实时连接失败，已切换为普通模式。')).toBeTruthy();
  });

  it('does not render old storyUnfolds text in typing area', () => {
    renderWithIntl(
      <NarrationPanel
        narration=""
        isStreaming={true}
        stageLabel="NPC 思考中……"
      />
    );
    expect(screen.queryByText('故事展开中...')).toBeNull();
  });

  it('renders narration content when streaming with narration', () => {
    renderWithIntl(
      <NarrationPanel
        narration="你站在山门前，云雾缭绕。"
        isStreaming={true}
        stageLabel="生成叙事中……"
      />
    );
    expect(screen.getByText(/你站在山门前，云雾缭绕。/)).toBeTruthy();
  });

  it('renders completed narration when not streaming', () => {
    renderWithIntl(
      <NarrationPanel
        narration="故事已经展开。"
        isStreaming={false}
      />
    );
    expect(screen.getByText('故事已经展开。')).toBeTruthy();
  });
});
