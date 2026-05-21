import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { LocationMapPanel } from '@/components/game/LocationMapPanel';
import * as api from '@/lib/api';
import type { PlayerLocation } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getPlayerLocations: jest.fn(),
}));

const mockGetPlayerLocations = api.getPlayerLocations as jest.MockedFunction<typeof api.getPlayerLocations>;

describe('LocationMapPanel', () => {
  const sessionId = 'test-session-id';

  const createMockLocation = (overrides: Partial<PlayerLocation> = {}): PlayerLocation => ({
    location_id: 'loc-1',
    name: 'Test Location',
    description: 'A test location description',
    connections: ['loc-2'],
    is_current: false,
    danger_level: 'safe',
    accessible: true,
    ...overrides,
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetPlayerLocations.mockImplementation(() => new Promise(() => {}));
    
    renderWithIntl(<LocationMapPanel sessionId={sessionId} />);
    
    expect(screen.getByText('地点地图')).toBeInTheDocument();
  });

  it('shows empty state when no locations', async () => {
    mockGetPlayerLocations.mockResolvedValueOnce([]);
    
    renderWithIntl(<LocationMapPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('尚未发现任何地点')).toBeInTheDocument();
    });
    
    expect(mockGetPlayerLocations).toHaveBeenCalledWith(sessionId);
  });

  it('renders known locations', async () => {
    const loc1 = createMockLocation({ location_id: 'loc-1', name: 'Village' });
    const loc2 = createMockLocation({ location_id: 'loc-2', name: 'Forest', connections: [] });
    
    mockGetPlayerLocations.mockResolvedValueOnce([loc1, loc2]);
    
    renderWithIntl(<LocationMapPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Village')).toBeInTheDocument();
    });
    
    expect(screen.getByText('Forest')).toBeInTheDocument();
  });

  it('highlights current location', async () => {
    const currentLoc = createMockLocation({ 
      location_id: 'loc-1', 
      name: 'Current Place',
      is_current: true 
    });
    const otherLoc = createMockLocation({ 
      location_id: 'loc-2', 
      name: 'Other Place',
      is_current: false 
    });
    
    mockGetPlayerLocations.mockResolvedValueOnce([currentLoc, otherLoc]);
    
    renderWithIntl(<LocationMapPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('当前位置')).toBeInTheDocument();
    });
    
    expect(screen.getByText('Current Place')).toBeInTheDocument();
    expect(screen.getByText('Other Place')).toBeInTheDocument();
  });

  it('shows danger level badges', async () => {
    const safeLoc = createMockLocation({ 
      location_id: 'loc-1', 
      name: 'Safe Village',
      danger_level: 'safe' 
    });
    const dangerLoc = createMockLocation({ 
      location_id: 'loc-2', 
      name: 'Dangerous Cave',
      danger_level: 'dangerous',
      is_current: false
    });
    
    mockGetPlayerLocations.mockResolvedValueOnce([safeLoc, dangerLoc]);
    
    renderWithIntl(<LocationMapPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('安全')).toBeInTheDocument();
    });
    
    expect(screen.getByText('危险')).toBeInTheDocument();
  });
});
