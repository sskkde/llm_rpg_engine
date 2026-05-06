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
    recommended_actions: ['继续前进'],
    occurred_at: '2024-01-01T00:00:00Z',
    ...overrides,
  });

  it('renders empty state', () => {
    renderWithIntl(<LogPanel entries={[]} />);
    expect(screen.getByTestId('adventure-log')).toBeInTheDocument();
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
    expect(screen.getByTestId('adventure-log')).toBeInTheDocument();
    expect(screen.getByTestId('adventure-log-entry')).toBeInTheDocument();
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
    expect(screen.getByTestId('adventure-log')).toBeInTheDocument();
    expect(screen.getByTestId('adventure-log-entry')).toBeInTheDocument();
    expect(screen.getByText(/回合 1/)).toBeInTheDocument();
    expect(screen.getByText(/向前走/)).toBeInTheDocument();
  });

  it('calls onSelectEntry and marks the selected entry', () => {
    const entry = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '攻击敌人',
      narration: '你挥剑攻击敌人，造成了伤害。',
    });
    const onSelectEntry = jest.fn();
    
    renderWithIntl(
      <LogPanel entries={[entry]} selectedEntryId="turn-1" onSelectEntry={onSelectEntry} />
    );
    
    const button = screen.getByTestId('adventure-log-entry').querySelector('button');

    expect(button).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(button!);
    expect(onSelectEntry).toHaveBeenCalledWith(entry);
  });

  it('does not render inline expanded dialogue', () => {
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
    const onSelectEntry = jest.fn();

    renderWithIntl(<LogPanel entries={[entry1, entry2]} onSelectEntry={onSelectEntry} />);
    
    const entries = screen.getAllByTestId('adventure-log-entry');
    expect(entries).toHaveLength(2);
    
    fireEvent.click(entries[0].querySelector('button')!);
    expect(onSelectEntry).toHaveBeenCalledWith(entry1);
    expect(screen.queryByText('玩家行动:')).not.toBeInTheDocument();
    expect(screen.queryByText('叙事:')).not.toBeInTheDocument();
  });

  it('does not render internal fields', () => {
    const entry = createEntry({
      id: 'turn-1',
      turn_no: 1,
      action: '测试行动',
      narration: '测试叙事',
    });
    
    renderWithIntl(<LogPanel entries={[entry]} />);

    expect(screen.getByTestId('adventure-log')).toBeInTheDocument();
    expect(screen.getByTestId('adventure-log-entry')).toBeInTheDocument();

    // Verify internal fields are NOT in DOM
    expect(screen.queryByText('result_json')).not.toBeInTheDocument();
    expect(screen.queryByText('transaction_id')).not.toBeInTheDocument();
    expect(screen.queryByText('hidden_plan_state')).not.toBeInTheDocument();
  });
});
