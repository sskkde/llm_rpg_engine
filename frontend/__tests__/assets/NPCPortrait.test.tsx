import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { NPCPortrait } from '@/components/assets/NPCPortrait';
import * as api from '@/lib/api';
import { AssetGenerationStatus } from '@/types/api';

jest.mock('@/lib/api', () => ({ generatePortrait: jest.fn() }));

describe('NPCPortrait', () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it('renders loading state initially', () => {
    (api.generatePortrait as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<NPCPortrait npcId="npc-1" />);
    expect(screen.getByText('生成中...')).toBeInTheDocument();
  });

  it('renders fallback on error', async () => {
    (api.generatePortrait as jest.Mock).mockRejectedValue(new Error('API error'));
    renderWithIntl(<NPCPortrait npcId="npc-1" />);
    await waitFor(() => {
      expect(screen.getByText('加载失败')).toBeInTheDocument();
    });
  });

  it('renders avatar when loaded', async () => {
    (api.generatePortrait as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1', asset_type: 'portrait',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<NPCPortrait npcId="npc-1" />);
    await waitFor(() => {
      expect(screen.getByText('🧑')).toBeInTheDocument();
    });
  });

  it('shows debug info when debug prop is true', async () => {
    (api.generatePortrait as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1', asset_type: 'portrait',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: true,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<NPCPortrait npcId="npc-1" debug />);
    await waitFor(() => {
      expect(screen.getByText('cached')).toBeInTheDocument();
    });
  });

  it('renders mood-based emoji', async () => {
    (api.generatePortrait as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1', asset_type: 'portrait',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<NPCPortrait npcId="npc-1" mood="happy" />);
    await waitFor(() => {
      expect(screen.getByText('😊')).toBeInTheDocument();
    });
  });

  it('shows error message from failed asset', async () => {
    (api.generatePortrait as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1', asset_type: 'portrait',
      generation_status: AssetGenerationStatus.FAILED,
      error_message: 'Custom error',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<NPCPortrait npcId="npc-1" />);
    await waitFor(() => {
      expect(screen.getByText('Custom error')).toBeInTheDocument();
    });
  });

  it('shows retry button on error', async () => {
    (api.generatePortrait as jest.Mock).mockRejectedValue(new Error('API error'));
    renderWithIntl(<NPCPortrait npcId="npc-1" />);
    await waitFor(() => {
      expect(screen.getByText('重试')).toBeInTheDocument();
    });
  });
});
