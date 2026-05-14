import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { StateDiffViewer } from '@/components/debug/StateDiffViewer';
import type { StateDiffResponse } from '@/types/api';

const mockStateDiff: StateDiffResponse = {
  entries: [
    {
      path: 'player_state.hp',
      operation: 'change',
      old_value: 100,
      new_value: 80,
    },
    {
      path: 'player_state.mana',
      operation: 'add',
      old_value: undefined,
      new_value: 50,
    },
    {
      path: 'npc_states.npc_1.location',
      operation: 'change',
      old_value: 'location_1',
      new_value: 'location_2',
    },
    {
      path: 'inventory.gold',
      operation: 'remove',
      old_value: 100,
      new_value: undefined,
    },
    {
      path: 'quest_states.quest_1.status',
      operation: 'change',
      old_value: 'in_progress',
      new_value: 'completed',
    },
    {
      path: 'location_states.location_1.visited',
      operation: 'add',
      old_value: undefined,
      new_value: true,
    },
    {
      path: 'unknown_field',
      operation: 'add',
      old_value: undefined,
      new_value: 'test',
    },
  ],
  added_keys: ['player_state.mana', 'location_states.location_1.visited', 'unknown_field'],
  removed_keys: ['inventory.gold'],
  changed_keys: ['player_state.hp', 'npc_states.npc_1.location', 'quest_states.quest_1.status'],
};

describe('StateDiffViewer', () => {
  it('renders empty state when no entries', () => {
    const emptyDiff: StateDiffResponse = {
      entries: [],
      added_keys: [],
      removed_keys: [],
      changed_keys: [],
    };

    renderWithIntl(<StateDiffViewer stateDiff={emptyDiff} />);

    expect(screen.getByText('无状态变更')).toBeInTheDocument();
  });

  it('displays summary stats with badges', () => {
    renderWithIntl(<StateDiffViewer stateDiff={mockStateDiff} />);

    // Multiple badges exist for each operation type
    expect(screen.getAllByText('新增').length).toBeGreaterThan(0);
    expect(screen.getAllByText('移除').length).toBeGreaterThan(0);
    expect(screen.getAllByText('变更').length).toBeGreaterThan(0);
  });

  it('categorizes entries by state category', () => {
    renderWithIntl(<StateDiffViewer stateDiff={mockStateDiff} />);

    expect(screen.getByText('玩家状态')).toBeInTheDocument();
    expect(screen.getByText('NPC状态')).toBeInTheDocument();
    expect(screen.getByText('物品栏')).toBeInTheDocument();
    expect(screen.getByText('任务状态')).toBeInTheDocument();
    expect(screen.getByText('地点状态')).toBeInTheDocument();
    expect(screen.getByText('其他')).toBeInTheDocument();
  });

  it('shows entry counts in category summaries', () => {
    renderWithIntl(<StateDiffViewer stateDiff={mockStateDiff} />);

    // Entry counts appear in category summaries like "(2)"
    expect(screen.getAllByText(/\(\d+\)/).length).toBeGreaterThan(0);
  });

  it('expands category on click', async () => {
    renderWithIntl(<StateDiffViewer stateDiff={mockStateDiff} />);

    const playerCategory = screen.getByText('玩家状态').closest('button');
    if (playerCategory) {
      fireEvent.click(playerCategory);
    }

    await waitFor(() => {
      expect(screen.getByText('player_state.hp')).toBeInTheDocument();
    });
  });

  it('displays diff values correctly for change operation', async () => {
    renderWithIntl(<StateDiffViewer stateDiff={mockStateDiff} />);

    const playerCategory = screen.getByText('玩家状态').closest('button');
    if (playerCategory) {
      fireEvent.click(playerCategory);
    }

    await waitFor(() => {
      // "旧值" and "新值" appear in multiple diff entries
      expect(screen.getAllByText('旧值').length).toBeGreaterThan(0);
      expect(screen.getAllByText('新值').length).toBeGreaterThan(0);
    });
  });

  it('respects maxEntries prop', () => {
    const manyEntries = Array.from({ length: 100 }, (_, i) => ({
      path: `player_state.field_${i}`,
      operation: 'add' as const,
      old_value: undefined,
      new_value: i,
    }));

    const largeDiff: StateDiffResponse = {
      entries: manyEntries,
      added_keys: manyEntries.map((e) => e.path),
      removed_keys: [],
      changed_keys: [],
    };

    renderWithIntl(<StateDiffViewer stateDiff={largeDiff} maxEntries={10} />);

    // The showingEntries message appears multiple times (for category and overall)
    expect(screen.getAllByText(/显示 10\/100 条/).length).toBeGreaterThan(0);
  });
});
