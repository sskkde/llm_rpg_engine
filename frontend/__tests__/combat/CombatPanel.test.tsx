import {screen, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import { CombatPanel } from '@/components/game/CombatPanel';
import * as api from '@/lib/api';
import type { CombatSession, CombatEventsResponse } from '@/types/api';

jest.mock('@/lib/api', () => ({
  getCombat: jest.fn(),
  getCombatEvents: jest.fn(),
  submitCombatAction: jest.fn(),
  endCombat: jest.fn(),
}));

const mockCombat: CombatSession = {
  id: 'combat-001',
  session_id: 'session-001',
  status: 'active',
  current_round: 3,
  participants: [
    {
      entity_id: 'player-1',
      name: 'Hero',
      hp: 80,
      max_hp: 100,
      is_player: true,
      is_defeated: false,
    },
    {
      entity_id: 'enemy-1',
      name: 'Goblin',
      hp: 30,
      max_hp: 50,
      is_player: false,
      is_defeated: false,
    },
    {
      entity_id: 'enemy-2',
      name: 'Orc',
      hp: 60,
      max_hp: 100,
      is_player: false,
      is_defeated: false,
    },
  ],
};

const mockEvents: CombatEventsResponse = {
  combat_id: 'combat-001',
  events: [
    {
      event_id: 'event-001',
      combat_id: 'combat-001',
      round: 1,
      event_type: 'attack',
      timestamp: '2024-01-01T00:00:00Z',
    },
  ],
};

describe('CombatPanel', () => {
  const mockOnCombatEnd = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (api.getCombat as jest.Mock).mockResolvedValue(mockCombat);
    (api.getCombatEvents as jest.Mock).mockResolvedValue(mockEvents);
  });

  describe('locale-specific rendering', () => {
    it('renders combat title in zh', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('战斗')).toBeInTheDocument();
      });
    });

    it('renders combat title in en', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Combat')).toBeInTheDocument();
      });
    });

    it('shows round number in zh', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('第 3 回合')).toBeInTheDocument();
      });
    });

    it('shows round number in en', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Round 3')).toBeInTheDocument();
      });
    });
  });

  describe('loading state', () => {
    it('shows loading state before combat data loads', async () => {
      let resolveCombat: (value: CombatSession) => void;
      let resolveEvents: (value: CombatEventsResponse) => void;
      (api.getCombat as jest.Mock).mockImplementation(() => 
        new Promise((resolve) => { resolveCombat = resolve; })
      );
      (api.getCombatEvents as jest.Mock).mockImplementation(() =>
        new Promise((resolve) => { resolveEvents = resolve; })
      );

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Loading combat...')).toBeInTheDocument();
      });

      resolveCombat!(mockCombat);
      resolveEvents!(mockEvents);
      await waitFor(() => {
        expect(screen.queryByText('Loading combat...')).not.toBeInTheDocument();
      });
    });
  });

  describe('error state', () => {
    it('shows not found when combat fetch fails', async () => {
      (api.getCombat as jest.Mock).mockRejectedValue(new Error('Network error'));
      (api.getCombatEvents as jest.Mock).mockRejectedValue(new Error('Network error'));

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Combat not found')).toBeInTheDocument();
      });
    });

    it('shows not found message in zh locale on error', async () => {
      (api.getCombat as jest.Mock).mockRejectedValue(new Error('Network error'));
      (api.getCombatEvents as jest.Mock).mockRejectedValue(new Error('Network error'));

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('未找到战斗')).toBeInTheDocument();
      });
    });

    it('shows not found message when combat is null', async () => {
      (api.getCombat as jest.Mock).mockResolvedValue(null);
      (api.getCombatEvents as jest.Mock).mockResolvedValue(mockEvents);

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Combat not found')).toBeInTheDocument();
      });
    });

    it('shows not found message in zh locale', async () => {
      (api.getCombat as jest.Mock).mockResolvedValue(null);
      (api.getCombatEvents as jest.Mock).mockResolvedValue(mockEvents);

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('未找到战斗')).toBeInTheDocument();
      });
    });
  });

  describe('participants display', () => {
    it('shows player name', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Hero')).toBeInTheDocument();
      });
    });

    it('shows enemy names', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Goblin')).toBeInTheDocument();
        expect(screen.getByText('Orc')).toBeInTheDocument();
      });
    });

    it('shows section labels in zh', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('您')).toBeInTheDocument();
        expect(screen.getByText('敌人')).toBeInTheDocument();
      });
    });

    it('shows section labels in en', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('You')).toBeInTheDocument();
        expect(screen.getByText('Enemies')).toBeInTheDocument();
      });
    });
  });

  describe('action buttons', () => {
    it('shows action buttons when combat is active', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Attack')).toBeInTheDocument();
        expect(screen.getByText('Defend')).toBeInTheDocument();
        expect(screen.getByText('Skill')).toBeInTheDocument();
        expect(screen.getByText('Item')).toBeInTheDocument();
        expect(screen.getByText('Flee')).toBeInTheDocument();
      });
    });

    it('shows action buttons in zh locale', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('攻击')).toBeInTheDocument();
        expect(screen.getByText('防御')).toBeInTheDocument();
        expect(screen.getByText('技能')).toBeInTheDocument();
        expect(screen.getByText('物品')).toBeInTheDocument();
        expect(screen.getByText('逃跑')).toBeInTheDocument();
      });
    });

    it('shows return to game button when combat is ended', async () => {
      const endedCombat: CombatSession = {
        ...mockCombat,
        status: 'player_win',
      };
      (api.getCombat as jest.Mock).mockResolvedValue(endedCombat);

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Return to Game')).toBeInTheDocument();
      });
    });

    it('shows return to game button in zh locale', async () => {
      const endedCombat: CombatSession = {
        ...mockCombat,
        status: 'player_win',
      };
      (api.getCombat as jest.Mock).mockResolvedValue(endedCombat);

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('返回游戏')).toBeInTheDocument();
      });
    });
  });

  describe('events display', () => {
    it('shows events section label', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('Events')).toBeInTheDocument();
      });
    });

    it('shows events section label in zh', async () => {
      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('事件')).toBeInTheDocument();
      });
    });

    it('shows no events message when empty', async () => {
      (api.getCombatEvents as jest.Mock).mockResolvedValue({
        combat_id: 'combat-001',
        events: [],
      });

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'en'}
      );

      await waitFor(() => {
        expect(screen.getByText('No combat events yet')).toBeInTheDocument();
      });
    });

    it('shows no events message in zh', async () => {
      (api.getCombatEvents as jest.Mock).mockResolvedValue({
        combat_id: 'combat-001',
        events: [],
      });

      renderWithIntl(
        <CombatPanel combatId="combat-001" onCombatEnd={mockOnCombatEnd} />,
        {locale: 'zh'}
      );

      await waitFor(() => {
        expect(screen.getByText('暂无战斗事件')).toBeInTheDocument();
      });
    });
  });
});
