import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {ValidationAuditViewer} from '@/components/debug/ValidationAuditViewer';
import * as api from '@/lib/api';

jest.mock('@/lib/api');

const mockGetValidationAudit = api.getValidationAudit as jest.MockedFunction<typeof api.getValidationAudit>;

const mockValidationResponse = {
  validation_id: 'val-123',
  session_id: 'test-session',
  turn_no: 5,
  validation_target: 'action',
  target_id: 'action-456',
  overall_status: 'passed' as const,
  checks: [
    {
      check_id: 'check-1',
      check_type: 'action_validity',
      status: 'passed' as const,
      message: 'Action is valid',
      details: { action_type: 'move', valid: true },
    },
    {
      check_id: 'check-2',
      check_type: 'state_delta',
      status: 'passed' as const,
      message: 'State changes are valid',
      details: { changes: 3 },
    },
    {
      check_id: 'check-3',
      check_type: 'lore_consistency',
      status: 'warning' as const,
      message: 'Minor lore inconsistency detected',
      details: { severity: 'low' },
    },
    {
      check_id: 'check-4',
      check_type: 'perspective',
      status: 'passed' as const,
      message: undefined,
      details: {},
    },
  ],
  error_count: 0,
  warning_count: 1,
  errors: [],
  warnings: ['Minor lore inconsistency detected'],
  transaction_id: 'txn-789',
  created_at: '2024-01-01T10:00:00Z',
};

const mockFailedValidationResponse = {
  validation_id: 'val-456',
  session_id: 'test-session',
  turn_no: 10,
  validation_target: 'narration',
  target_id: undefined,
  overall_status: 'failed' as const,
  checks: [
    {
      check_id: 'check-5',
      check_type: 'narration_leak',
      status: 'failed' as const,
      message: 'Forbidden information leaked in narration',
      details: { leaked_info: ['npc_secret', 'hidden_location'] },
    },
    {
      check_id: 'check-6',
      check_type: 'perspective',
      status: 'failed' as const,
      message: 'Narration contains player-invisible information',
      details: { perspective: 'player' },
    },
  ],
  error_count: 2,
  warning_count: 0,
  errors: [
    'Forbidden information leaked in narration',
    'Narration contains player-invisible information',
  ],
  warnings: [],
  transaction_id: undefined,
  created_at: '2024-01-02T10:00:00Z',
};

describe('ValidationAuditViewer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetValidationAudit.mockResolvedValue(mockValidationResponse);
  });

  it('shows empty state when no session ID provided', () => {
    renderWithIntl(<ValidationAuditViewer sessionId="" validationId="val-123" />);
    expect(screen.getByText('未加载验证')).toBeInTheDocument();
  });

  it('shows empty state when no validation ID provided', () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="" />);
    expect(screen.getByText('未加载验证')).toBeInTheDocument();
  });

  it('shows load button when valid props provided', () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);
    expect(screen.getByText('加载验证审计数据')).toBeInTheDocument();
  });

  it('loads data when button clicked', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(mockGetValidationAudit).toHaveBeenCalledWith('test-session', 'val-123');
    });

    await waitFor(() => {
      expect(screen.getByText('验证审计')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    const error = new Error('Failed to load') as Error & { status?: number };
    error.status = 500;
    mockGetValidationAudit.mockRejectedValue(error);

    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('加载会话数据失败')).toBeInTheDocument();
    });
  });

  it('shows 404 error when validation not found', async () => {
    const error = new Error('Not found') as Error & { status?: number };
    error.status = 404;
    mockGetValidationAudit.mockRejectedValue(error);

    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="nonexistent" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('验证未找到')).toBeInTheDocument();
    });
  });

  it('shows 401/403 error with admin required message', async () => {
    const error = new Error('Forbidden') as Error & { status?: number };
    error.status = 403;
    mockGetValidationAudit.mockRejectedValue(error);

    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('需要管理员权限')).toBeInTheDocument();
    });
  });

  it('displays overall status and check counts', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('整体状态')).toBeInTheDocument();
      expect(screen.getByText('检查数量')).toBeInTheDocument();
      expect(screen.getByText('错误数量')).toBeInTheDocument();
      expect(screen.getByText('警告数量')).toBeInTheDocument();
    });
  });

  it('displays passed status with green styling', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Multiple PASSED badges exist (overall status + check entries)
      expect(screen.getAllByText('PASSED').length).toBeGreaterThan(0);
    });
  });

  it('shows warnings section when warnings exist', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      // 警告 appears in summary stats (警告数量) and section header (警告 (1))
      expect(screen.getAllByText(/警告/).length).toBeGreaterThan(0);
      // Warning message appears in both warnings list and check details
      expect(screen.getAllByText('Minor lore inconsistency detected').length).toBeGreaterThan(0);
    });
  });

  it('shows errors section when errors exist', async () => {
    mockGetValidationAudit.mockResolvedValue(mockFailedValidationResponse);

    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-456" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getAllByText(/错误/).length).toBeGreaterThan(0);
      expect(screen.getAllByText('Forbidden information leaked in narration').length).toBeGreaterThan(0);
    });
  });

  it('groups checks by type in collapsible sections', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('行动有效性')).toBeInTheDocument();
      expect(screen.getByText('状态变更')).toBeInTheDocument();
      expect(screen.getByText('设定一致性')).toBeInTheDocument();
    });
  });

  it('displays check details with status badge', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Multiple PASSED and WARNING badges exist across different check entries
      expect(screen.getAllByText('PASSED').length).toBeGreaterThan(0);
      expect(screen.getAllByText('WARNING').length).toBeGreaterThan(0);
    });
  });

  it('shows transaction ID when present', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      // Transaction ID label is in one span, value in another
      expect(screen.getByText(/事务ID/)).toBeInTheDocument();
    });
  });

  it('refreshes data when refresh button clicked', async () => {
    renderWithIntl(<ValidationAuditViewer sessionId="test-session" validationId="val-123" />);

    const loadButton = screen.getByText('加载验证审计数据');
    fireEvent.click(loadButton);

    await waitFor(() => {
      expect(screen.getByText('验证审计')).toBeInTheDocument();
    });

    const refreshButton = screen.getByText('刷新');
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(mockGetValidationAudit).toHaveBeenCalledTimes(2);
    });
  });
});
