import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { SceneBackground } from '@/components/assets/SceneBackground';
import * as api from '@/lib/api';
import { AssetGenerationStatus } from '@/types/api';

jest.mock('@/lib/api', () => ({ generateSceneAsset: jest.fn() }));

describe('SceneBackground', () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it('renders with placeholder text', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(screen.getByText('加载中...')).toBeInTheDocument();
    });
  });

  it('calls generateSceneAsset on mount with locationId', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<SceneBackground locationId="loc-1" sessionId="sess-1" weather="rainy" timeOfDay="night" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalledWith({
        location_id: 'loc-1',
        session_id: 'sess-1',
        time_of_day: 'night',
        weather: 'rainy',
      });
    });
  });

  it('shows loading state while API pending', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(screen.getByText('加载中...')).toBeInTheDocument();
    });
  });

  it('shows background image when API succeeds with completed asset', async () => {
    (api.generateSceneAsset as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/scene.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      const backgroundDiv = container.querySelector('[style*="background-image"]');
      expect(backgroundDiv).toBeInTheDocument();
      expect(backgroundDiv).toHaveStyle({
        backgroundImage: 'url(https://example.com/scene.png)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      });
    });
  });

  it('shows gradient fallback when API fails', async () => {
    (api.generateSceneAsset as jest.Mock).mockRejectedValue(new Error('API error'));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
  });

  it('shows gradient fallback when asset status is failed', async () => {
    (api.generateSceneAsset as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.FAILED,
      error_message: 'Generation failed',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
  });

  it('re-requests when locationId changes', async () => {
    (api.generateSceneAsset as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/scene.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    const { rerender } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalledWith(
        expect.objectContaining({ location_id: 'loc-1' })
      );
    });

    rerender(<SceneBackground locationId="loc-2" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalledWith(
        expect.objectContaining({ location_id: 'loc-2' })
      );
      expect(api.generateSceneAsset).toHaveBeenCalledTimes(2);
    });
  });

  it('renders night gradient', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" timeOfDay="night" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('indigo-900');
  });

  it('renders rainy gradient', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" weather="rainy" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('slate-400');
  });

  it('renders snowy gradient', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" weather="snowy" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('blue-100');
  });

  it('renders default day gradient', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('blue-300');
  });

  it('includes locationId data attribute', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-123" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.dataset.locationId).toBe('loc-123');
  });

  it('includes sessionId data attribute when provided', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" sessionId="session-456" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalled();
    });
    const div = container.firstChild as HTMLElement;
    expect(div.dataset.sessionId).toBe('session-456');
  });

  it('uses default time_of_day when not provided', async () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(api.generateSceneAsset).toHaveBeenCalledWith(
        expect.objectContaining({ time_of_day: 'day' })
      );
    });
  });
});
