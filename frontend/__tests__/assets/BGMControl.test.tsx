import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { BGMControl } from '@/components/assets/BGMControl';
import * as api from '@/lib/api';
import { AssetGenerationStatus } from '@/types/api';

jest.mock('@/lib/api', () => ({ generateBGM: jest.fn() }));

describe('BGMControl', () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it('shows muted state', () => {
    renderWithIntl(<BGMControl muted />);
    expect(screen.getByText('已静音')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    (api.generateBGM as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<BGMControl />);
    expect(screen.getByText('生成中...')).toBeInTheDocument();
  });

  it('shows BGM available when loaded', async () => {
    (api.generateBGM as jest.Mock).mockResolvedValue({
      asset_id: 'bgm-1', asset_type: 'bgm',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<BGMControl />);
    await waitFor(() => {
      expect(screen.getByText('背景音乐可用')).toBeInTheDocument();
    });
  });

  it('does not generate when muted', () => {
    renderWithIntl(<BGMControl muted />);
    expect(api.generateBGM).not.toHaveBeenCalled();
  });

  it('shows play button when BGM is available', async () => {
    (api.generateBGM as jest.Mock).mockResolvedValue({
      asset_id: 'bgm-1', asset_type: 'bgm',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<BGMControl />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
    });
  });

  it('shows unavailable state when asset is not completed', async () => {
    (api.generateBGM as jest.Mock).mockResolvedValue({
      asset_id: 'bgm-1', asset_type: 'bgm',
      generation_status: AssetGenerationStatus.PENDING, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<BGMControl />);
    await waitFor(() => {
      expect(screen.getByText('背景音乐不可用')).toBeInTheDocument();
    });
  });

  it('silently handles API failure', async () => {
    (api.generateBGM as jest.Mock).mockRejectedValue(new Error('API error'));
    renderWithIntl(<BGMControl />);
    await waitFor(() => {
      expect(screen.queryByText('加载失败')).not.toBeInTheDocument();
    });
  });

  it('toggles play state on button click', async () => {
    (api.generateBGM as jest.Mock).mockResolvedValue({
      asset_id: 'bgm-1', asset_type: 'bgm',
      generation_status: AssetGenerationStatus.COMPLETED, cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<BGMControl />);
    
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '播放' })).toBeInTheDocument();
    });
    
    const playButton = screen.getByRole('button', { name: '播放' });
    fireEvent.click(playButton);
    
    expect(screen.getByRole('button', { name: '暂停' })).toBeInTheDocument();
  });
});
