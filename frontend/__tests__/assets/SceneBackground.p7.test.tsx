import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { SceneBackground } from '@/components/assets/SceneBackground';
import * as api from '@/lib/api';
import { AssetGenerationStatus } from '@/types/api';

jest.mock('@/lib/api', () => ({ generateSceneAsset: jest.fn() }));

describe('SceneBackground P7 - Background Image Rendering', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('test_renders_gradient_on_loading', () => {
    (api.generateSceneAsset as jest.Mock).mockReturnValue(new Promise(() => {}));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('test_renders_placeholder_on_error', async () => {
    (api.generateSceneAsset as jest.Mock).mockRejectedValue(new Error('API error'));
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
  });

  it('test_renders_background_image_when_completed', async () => {
    const mockAsset = {
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/scene.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    };
    (api.generateSceneAsset as jest.Mock).mockResolvedValue(mockAsset);
    
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
    
    const hiddenImg = container.querySelector('img.hidden') as HTMLImageElement;
    expect(hiddenImg).toBeInTheDocument();
    expect(hiddenImg.src).toBe('https://example.com/scene.png');
  });

  it('test_falls_back_to_gradient_on_image_error', async () => {
    const mockAsset = {
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/broken.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    };
    (api.generateSceneAsset as jest.Mock).mockResolvedValue(mockAsset);
    
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    
    await waitFor(() => {
      const hiddenImg = container.querySelector('img.hidden') as HTMLImageElement;
      expect(hiddenImg).toBeInTheDocument();
    });
    
    const hiddenImg = container.querySelector('img.hidden') as HTMLImageElement;
    fireEvent.error(hiddenImg);
    
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
    
    const backgroundDiv = container.querySelector('[style*="background-image"]');
    expect(backgroundDiv).not.toBeInTheDocument();
  });

  it('test_renders_gradient_when_no_asset', async () => {
    (api.generateSceneAsset as jest.Mock).mockResolvedValue({
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.PENDING,
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    });
    
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
    
    const backgroundDiv = container.querySelector('[style*="background-image"]');
    expect(backgroundDiv).not.toBeInTheDocument();
  });

  it('test_resets_image_error_on_location_change', async () => {
    const mockAsset1 = {
      asset_id: 'asset-1',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/broken.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    };
    
    const mockAsset2 = {
      asset_id: 'asset-2',
      asset_type: 'scene',
      generation_status: AssetGenerationStatus.COMPLETED,
      result_url: 'https://example.com/working.png',
      cache_hit: false,
      created_at: '2024-01-01T00:00:00Z',
    };
    
    (api.generateSceneAsset as jest.Mock)
      .mockResolvedValueOnce(mockAsset1)
      .mockResolvedValueOnce(mockAsset2);
    
    const { container, rerender } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    
    await waitFor(() => {
      const hiddenImg = container.querySelector('img.hidden') as HTMLImageElement;
      expect(hiddenImg).toBeInTheDocument();
    });
    
    const hiddenImg = container.querySelector('img.hidden') as HTMLImageElement;
    fireEvent.error(hiddenImg);
    
    await waitFor(() => {
      expect(screen.getByText('场景背景')).toBeInTheDocument();
    });
    
    rerender(<SceneBackground locationId="loc-2" />);
    
    await waitFor(() => {
      const backgroundDiv = container.querySelector('[style*="background-image"]');
      expect(backgroundDiv).toBeInTheDocument();
      expect(backgroundDiv).toHaveStyle({
        backgroundImage: 'url(https://example.com/working.png)',
      });
    });
  });
});
