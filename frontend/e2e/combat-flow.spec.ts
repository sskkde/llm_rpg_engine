import {test, expect, type Page} from '@playwright/test';

const BACKEND_URL = 'http://127.0.0.1:8000';

async function isBackendAvailable(page: Page): Promise<boolean> {
  try {
    const response = await page.request.get(`${BACKEND_URL}/health`);
    return response.ok();
  } catch {
    return false;
  }
}

async function setupCombatState(page: Page): Promise<{ combatId: string; username: string }> {
  const username = `e2e_combat_${Date.now()}`;
  const password = 'TestPass123!';

  const regRes = await page.request.post(`${BACKEND_URL}/auth/register`, {
    data: { 
      username, 
      email: `${username}@test.com`, 
      password 
    }
  });
  
  if (!regRes.ok()) {
    throw new Error(`Registration failed: ${regRes.status()}`);
  }

  const loginRes = await page.request.post(`${BACKEND_URL}/auth/login`, {
    data: { username, password }
  });
  
  if (!loginRes.ok()) {
    throw new Error(`Login failed: ${loginRes.status()}`);
  }
  
  const { access_token } = await loginRes.json();

  const worldRes = await page.request.get(`${BACKEND_URL}/world/state`);
  
  if (!worldRes.ok()) {
    throw new Error(`Failed to get world state: ${worldRes.status()}`);
  }
  
  const worldData = await worldRes.json();
  const worldId = worldData.world.id;

  const saveRes = await page.request.post(`${BACKEND_URL}/saves`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: { slot_number: 1, name: 'E2E Combat Test Save' }
  });
  
  if (!saveRes.ok()) {
    throw new Error(`Failed to create save slot: ${saveRes.status()}`);
  }
  
  const saveData = await saveRes.json();
  const slotId = saveData.id;

  const manualSaveRes = await page.request.post(`${BACKEND_URL}/saves/manual-save`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: { 
      world_id: worldId,
      save_slot_id: slotId 
    }
  });
  
  if (!manualSaveRes.ok()) {
    throw new Error(`Failed to create manual save: ${manualSaveRes.status()}`);
  }
  
  const manualSaveData = await manualSaveRes.json();
  const sessionId = manualSaveData.session_id;

  const combatRes = await page.request.post(`${BACKEND_URL}/combat/start`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      session_id: sessionId,
      participants: [
        {
          actor_id: 'player-1',
          actor_type: 'player',
          name: 'E2E Hero',
          hp: 100,
          max_hp: 100,
          initiative: 15
        },
        {
          actor_id: 'enemy-1',
          actor_type: 'npc',
          name: 'E2E Enemy',
          hp: 50,
          max_hp: 50,
          initiative: 10
        }
      ]
    }
  });
  
  if (!combatRes.ok()) {
    throw new Error(`Failed to start combat: ${combatRes.status()}`);
  }
  
  const combatData = await combatRes.json();
  
  return { 
    combatId: combatData.combat_id, 
    username 
  };
}

test.describe('Combat Page - Locale Routing', () => {
  test('zh combat-test page redirects to login (protected route)', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    await page.goto('/zh/combat-test');
    await expect(page).toHaveURL(/\/zh\/auth\/login/);
    await expect(page.locator('h1')).toContainText('登录');
  });

  test('en combat-test page redirects to login (protected route)', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    await page.goto('/en/combat-test');
    await expect(page).toHaveURL(/\/en\/auth\/login/);
    await expect(page.locator('h1')).toContainText('Login');
  });
});

test.describe('Combat Flow - API Integration', () => {
  test('full combat flow loads combat panel with participants', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    const { combatId, username } = await setupCombatState(page);
    const password = 'TestPass123!';

    await page.goto('/zh/auth/login');
    await page.fill('[data-testid="username-input"]', username);
    await page.fill('[data-testid="password-input"]', password);
    await page.click('[data-testid="login-submit"]');
    await expect(page).toHaveURL(/\/zh\/game/);

    await page.goto('/zh/combat-test');
    await expect(page.getByRole('heading', { name: 'Combat UI Test' })).toBeVisible();
    await expect(page.getByPlaceholder('Combat ID')).toBeVisible();
    
    const input = page.getByPlaceholder('Combat ID');
    await input.clear();
    await input.fill(combatId);
    await page.click('button:has-text("Load Combat")');
    
    await expect(page.getByRole('heading', { name: '战斗' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('E2E Hero')).toBeVisible();
    await expect(page.getByText('E2E Enemy')).toBeVisible();
    await expect(page.getByText(/第 \d+ 回合/)).toBeVisible();
  });

  test('combat panel shows enemies section', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    const { combatId, username } = await setupCombatState(page);
    const password = 'TestPass123!';

    await page.goto('/zh/auth/login');
    await page.fill('[data-testid="username-input"]', username);
    await page.fill('[data-testid="password-input"]', password);
    await page.click('[data-testid="login-submit"]');
    await expect(page).toHaveURL(/\/zh\/game/);

    await page.goto('/zh/combat-test');
    const input = page.getByPlaceholder('Combat ID');
    await input.clear();
    await input.fill(combatId);
    await page.click('button:has-text("Load Combat")');
    
    await expect(page.getByRole('heading', { name: '战斗' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('敌人')).toBeVisible();
  });

  test('combat panel handles invalid combat ID with error message', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    const username = `e2e_invalid_${Date.now()}`;
    const password = 'TestPass123!';

    await page.request.post(`${BACKEND_URL}/auth/register`, {
      data: { username, email: `${username}@test.com`, password }
    });

    await page.goto('/zh/auth/login');
    await page.fill('[data-testid="username-input"]', username);
    await page.fill('[data-testid="password-input"]', password);
    await page.click('[data-testid="login-submit"]');
    await expect(page).toHaveURL(/\/zh\/game/);

    await page.goto('/zh/combat-test');
    
    const input = page.getByPlaceholder('Combat ID');
    await input.clear();
    await input.fill('invalid-combat-id-12345');
    await page.click('button:has-text("Load Combat")');
    
    await expect(page.getByText(/未找到战斗|加载战斗状态失败/)).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Combat UI - English Locale', () => {
  test('combat page shows English translations', async ({page}) => {
    if (!(await isBackendAvailable(page))) {
      test.skip();
      return;
    }

    const { combatId, username } = await setupCombatState(page);
    const password = 'TestPass123!';

    await page.goto('/en/auth/login');
    await page.fill('[data-testid="username-input"]', username);
    await page.fill('[data-testid="password-input"]', password);
    await page.click('[data-testid="login-submit"]');
    await expect(page).toHaveURL(/\/en\/game/);

    await page.goto('/en/combat-test');
    await expect(page.getByRole('heading', { name: 'Combat UI Test' })).toBeVisible();
    
    const input = page.getByPlaceholder('Combat ID');
    await input.clear();
    await input.fill(combatId);
    await page.click('button:has-text("Load Combat")');
    
    await expect(page.getByRole('heading', { name: 'Combat' })).toBeVisible({ timeout: 10000 });
  });
});
