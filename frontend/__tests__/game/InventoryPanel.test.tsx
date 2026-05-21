import { screen, waitFor, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { InventoryPanel } from '@/components/game/InventoryPanel';
import * as api from '@/lib/api';
import type { PlayerInventoryItem, InventoryStats } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getPlayerInventory: jest.fn(),
  getPlayerInventoryStats: jest.fn(),
}));

const mockGetPlayerInventory = api.getPlayerInventory as jest.MockedFunction<typeof api.getPlayerInventory>;
const mockGetPlayerInventoryStats = api.getPlayerInventoryStats as jest.MockedFunction<typeof api.getPlayerInventoryStats>;

describe('InventoryPanel', () => {
  const sessionId = 'test-session-id';

const createMockItem = (overrides: Partial<PlayerInventoryItem> = {}): PlayerInventoryItem => ({
  id: 'item-1',
  name: 'Test Item',
  description: 'A test item description',
  quantity: 1,
  rarity: 'common',
  item_type: 'consumable',
  effects: { hp: 10 },
  ...overrides,
});

  const createMockStats = (overrides: Partial<InventoryStats> = {}): InventoryStats => ({
    total_items: 5,
    unique_items: 3,
    categories: { consumable: 2, equipment: 1 },
    ...overrides,
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state initially', () => {
    mockGetPlayerInventory.mockImplementation(() => new Promise(() => {}));
    mockGetPlayerInventoryStats.mockImplementation(() => new Promise(() => {}));
    
    renderWithIntl(<InventoryPanel sessionId={sessionId} />);
    
    expect(screen.getByText('物品栏')).toBeInTheDocument();
  });

  it('shows empty state when no items', async () => {
    mockGetPlayerInventory.mockResolvedValueOnce([]);
    mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
    
    renderWithIntl(<InventoryPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('物品栏为空')).toBeInTheDocument();
    });
    
    expect(mockGetPlayerInventory).toHaveBeenCalledWith(sessionId, undefined);
  });

  it('renders item list with quantities', async () => {
    const item1 = createMockItem({ id: 'item-1', name: 'Health Potion', quantity: 3 });
    const item2 = createMockItem({ id: 'item-2', name: 'Mana Potion', quantity: 2, rarity: 'uncommon' });
    
    mockGetPlayerInventory.mockResolvedValueOnce([item1, item2]);
    mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
    
    renderWithIntl(<InventoryPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Health Potion')).toBeInTheDocument();
    });
    
    expect(screen.getByText('Mana Potion')).toBeInTheDocument();
    expect(screen.getByText('x3')).toBeInTheDocument();
    expect(screen.getByText('x2')).toBeInTheDocument();
  });

  it('category filter tabs work', async () => {
    const item1 = createMockItem({ id: 'item-1', name: 'Health Potion', item_type: 'consumable' });
    
    mockGetPlayerInventory.mockResolvedValueOnce([item1]);
    mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
    
    renderWithIntl(<InventoryPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Health Potion')).toBeInTheDocument();
    });
    
    mockGetPlayerInventory.mockResolvedValueOnce([]);
    const equipmentTab = screen.getByRole('button', { name: '装备' });
    fireEvent.click(equipmentTab);
    
    await waitFor(() => {
      expect(mockGetPlayerInventory).toHaveBeenCalledWith(sessionId, 'equipment');
    });
  });

  it('shows item details on click', async () => {
    const item = createMockItem({ 
      id: 'item-1', 
      name: 'Health Potion',
      description: 'Restores 10 HP',
      effects: { hp: 10 }
    });
    
    mockGetPlayerInventory.mockResolvedValueOnce([item]);
    mockGetPlayerInventoryStats.mockResolvedValueOnce(createMockStats());
    
    renderWithIntl(<InventoryPanel sessionId={sessionId} />);
    
    await waitFor(() => {
      expect(screen.getByText('Health Potion')).toBeInTheDocument();
    });
    
    const itemButton = screen.getByRole('button', { name: /Health Potion/ });
    fireEvent.click(itemButton);
    
    await waitFor(() => {
      expect(screen.getByText('Restores 10 HP')).toBeInTheDocument();
    });
  });
});
