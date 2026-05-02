import {screen, fireEvent} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import { SaveSlotList } from '@/components/saves/SaveSlotList';
import type { SaveSlot } from '@/types/api';

const mockSaves: SaveSlot[] = [
  { id: '1', user_id: 'u1', slot_number: 1, name: 'My Save', created_at: '2024-01-01T00:00:00Z', session_count: 2 },
  { id: '2', user_id: 'u1', slot_number: 2, created_at: '2024-01-02T00:00:00Z', session_count: 0 },
];

describe('SaveSlotList', () => {
  const onSelect = jest.fn();
  const onDelete = jest.fn();
  const onRetry = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state', () => {
    renderWithIntl(
      <SaveSlotList saves={[]} isLoading={true} error={null} onSelect={onSelect} onDelete={onDelete} onRetry={onRetry} />
    , {locale: 'en'});
    expect(screen.getByText(/loading saves/i)).toBeInTheDocument();
  });

  it('renders error state', () => {
    renderWithIntl(
      <SaveSlotList saves={[]} isLoading={false} error="Failed to load" onSelect={onSelect} onDelete={onDelete} onRetry={onRetry} />
    , {locale: 'en'});
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument();
  });

  it('renders empty state', () => {
    renderWithIntl(
      <SaveSlotList saves={[]} isLoading={false} error={null} onSelect={onSelect} onDelete={onDelete} onRetry={onRetry} />
    , {locale: 'en'});
    expect(screen.getByText(/no saves yet/i)).toBeInTheDocument();
  });

  it('renders save slots', () => {
    renderWithIntl(
      <SaveSlotList saves={mockSaves} isLoading={false} error={null} onSelect={onSelect} onDelete={onDelete} onRetry={onRetry} />
    , {locale: 'en'});
    expect(screen.getByText('My Save')).toBeInTheDocument();
    expect(screen.getByText('Save Slot 2')).toBeInTheDocument();
  });

  it('calls onSelect when clicking a save', () => {
    renderWithIntl(
      <SaveSlotList saves={mockSaves} isLoading={false} error={null} onSelect={onSelect} onDelete={onDelete} onRetry={onRetry} />
    , {locale: 'en'});
    fireEvent.click(screen.getByText('My Save'));
    expect(onSelect).toHaveBeenCalledWith(mockSaves[0]);
  });
});
