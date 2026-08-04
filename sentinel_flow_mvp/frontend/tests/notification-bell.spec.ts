// ============================================================================
// NOTIFICATION BELL E2E TEST SUITE — Phase 3.4: Bell styling + mark-read + deep-link
// ============================================================================
// Beginner Note — What This Test File Does:
//
//     This file verifies the NotificationBell on the POS dashboard after its
//     upgrade from generic red text to per-disease icon/color styling with
//     click-to-deep-link behaviour:
//
//     1. Per-disease styling:  a DENGUE-linked alert shows the Bug icon, a
//                              SYSTEM alert falls back to the neutral Bell icon.
//     2. Click deep-link:      clicking an alert marks it read (PATCH) and
//                              navigates to /health-risk-radar?disease=...
//     3. Unread dot:           the red ping dot appears only while unread
//                              alerts exist.
//
//     Why we mock network requests:
//         The live database has zero notifications (and zero risk scores), so
//         real-data tests would never see the bell's contents. Mocking gives
//         deterministic coverage of all branches.
// ============================================================================

import { test, expect } from '@playwright/test';

const BASE_URL: string = 'http://localhost:3002';

// ============================================================================
// MOCK PAYLOADS
// Shapes mirror the backend NotificationResponse schema exactly:
//   { id, title, message, alert_type, health_risk_score_id?, disease_category?,
//     is_read, created_at }
// ============================================================================

const NOTIFICATIONS_MIXED = [
  {
    id: 11,
    title: 'Disease Wave: PARA-001',
    message: 'High health risk score (85.0) for dengue. Preemptive stock recommended.',
    alert_type: 'DISEASE_WAVE',
    health_risk_score_id: 100,
    disease_category: 'dengue',
    is_read: false,
    created_at: '2026-08-04T06:00:00Z',
  },
  {
    id: 12,
    title: 'System maintenance',
    message: 'Scheduled maintenance at 02:00.',
    alert_type: 'SYSTEM',
    health_risk_score_id: null,
    disease_category: null,
    is_read: true,
    created_at: '2026-08-04T05:00:00Z',
  },
];

const NOTIFICATIONS_ALL_READ = NOTIFICATIONS_MIXED.map((n) => ({ ...n, is_read: true }));

// ============================================================================
// SUITE: Notification Bell
// ============================================================================

test.describe('Notification Bell', () => {

  // ==========================================================================
  // TEST 1: PER-DISEASE STYLING
  // Each notification renders the icon/color for its disease (Bug for dengue);
  // alerts without a disease_category (SYSTEM) get the neutral Bell fallback.
  // ==========================================================================

  test('renders per-disease icon styling with neutral fallback', async ({ page }) => {
    await page.route('**/api/v1/notifications', (route) =>
      route.fulfill({ json: NOTIFICATIONS_MIXED })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    await page.getByTestId('notification-bell').click();

    const items = page.getByTestId('notification-item');
    await expect(items).toHaveCount(2);

    // Dengue-linked alert → Bug icon; title and message visible.
    await expect(items.first().locator('svg.lucide-bug')).toBeVisible();
    await expect(items.first().getByText('Disease Wave: PARA-001')).toBeVisible();
    await expect(items.first().getByText('DISEASE_WAVE', { exact: true })).toBeVisible();

    // SYSTEM alert (no disease_category) → neutral Bell fallback icon.
    await expect(items.nth(1).locator('svg.lucide-bell')).toBeVisible();
    await expect(items.nth(1).getByText('System maintenance')).toBeVisible();
    await expect(items.nth(1).getByText('SYSTEM', { exact: true })).toBeVisible();
  });

  // ==========================================================================
  // TEST 2: CLICK MARKS READ + NAVIGATES WITH DISEASE PARAM
  // Clicking an alert fires the PATCH mark-as-read call and navigates to
  // /health-risk-radar?disease=<disease> so the Radar page can pre-select it.
  // ==========================================================================

  test('clicking an alert marks it read and deep-links to the radar page', async ({ page }) => {
    await page.route('**/api/v1/notifications', (route) =>
      route.fulfill({ json: NOTIFICATIONS_MIXED })
    );
    const patchPromise = page.waitForRequest('**/api/v1/notifications/11/read');
    await page.route('**/api/v1/notifications/11/read', (route) =>
      route.fulfill({ json: { status: 'success' } })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    await page.getByTestId('notification-bell').click();
    await page.getByTestId('notification-item').first().click();

    await expect(page).toHaveURL(/\/health-risk-radar\?disease=dengue/);
    await patchPromise;
  });

  // ==========================================================================
  // TEST 3: UNREAD DOT PRESENT WITH UNREAD ITEMS
  // ==========================================================================

  test('shows the unread dot when an unread alert exists', async ({ page }) => {
    await page.route('**/api/v1/notifications', (route) =>
      route.fulfill({ json: NOTIFICATIONS_MIXED })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    await expect(page.getByTestId('notification-unread-dot')).toBeVisible();
  });

  // ==========================================================================
  // TEST 4: NO DOT WHEN ALL READ
  // ==========================================================================

  test('hides the unread dot when all alerts are read', async ({ page }) => {
    await page.route('**/api/v1/notifications', (route) =>
      route.fulfill({ json: NOTIFICATIONS_ALL_READ })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    await expect(page.getByTestId('notification-unread-dot')).toHaveCount(0);
  });
});
