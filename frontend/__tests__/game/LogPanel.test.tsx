import { screen, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { LogPanel } from '@/components/game/LogPanel';
import { AdventureLogEntry } from '@/types/api';

describe('LogPanel', () => {
  const createEntry = (overrides: Partial<AdventureLogEntry> = {}): AdventureLogEntry => ({
    id: 'test-id-1',
    turn_no: 1,
    event_type: 'player_turn',
    action: '观察四周',
    narration: '你环顾四周，发现这里是一片神秘的森林。',
    occurred_at: '2024-01-01T00:00:00Z',
    ...overrides,
  });

  it('renders empty state', () => {
    renderWithIntl(<LogPanel entries={[]} />);
    expect(screen.getByText('暂无回合')).toBeInTheDocument();
  });

  it('renders initial scene entry', () => {
    const entry = createEntry({
      id: 'scene-1',
      event_type: 'initial_scene',
      action: null,
      narration: '故事开始了...',
    });
    
    renderWithIntl(<LogPanel entries={[entry]} />);
    expect(screen.getByText('初始场景')).toBeInTheDocument();
  });

  it('renders player turn entry', () => {
    const entry = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '向前走',
      narration: '你向前走去...',
    });
    
    renderWithIntl(<LogPanel entries={[entry]} />);
    expect(screen.getByText(/回合 1/)).toBeInTheDocument();
    expect(screen.getByText(/向前走/)).toBeInTheDocument();
  });

  it('expands and collapses player-visible dialogue', () => {
    const entry = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '攻击敌人',
      narration: '你挥剑攻击敌人，造成了伤害。',
    });
    
    renderWithIntl(<LogPanel entries={[entry]} />);
    
    const button = screen.getByRole('button');
    
    // Initially collapsed
    expect(button).toHaveAttribute('aria-expanded', 'false');
    
    // Click to expand
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('玩家行动:')).toBeInTheDocument();
    expect(screen.getByText('攻击敌人')).toBeInTheDocument();
    expect(screen.getByText('叙事:')).toBeInTheDocument();
    
    // Click to collapse
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('allows multiple entries open simultaneously', () => {
    const entry1 = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '行动一',
      narration: '叙事一',
    });
    const entry2 = createEntry({
      id: 'turn-2',
      turn_no: 2,
      action: '行动二',
      narration: '叙事二',
    });
    
    renderWithIntl(<LogPanel entries={[entry1, entry2]} />);
    
    const buttons = screen.getAllByRole('button');
    
    // Expand first entry
    fireEvent.click(buttons[0]);
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'true');
    
    // Expand second entry
    fireEvent.click(buttons[1]);
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'true');
    
    // Both should still be expanded
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'true');
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'true');
  });

  it('does not render internal fields', () => {
    const entry = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '测试行动',
      narration: '测试叙事',
    });
    
    renderWithIntl(<LogPanel entries={[entry]} />);
    
    // Expand to show full content
    fireEvent.click(screen.getByRole('button'));
    
    // Verify internal fields are NOT in DOM
    expect(screen.queryByText('result_json')).not.toBeInTheDocument();
    expect(screen.queryByText('transaction_id')).not.toBeInTheDocument();
    expect(screen.queryByText('hidden_plan_state')).not.toBeInTheDocument();
  });
});
