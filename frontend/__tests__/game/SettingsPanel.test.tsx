import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { SettingsPanel } from '@/components/game/SettingsPanel';

describe('SettingsPanel', () => {
  const sessionId = 'test-session-12345678';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders settings button', () => {
    renderWithIntl(<SettingsPanel sessionId={sessionId} />);
    
    const settingsButton = screen.getByRole('button', { name: '设置' });
    expect(settingsButton).toBeInTheDocument();
  });

  it('opens modal on gear click', async () => {
    renderWithIntl(<SettingsPanel sessionId={sessionId} />);
    
    const settingsButton = screen.getByRole('button', { name: '设置' });
    fireEvent.click(settingsButton);
    
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    
    expect(screen.getByText('声音')).toBeInTheDocument();
    expect(screen.getByText('语言')).toBeInTheDocument();
    expect(screen.getByText('显示')).toBeInTheDocument();
  });

  it('shows session ID in modal', async () => {
    renderWithIntl(<SettingsPanel sessionId={sessionId} />);
    
    const settingsButton = screen.getByRole('button', { name: '设置' });
    fireEvent.click(settingsButton);
    
    await waitFor(() => {
      expect(screen.getByText('会话ID')).toBeInTheDocument();
    });
    
    expect(screen.getByText('test-ses...')).toBeInTheDocument();
  });

  it('shows language info in modal', async () => {
    renderWithIntl(<SettingsPanel sessionId={sessionId} />);
    
    const settingsButton = screen.getByRole('button', { name: '设置' });
    fireEvent.click(settingsButton);
    
    await waitFor(() => {
      expect(screen.getByText('中文')).toBeInTheDocument();
    });
  });

  it('close modal works', async () => {
    renderWithIntl(<SettingsPanel sessionId={sessionId} />);
    
    const settingsButton = screen.getByRole('button', { name: '设置' });
    fireEvent.click(settingsButton);
    
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    
    const closeButton = screen.getByRole('button', { name: '关闭弹窗' });
    fireEvent.click(closeButton);
    
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
