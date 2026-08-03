// ============================================================================
// PREEMPTIVE WARNING BANNER E2E TEST SUITE — Phase 3.5: Banner Data Rewrite
// ============================================================================
// Beginner Note — What This Test File Does:
//
//     This file verifies the PreemptiveWarningBanner on the POS dashboard
//     after its rewrite from hardcoded disease-wave alerts (probability/
//     volume placeholders) to real /api/v1/health-risk/current scores.
//
//     1. Real-data render:   banner shows disease name, score and confidence.
//     2. Degraded handling:  data_status === "degraded" shows the honest note.
//     3. Drill-down:         "See details" fetches /explain/{id} and shows
//                            the contributing factors.
//     4. Empty state:        /current returning no scores renders NO banner.
//
//     Why we mock network requests:
//         The live database has zero scored rows (health_risk_enabled is off
//         on the seed tenant), so a real-data test would never see the banner.
//         Mocking gives us deterministic coverage of all four branches.
// ============================================================================

import { test, expect } from '@playwright/test';

const BASE_URL: string = 'http://localhost:3002';

// ============================================================================
// MOCK PAYLOADS
// Shapes mirror the backend Pydantic schemas exactly:
//   /current → HealthRiskCurrentResponse { pincode, scores[{id, disease_category,
//              score, confidence, computed_at, data_status}] }
//   /explain → HealthRiskExplainResponse { id, pincode, disease_category,
//              score, confidence, computed_at, contributing_factors }
// ============================================================================

const CURRENT_TWO_DISEASES = {
  pincode: '110001',
  scores: [
    {
      id: 1,
      disease_category: 'DENGUE',
      score: 82.4,
      confidence: 'HIGH',
      computed_at: '2026-08-03T06:00:00Z',
      data_status: 'real_data',
    },
    {
      id: 2,
      disease_category: 'LEPTOSPIROSIS',
      score: 45.1,
      confidence: 'MODERATE',
      computed_at: '2026-08-03T06:00:00Z',
      data_status: 'degraded',
    },
  ],
};

const CURRENT_EMPTY = {
  pincode: '110001',
  scores: [],
};

const EXPLAIN_DENGUE = {
  id: 1,
  pincode: '110001',
  disease_category: 'DENGUE',
  score: 82.4,
  confidence: 'HIGH',
  computed_at: '2026-08-03T06:00:00Z',
  contributing_factors: {
    trend_score: 78,
    humidity_percent: 91,
    rain_mm: 12.5,
    weather_anomaly: 62,
  },
};

// ============================================================================
// SUITE: Preemptive Warning Banner
// ============================================================================

test.describe('Preemptive Warning Banner', () => {

  // ==========================================================================
  // TEST 1: REAL-DATA RENDER
  // The banner shows the disease's real score and confidence from /current —
  // no hardcoded probability/volume placeholders.
  // ==========================================================================

  test('renders real score and confidence for each disease', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: CURRENT_TWO_DISEASES })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    const banner = page.getByTestId('preemptive-warning-banner');
    await expect(banner).toBeVisible();
    await expect(banner.getByText('DENGUE')).toBeVisible();
    await expect(banner.getByText('82.4')).toBeVisible();
    await expect(banner.getByText('Confidence HIGH')).toBeVisible();
    await expect(banner.getByText('LEPTOSPIROSIS')).toBeVisible();
    await expect(banner.getByText('45.1')).toBeVisible();
    await expect(banner.getByText('Confidence MODERATE')).toBeVisible();
  });

  // ==========================================================================
  // TEST 2: DEGRADED DATA NOTE
  // A disease whose data_status is "degraded" shows an honest informational
  // note — not an error state, not a hidden data gap.
  // ==========================================================================

  test('shows the degraded note when data_status is degraded', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: CURRENT_TWO_DISEASES })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    const banner = page.getByTestId('preemptive-warning-banner');
    await expect(banner).toBeVisible();
    await expect(banner.getByText('based on limited recent data')).toBeVisible();
  });

  // ==========================================================================
  // TEST 3: SEE-DETAILS DRILL-DOWN
  // Clicking a disease item fetches /explain/{id} and shows the raw
  // contributing factors behind the score.
  // ==========================================================================

  test('expands to show contributing factors on see-details click', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: CURRENT_TWO_DISEASES })
    );
    await page.route('**/api/v1/health-risk/explain/1', (route) =>
      route.fulfill({ json: EXPLAIN_DENGUE })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    const banner = page.getByTestId('preemptive-warning-banner');
    await expect(banner).toBeVisible();

    await banner.locator('button:has-text("See details")').first().click();

    await expect(banner.getByText('Raw inputs behind this score')).toBeVisible();
    await expect(banner.getByText('Trend signal')).toBeVisible();
    await expect(banner.getByText('78 / 100')).toBeVisible();
    await expect(banner.getByText('Humidity')).toBeVisible();
    await expect(banner.getByText('91%')).toBeVisible();
    await expect(banner.getByText('Rainfall')).toBeVisible();
    await expect(banner.getByText('12.5 mm')).toBeVisible();
    await expect(banner.getByText('Weather anomaly')).toBeVisible();
  });

  // ==========================================================================
  // TEST 4: EMPTY STATE
  // With no scored data (the realistic live-DB state today), the banner
  // renders nothing — no alerts, no banner, no empty shell.
  // ==========================================================================

  test('renders nothing when /current returns empty scores', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: CURRENT_EMPTY })
    );

    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

    await expect(page.getByTestId('preemptive-warning-banner')).toHaveCount(0);
    await expect(page.getByText('Active Health Risk Signals')).toHaveCount(0);
  });
});
