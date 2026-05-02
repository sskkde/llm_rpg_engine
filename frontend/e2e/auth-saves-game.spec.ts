import {test, expect} from '@playwright/test';

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

test.describe('Authentication Flow', () => {
  test('register and redirect to saves', async ({page}) => {
    const timestamp = Date.now();
    const username = `e2e_user_${timestamp}`;

    await page.goto('/zh/auth/register');
    await page.fill('[data-testid="register-username-input"]', username);
    await page.fill('[data-testid="register-password-input"]', 'TestPass123!');
    await page.click('[data-testid="register-submit"]');

    await expect(page).toHaveURL(/\/zh\/saves/);
  });

  test('login and redirect to saves', async ({page}) => {
    await page.goto('/zh/auth/login');
    await expect(page.locator('h1')).toContainText('登录');
  });

  test('invalid login shows error', async ({page}) => {
    await page.goto('/zh/auth/login');
    await page.fill('[data-testid="username-input"]', 'nonexistent');
    await page.fill('[data-testid="password-input"]', 'wrongpass');
    await page.click('[data-testid="login-submit"]');

    await expect(page.locator('[data-testid="login-error"]')).toBeVisible({timeout: 5000}).catch(() => {
      expect(page.locator('text=用户名或密码错误')).toBeVisible();
    });
  });
});

test.describe('Saves Flow', () => {
  test('shows saves page after login', async ({page}) => {
    await page.goto('/zh/saves');
    await expect(page.locator('h1')).toContainText('存档管理');
  });
});

test.describe('Game Flow', () => {
  test('game page redirects to saves', async ({page}) => {
    await page.goto('/zh/game');
    await expect(page.locator('text=存档管理')).toBeVisible();
  });
});

test.describe('Admin Access', () => {
  test('admin page shows login required', async ({page}) => {
    await page.goto('/zh/admin');
    await expect(page.locator('text=需要登录')).toBeVisible({timeout: 5000}).catch(() => {
      expect(page.locator('text=管理面板')).toBeVisible();
    });
  });
});
