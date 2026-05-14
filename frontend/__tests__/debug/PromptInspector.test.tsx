import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { PromptInspector } from '@/components/debug/PromptInspector';
import * as api from '@/lib/api';

jest.mock('@/lib/api', () => ({
  getPromptInspector: jest.fn(),
}));

const mockPromptInspectorResponse = {
  session_id: 'test-session-123',
  total_turns: 2,
  prompt_templates: [
    {
      prompt_template_id: 'pt-1',
      proposal_type: 'narration',
      turn_no: 1,
      model_name: 'gpt-4',
      confidence: 0.95,
    },
  ],
  model_calls: [
    {
      call_id: 'mc-1',
      turn_no: 1,
      prompt_type: 'narration',
      model_name: 'gpt-4',
      provider: 'openai',
      input_tokens: 500,
      output_tokens: 200,
      cost_estimate: 0.015,
      latency_ms: 1500,
      success: true,
      created_at: '2024-01-01T00:00:00Z',
    },
    {
      call_id: 'mc-2',
      turn_no: 2,
      prompt_type: 'npc_decision',
      model_name: 'gpt-4',
      provider: 'openai',
      input_tokens: 300,
      output_tokens: 100,
      cost_estimate: 0.008,
      latency_ms: 800,
      success: true,
      created_at: '2024-01-01T00:01:00Z',
    },
  ],
  context_builds: [
    {
      build_id: 'cb-1',
      turn_no: 1,
      perspective_type: 'player',
      perspective_id: 'player-1',
      included_memories: [
        {
          memory_id: 'mem-1',
          memory_type: 'episodic',
          owner_id: 'player',
          included: true,
          reason: 'high_relevance',
          relevance_score: 0.9,
          importance_score: 0.8,
          recency_score: 1.0,
          perspective_filter_applied: false,
          forbidden_knowledge_flag: false,
        },
      ],
      excluded_memories: [],
      total_candidates: 5,
      included_count: 1,
      excluded_count: 4,
      context_token_count: 300,
      build_duration_ms: 50,
    },
  ],
  proposals: [
    {
      audit_id: 'prop-1',
      turn_no: 1,
      proposal_type: 'narration',
      prompt_template_id: 'pt-1',
      model_name: 'gpt-4',
      input_tokens: 500,
      output_tokens: 200,
      latency_ms: 1500,
      raw_output_preview: 'The player enters the cave...',
      raw_output_hash: 'hash123',
      parsed_proposal: { narration: 'The player enters the cave...' },
      parse_success: true,
      repair_attempts: 0,
      repair_strategies_tried: [],
      repair_success: true,
      validation_passed: true,
      validation_errors: [],
      validation_warnings: [],
      rejected: false,
      rejection_reason: null,
      fallback_used: false,
      fallback_reason: null,
      fallback_strategy: null,
      confidence: 0.95,
      perspective_check_passed: true,
      forbidden_info_detected: [],
    },
  ],
  validations: [
    {
      validation_id: 'val-1',
      turn_no: 1,
      validation_target: 'proposal',
      overall_status: 'pass',
      checks: [
        {
          check_id: 'chk-1',
          check_type: 'schema',
          status: 'pass',
          message: 'Schema valid',
          details: {},
        },
      ],
      error_count: 0,
      warning_count: 0,
      errors: [],
      warnings: [],
    },
  ],
  aggregates: {
    total_tokens_used: 1100,
    total_cost: 0.023,
    total_latency_ms: 2300,
    total_model_calls: 2,
    call_success_rate: 100.0,
    repair_success_rate: 100.0,
  },
};

describe('PromptInspector', () => {
  const mockGetPromptInspector = api.getPromptInspector as jest.Mock;

  beforeEach(() => {
    mockGetPromptInspector.mockClear();
  });

  it('renders load button when no data loaded', () => {
    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    expect(screen.getByRole('button', { name: '加载' })).toBeInTheDocument();
  });

  it('shows filter inputs for turn range', () => {
    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    // Labels are present but not associated with inputs via htmlFor
    expect(screen.getByText('起始回合')).toBeInTheDocument();
    expect(screen.getByText('结束回合')).toBeInTheDocument();
  });

  it('calls API with session ID when load button clicked', async () => {
    mockGetPromptInspector.mockResolvedValueOnce(mockPromptInspectorResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(mockGetPromptInspector).toHaveBeenCalledWith('test-session-123', undefined, undefined);
    });
  });

  it('calls API with turn range filters', async () => {
    mockGetPromptInspector.mockResolvedValueOnce(mockPromptInspectorResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    // Find inputs by their position/type since labels aren't associated
    const inputs = screen.getAllByRole('spinbutton');
    const startTurnInput = inputs[0];
    const endTurnInput = inputs[1];

    fireEvent.change(startTurnInput, { target: { value: '1' } });
    fireEvent.change(endTurnInput, { target: { value: '5' } });

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(mockGetPromptInspector).toHaveBeenCalledWith('test-session-123', 1, 5);
    });
  });

  it('displays model calls table after loading', async () => {
    mockGetPromptInspector.mockResolvedValueOnce(mockPromptInspectorResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Multiple gpt-4 entries exist in the table
      expect(screen.getAllByText('gpt-4').length).toBeGreaterThan(0);
    });
  });

  it('displays aggregates summary', async () => {
    mockGetPromptInspector.mockResolvedValueOnce(mockPromptInspectorResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('$0.0230')).toBeInTheDocument();
    });
  });

  it('expands row to show details when clicked', async () => {
    mockGetPromptInspector.mockResolvedValueOnce(mockPromptInspectorResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Multiple gpt-4 entries exist in the table
      expect(screen.getAllByText('gpt-4').length).toBeGreaterThan(0);
    });

    const firstRow = screen.getByText('1').closest('tr');
    if (firstRow) {
      fireEvent.click(firstRow);
    }

    await waitFor(() => {
      expect(screen.getByText('Proposals')).toBeInTheDocument();
    });
  });

  it('shows error message on API failure', async () => {
    const error = new Error('API Error');
    (error as unknown as { status: number }).status = 500;
    mockGetPromptInspector.mockRejectedValueOnce(error);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Error message is displayed in ErrorMessage component
      expect(screen.getByText(/加载会话数据失败/)).toBeInTheDocument();
    });
  });

  it('shows empty state when no model calls', async () => {
    const emptyResponse = {
      ...mockPromptInspectorResponse,
      model_calls: [],
      aggregates: {
        total_tokens_used: 0,
        total_cost: 0,
        total_latency_ms: 0,
        total_model_calls: 0,
        call_success_rate: 100.0,
        repair_success_rate: 100.0,
      },
    };
    mockGetPromptInspector.mockResolvedValueOnce(emptyResponse);

    renderWithIntl(<PromptInspector sessionId="test-session-123" />);

    const loadButton = screen.getByRole('button', { name: '加载' });
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('无数据')).toBeInTheDocument();
    });
  });
});
