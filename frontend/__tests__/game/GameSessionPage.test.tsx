import { screen, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import GameSessionPage from '@/app/[locale]/game/[sessionId]/page';

const mockGetSessionSnapshot = jest.fn();
const mockGetAdventureLog = jest.fn();
const mockExecuteTurn = jest.fn();

jest.mock('@/lib/api', () => ({
  getSessionSnapshot: (...args: unknown[]) => mockGetSessionSnapshot(...args),
  getAdventureLog: (...args: unknown[]) => mockGetAdventureLog(...args),
  executeTurn: (...args: unknown[]) => mockExecuteTurn(...args),
}));

jest.mock('@/hooks/useTurnStream', () => ({
  useTurnStream: () => ({
    isStreaming: false,
    isPending: false,
    narration: '',
    error: null,
    usedFallback: false,
    submitTurn: jest.fn(),
    clearError: jest.fn(),
  }),
}));

jest.mock('@/components/ui/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/zh/game/test-session',
}));

function renderPage() {
  return renderWithIntl(
    <GameSessionPage params={Promise.resolve({ sessionId: 'test-session' })} />
  );
}

describe('GameSessionPage - adventure log loading', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetSessionSnapshot.mockResolvedValue({
      session_id: 'test-session',
      world_id: 'world-1',
      player_state: { hp: 100, max_hp: 100, level: 1 },
      session_state: { active_mode: 'exploration' },
    });
  });

  it('restores initial scene narration from adventure log', async () => {
    mockGetAdventureLog.mockResolvedValue([
      {
        id: 'entry-1',
        turn_no: 0,
        event_type: 'initial_scene',
        action: null,
        narration: '你站在一座古老的山门前，云雾缭绕。',
        occurred_at: '2025-01-01T00:00:00Z',
      },
    ]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('你站在一座古老的山门前，云雾缭绕。')).toBeInTheDocument();
    });
  });

  it('restores latest persisted turn narration', async () => {
    mockGetAdventureLog.mockResolvedValue([
      {
        id: 'entry-1',
        turn_no: 0,
        event_type: 'initial_scene',
        action: null,
        narration: '你站在一座古老的山门前。',
        occurred_at: '2025-01-01T00:00:00Z',
      },
      {
        id: 'entry-2',
        turn_no: 1,
        event_type: 'player_turn',
        action: '观察四周',
        narration: '你环顾四周，发现一条蜿蜒的小路通向山林深处。',
        occurred_at: '2025-01-01T00:01:00Z',
      },
    ]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('你环顾四周，发现一条蜿蜒的小路通向山林深处。')).toBeInTheDocument();
    });
  });
});
