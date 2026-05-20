import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { NPCPortrait } from '@/components/assets/NPCPortrait';
import * as api from '@/lib/api';
import { useAssetJob } from '@/hooks/useAssetJob';
import type { AssetJobResponse } from '@/types/api';

jest.mock('@/lib/api', () => ({
  createPortraitJob: jest.fn(),
  generatePortrait: jest.fn(),
  getAssetJob: jest.fn(),
  retryAssetJob: jest.fn(),
  cancelAssetJob: jest.fn(),
}));

jest.mock('@/hooks/useAssetJob', () => ({
  useAssetJob: jest.fn(),
}));

const mockedUseAssetJob = useAssetJob as jest.Mock;

const mockJobPending: AssetJobResponse = {
  job_id: 'job-1',
  asset_type: 'portrait',
  status: 'pending',
  attempt_count: 0,
  max_attempts: 3,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

const mockJobProcessing: AssetJobResponse = {
  ...mockJobPending,
  status: 'processing',
};

const mockJobCompleted: AssetJobResponse = {
  ...mockJobPending,
  status: 'completed',
  result_url: 'https://example.com/portrait.png',
};

const mockJobFailed: AssetJobResponse = {
  ...mockJobPending,
  status: 'failed',
  error_message: 'Generation failed',
};

const mockUseAssetJobReturn = {
  job: null,
  isLoading: false,
  error: null,
  isPolling: false,
  retry: jest.fn(),
  cancel: jest.fn(),
  refetch: jest.fn(),
};

describe('NPCPortrait P8', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseAssetJob.mockReturnValue(mockUseAssetJobReturn);
  });

  describe('with sessionId (async job flow)', () => {
    it('renders loading state while initializing job', async () => {
      (api.createPortraitJob as jest.Mock).mockReturnValue(new Promise(() => {}));
      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);
      await waitFor(() => {
        expect(screen.getByText('生成中...')).toBeInTheDocument();
      });
    });

    it('renders image when job is completed', async () => {
      (api.createPortraitJob as jest.Mock).mockResolvedValue({ job_id: 'job-1' });
      mockedUseAssetJob.mockReturnValue({
        ...mockUseAssetJobReturn,
        job: mockJobCompleted,
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);

      await waitFor(() => {
        expect(screen.getByAltText('NPC Portrait')).toBeInTheDocument();
      });
    });

    it('shows loading spinner during processing', async () => {
      (api.createPortraitJob as jest.Mock).mockResolvedValue({ job_id: 'job-1' });
      mockedUseAssetJob.mockReturnValue({
        ...mockUseAssetJobReturn,
        job: mockJobProcessing,
        isLoading: true,
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);

      await waitFor(() => {
        expect(screen.getByText('生成中...')).toBeInTheDocument();
      });
    });

    it('shows retry button on failure', async () => {
      const mockRetry = jest.fn();
      (api.createPortraitJob as jest.Mock).mockResolvedValue({ job_id: 'job-1' });
      mockedUseAssetJob.mockReturnValue({
        ...mockUseAssetJobReturn,
        job: mockJobFailed,
        retry: mockRetry,
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);

      await waitFor(() => {
        expect(screen.getByText('Generation failed')).toBeInTheDocument();
      });

      const retryButton = screen.getByText('重试');
      expect(retryButton).toBeInTheDocument();

      fireEvent.click(retryButton);
      await waitFor(() => {
        expect(mockRetry).toHaveBeenCalled();
      });
    });

    it('shows emoji fallback when image fails to load', async () => {
      (api.createPortraitJob as jest.Mock).mockResolvedValue({ job_id: 'job-1' });
      mockedUseAssetJob.mockReturnValue({
        ...mockUseAssetJobReturn,
        job: mockJobCompleted,
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);

      await waitFor(() => {
        expect(screen.getByAltText('NPC Portrait')).toBeInTheDocument();
      });

      const img = screen.getByAltText('NPC Portrait');
      fireEvent.error(img);

      await waitFor(() => {
        expect(screen.getByText('🧑')).toBeInTheDocument();
      });
    });

    it('shows mood-based emoji fallback', async () => {
      (api.createPortraitJob as jest.Mock).mockResolvedValue({ job_id: 'job-1' });
      mockedUseAssetJob.mockReturnValue({
        ...mockUseAssetJobReturn,
        job: mockJobCompleted,
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" mood="happy" />);

      await waitFor(() => {
        expect(screen.getByAltText('NPC Portrait')).toBeInTheDocument();
      });

      const img = screen.getByAltText('NPC Portrait');
      fireEvent.error(img);

      await waitFor(() => {
        expect(screen.getByText('😊')).toBeInTheDocument();
      });
    });

    it('shows error on job initialization failure', async () => {
      (api.createPortraitJob as jest.Mock).mockRejectedValue(new Error('Job init failed'));

      renderWithIntl(<NPCPortrait npcId="npc-1" sessionId="session-1" />);

      await waitFor(() => {
        expect(screen.getByText('Job init failed')).toBeInTheDocument();
      });
    });
  });

  describe('without sessionId (sync flow)', () => {
    it('shows fallback emoji without sessionId', async () => {
      (api.generatePortrait as jest.Mock).mockResolvedValue({
        asset_id: 'asset-1',
        asset_type: 'portrait',
        generation_status: 'completed',
        cache_hit: false,
        created_at: '2024-01-01T00:00:00Z',
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" />);

      await waitFor(() => {
        expect(screen.getByText('🧑')).toBeInTheDocument();
      });
    });

    it('does not call createPortraitJob when no sessionId', async () => {
      (api.generatePortrait as jest.Mock).mockResolvedValue({
        asset_id: 'asset-1',
        asset_type: 'portrait',
        generation_status: 'completed',
        cache_hit: false,
        created_at: '2024-01-01T00:00:00Z',
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" />);

      await waitFor(() => {
        expect(screen.getByText('🧑')).toBeInTheDocument();
      });

      expect(api.createPortraitJob).not.toHaveBeenCalled();
    });

    it('renders mood-based emoji in sync mode', async () => {
      (api.generatePortrait as jest.Mock).mockResolvedValue({
        asset_id: 'asset-1',
        asset_type: 'portrait',
        generation_status: 'completed',
        cache_hit: false,
        created_at: '2024-01-01T00:00:00Z',
      });

      renderWithIntl(<NPCPortrait npcId="npc-1" mood="angry" />);

      await waitFor(() => {
        expect(screen.getByText('😠')).toBeInTheDocument();
      });
    });
  });
});
