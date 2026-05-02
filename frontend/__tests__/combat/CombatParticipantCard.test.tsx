import {screen} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import { CombatParticipantCard } from '@/components/game/CombatParticipantCard';
import type { CombatParticipant } from '@/types/api';

const mockParticipant: CombatParticipant = {
  entity_id: 'npc-1',
  name: 'Goblin',
  hp: 50,
  max_hp: 100,
  is_player: false,
  is_defeated: false,
};

describe('CombatParticipantCard', () => {
  const onSelect = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders participant name and HP', () => {
    renderWithIntl(
      <CombatParticipantCard
        participant={mockParticipant}
        isSelected={false}
        onSelect={onSelect}
        isPlayer={false}
      />
    , {locale: 'en'});
    expect(screen.getByText('Goblin')).toBeInTheDocument();
    expect(screen.getByText('50/100 HP')).toBeInTheDocument();
  });

  it('calls onSelect when clicked', () => {
    renderWithIntl(
      <CombatParticipantCard
        participant={mockParticipant}
        isSelected={false}
        onSelect={onSelect}
        isPlayer={false}
      />
    , {locale: 'en'});
    screen.getByText('Goblin').click();
    expect(onSelect).toHaveBeenCalledWith('npc-1');
  });

  it('shows defeated badge when defeated', () => {
    renderWithIntl(
      <CombatParticipantCard
        participant={{ ...mockParticipant, is_defeated: true }}
        isSelected={false}
        onSelect={onSelect}
        isPlayer={false}
      />
    , {locale: 'en'});
    expect(screen.getByText('Defeated')).toBeInTheDocument();
  });

  it('shows player badge for player', () => {
    renderWithIntl(
      <CombatParticipantCard
        participant={{ ...mockParticipant, is_player: true }}
        isSelected={false}
        onSelect={onSelect}
        isPlayer={true}
      />
    , {locale: 'en'});
    expect(screen.getByText('Player')).toBeInTheDocument();
  });
});
