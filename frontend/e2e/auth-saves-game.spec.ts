import {test, expect, type Page} from '@playwright/test';

test.describe('Locale Routing', () => {
  test('root redirects to Chinese default', async ({page}) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/zh/);
  });

  test('Chinese login page renders localized text', async ({page}) => {
    await page.goto('/zh/auth/login');
    await expect(page.locator('h1')).toContainText('登录');
  });

  test('English login page renders localized text', async ({page}) => {
    await page.goto('/en/auth/login');
    await expect(page.locator('h1')).toContainText('Login');
  });

  test('invalid locale returns 404', async ({page}) => {
    const response = await page.goto('/fr/auth/login');
    expect(response?.status()).toBe(404);
  });
});

test.describe('Language Switcher', () => {
  test('switch login page from Chinese to English', async ({page}) => {
    await page.goto('/zh/auth/login');
    await page.click('[data-testid="language-switcher-en"]');
    await expect(page).toHaveURL(/\/en\/auth\/login/);
    await expect(page.locator('h1')).toContainText('Login');
  });

  test('switch login page from English to Chinese', async ({page}) => {
    await page.goto('/en/auth/login');
    await page.click('[data-testid="language-switcher-zh"]');
    await expect(page).toHaveURL(/\/zh\/auth\/login/);
    await expect(page.locator('h1')).toContainText('登录');
  });
});

async function registerViaUi(page: Page, username: string, password: string) {
  await page.goto('/zh/auth/register');
  await page.fill('[data-testid="register-username-input"]', username);
  await page.fill('[data-testid="register-password-input"]', password);
  await page.click('[data-testid="register-submit"]');
  await expect(page).toHaveURL(/\/zh\/auth\/login\?registered=1/);
  await expect(page.locator('[data-testid="registration-success"]')).toBeVisible();
}

async function loginViaUi(page: Page, username: string, password: string) {
  await page.goto('/zh/auth/login');
  await page.fill('[data-testid="username-input"]', username);
  await page.fill('[data-testid="password-input"]', password);
  await page.click('[data-testid="login-submit"]');
  await expect(page).toHaveURL(/\/zh\/game/);
}

test.describe('Authentication Flow', () => {
  test('register redirects to login with success message', async ({page}) => {
    const username = `e2e_user_${Date.now()}`;

    await registerViaUi(page, username, 'TestPass123!');
  });

  test('login redirects to game entry', async ({page}) => {
    const username = `e2e_login_${Date.now()}`;
    const password = 'TestPass123!';

    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
  });

  test('invalid login shows error', async ({page}) => {
    await page.goto('/zh/auth/login');
    await page.fill('[data-testid="username-input"]', 'nonexistent');
    await page.fill('[data-testid="password-input"]', 'wrongpass');
    await page.click('[data-testid="login-submit"]');

    await expect(page.locator('[data-testid="login-error"]')).toBeVisible({timeout: 5000});
  });
});

test.describe('Saves Flow', () => {
  test('creates a save after login', async ({page}) => {
    const username = `e2e_save_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'E2E 存档');
    await page.click('button:has-text("创建存档")');

    await expect(page.locator('text=E2E 存档')).toBeVisible({timeout: 10000});
  });
});

test.describe('Game Flow', () => {
  test('starts a new game from a save slot', async ({page}) => {
    const username = `e2e_game_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'E2E 游戏存档');
    await page.click('button:has-text("创建存档")');
    await page.click('text=E2E 游戏存档');
    await expect(page).toHaveURL(/\/zh\/saves\//);

    await page.click('button:has-text("开始新游戏")');

    await expect(page).toHaveURL(/\/zh\/game\//, {timeout: 15000});
    await expect(page.getByRole('heading', {name: '冒险', exact: true})).toBeVisible();
  });
});

test.describe('Admin Access', () => {
  test('admin page shows login required', async ({page}) => {
    await page.goto('/zh/admin');
    await expect(page.getByRole('heading', {name: '需要登录'})).toBeVisible({timeout: 5000});
  });
});
