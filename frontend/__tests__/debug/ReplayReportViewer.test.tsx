import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { ReplayReportViewer } from '@/components/debug/ReplayReportViewer';
import type { ReplayReportResponse } from '@/types/api';

const mockReport: ReplayReportResponse = {
  session_id: 'test-session-123',
  snapshot_id: 'snapshot-1',
  from_turn: 1,
  to_turn: 10,
  replayed_event_count: 25,
  deterministic: true,
  llm_calls_made: 5,
  state_diff: {
    entries: [
      {
        path: 'player_state.hp',
        operation: 'change',
        old_value: 100,
        new_value: 80,
      },
    ],
    added_keys: [],
    removed_keys: [],
    changed_keys: ['player_state.hp'],
  },
  warnings: ['Warning 1', 'Warning 2'],
  created_at: '2024-01-01T00:00:00Z',
};

describe('ReplayReportViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    Object.defineProperty(window.URL, 'createObjectURL', {
      value: jest.fn(() => 'blob:test-url'),
      writable: true,
    });

    Object.defineProperty(window.URL, 'revokeObjectURL', {
      value: jest.fn(),
      writable: true,
    });

  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('displays report header with turn range', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('回放报告')).toBeInTheDocument();
    expect(screen.getByText(/回合范围/)).toBeInTheDocument();
  });

  it('shows deterministic status correctly when true', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('确定性')).toBeInTheDocument();
    expect(screen.getByText('通过')).toBeInTheDocument();
  });

  it('shows deterministic status correctly when false', () => {
    const nonDeterministicReport: ReplayReportResponse = {
      ...mockReport,
      deterministic: false,
    };

    renderWithIntl(<ReplayReportViewer report={nonDeterministicReport} />);

    expect(screen.getAllByText('警告').length).toBeGreaterThan(0);
  });

  it('displays LLM calls count', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('LLM调用')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('displays events count', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('事件')).toBeInTheDocument();
    expect(screen.getByText('25')).toBeInTheDocument();
  });

  it('displays state changes count', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('状态变更')).toBeInTheDocument();
    expect(screen.getAllByText('1').length).toBeGreaterThan(0);
  });

  it('shows warnings section when warnings exist', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('警告')).toBeInTheDocument();
    expect(screen.getByText('Warning 1')).toBeInTheDocument();
    expect(screen.getByText('Warning 2')).toBeInTheDocument();
  });

  it('hides warnings section when no warnings', () => {
    const reportWithoutWarnings: ReplayReportResponse = {
      ...mockReport,
      warnings: [],
    };

    renderWithIntl(<ReplayReportViewer report={reportWithoutWarnings} />);

    expect(screen.queryByText('警告')).not.toBeInTheDocument();
  });

  it('shows state diff section', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.getByText('状态差异')).toBeInTheDocument();
  });

  it('downloads JSON when download button clicked', async () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    const downloadButton = screen.getByText('下载JSON');

    const mockAnchor = document.createElement('a');
    const clickSpy = jest.spyOn(mockAnchor, 'click').mockImplementation(() => {});

    const createElementSpy = jest.spyOn(document, 'createElement').mockImplementation((tagName: string, options?: ElementCreationOptions) => {
      if (tagName === 'a') {
        return mockAnchor;
      }
      return document.createElement(tagName, options);
    });

    fireEvent.click(downloadButton);

    await waitFor(() => {
      expect(window.URL.createObjectURL).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
    });

    createElementSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it('calls onClose when close button clicked', async () => {
    const onClose = jest.fn();

    renderWithIntl(<ReplayReportViewer report={mockReport} onClose={onClose} />);

    const closeButton = screen.getByText('关闭');
    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('does not show close button when onClose not provided', () => {
    renderWithIntl(<ReplayReportViewer report={mockReport} />);

    expect(screen.queryByText('关闭')).not.toBeInTheDocument();
  });
});