// ============================================================================
// HEALTH RISK RADAR E2E TEST SUITE — Phase 2: Frontend Health Risk Radar
// ============================================================================
// Beginner Note — What This Test File Does:
//
//     This file verifies the /health-risk-radar page in two states:
//
//     1. Empty state:
//        The seed tenant (PHARM-001) has health_risk_enabled=False and the
//        health_risk_scores table is empty in the live DB. We mock both
//        endpoints to return empty payloads and verify the page shows its
//        honest empty states instead of a blank page or an endless spinner.
//
//     2. Populated state:
//        We mock /current, /history and /explain with realistic payloads and
//        verify the trend graphs render and clicking a disease card fetches
//        and displays the contributing factors breakdown.
//
//     Why we mock network requests:
//         The live database has zero scored rows, so a real-data test would
//         always render the empty state. Mocking gives us deterministic
//         coverage of both the empty and populated branches.
// ============================================================================

import { test, expect, Page } from '@playwright/test';

// ============================================================================
// TEST BASE URL
// The Playwright config (playwright.config.ts) sets baseURL to
// http://localhost:3002. All page.goto() calls use this as the root.
// ============================================================================

const BASE_URL: string = 'http://localhost:3002';

// ============================================================================
// MOCK PAYLOADS
// Shapes mirror the backend Pydantic schemas exactly:
//   /current → HealthRiskCurrentResponse { pincode, scores[{id, disease_category,
//              score, confidence, computed_at, data_status}] }
//   /history → HealthRiskHistoryResponse  { pincode, days, scores[{id,
//              disease_category, score, confidence, computed_at}] }
//   /explain → HealthRiskExplainResponse  { id, pincode, disease_category,
//              score, confidence, computed_at, contributing_factors }
// ============================================================================

const EMPTY_CURRENT = {
  pincode: '110001',
  scores: [],
};

const EMPTY_HISTORY = {
  pincode: '110001',
  days: 30,
  scores: [],
};

const POPULATED_CURRENT = {
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

const POPULATED_HISTORY = {
  pincode: '110001',
  days: 30,
  scores: [
    { id: 101, disease_category: 'DENGUE', score: 60.0, confidence: 'MODERATE', computed_at: '2026-07-20T06:00:00Z' },
    { id: 102, disease_category: 'DENGUE', score: 71.5, confidence: 'HIGH', computed_at: '2026-07-27T06:00:00Z' },
    { id: 103, disease_category: 'DENGUE', score: 82.4, confidence: 'HIGH', computed_at: '2026-08-03T06:00:00Z' },
    { id: 201, disease_category: 'LEPTOSPIROSIS', score: 38.0, confidence: 'LOW', computed_at: '2026-07-20T06:00:00Z' },
    { id: 202, disease_category: 'LEPTOSPIROSIS', score: 45.1, confidence: 'MODERATE', computed_at: '2026-08-03T06:00:00Z' },
  ],
};

const POPULATED_EXPLAIN = {
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
// SUITE: Health Risk Radar
// ============================================================================

test.describe('Health Risk Radar', () => {

  // ==========================================================================
  // TEST 1: EMPTY STATE
  // The realistic state today: /current returns no diseases and /history
  // returns no rows. The page must show honest empty states — not a blank
  // page, not an endless spinner, not a misleading flat/zero trend line.
  // ==========================================================================

  test('renders honest empty states when there is no scored data', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: EMPTY_CURRENT })
    );
    await page.route('**/api/v1/health-risk/history*', (route) =>
      route.fulfill({ json: EMPTY_HISTORY })
    );

    await page.goto(`${BASE_URL}/health-risk-radar`, { waitUntil: 'load' });

    // Top-level empty state for the current signal breakdown.
    await expect(page.getByText('No current risk signals yet')).toBeVisible();

    // Honest empty state for the trend section — no fabricated data points.
    await expect(page.getByText('No historical data yet')).toBeVisible();
    await expect(page.getByText('Check back once scoring has run')).toBeVisible();
  });

  // ==========================================================================
  // TEST 2: POPULATED STATE
  // With mocked data, both trend graphs must render and clicking a disease
  // card must fetch /explain/{id} and display the contributing factors.
  // ==========================================================================

  test('renders trend graphs and shows explain breakdown on card click', async ({ page }) => {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: POPULATED_CURRENT })
    );
    await page.route('**/api/v1/health-risk/history*', (route) =>
      route.fulfill({ json: POPULATED_HISTORY })
    );
    await page.route('**/api/v1/health-risk/explain/1', (route) =>
      route.fulfill({ json: POPULATED_EXPLAIN })
    );

    await page.goto(`${BASE_URL}/health-risk-radar`, { waitUntil: 'load' });

    // Current signal breakdown shows both diseases and their scores.
    await expect(page.getByRole('button', { name: /DENGUE/ })).toBeVisible();
    await expect(page.getByText('82.4')).toBeVisible();
    await expect(page.getByRole('button', { name: /LEPTOSPIROSIS/ })).toBeVisible();

    // The degraded disease shows the informational note, not an error.
    await expect(page.getByText('based on limited recent data')).toBeVisible();

    // Trend section renders one AreaChart (an <svg>) per disease.
    await expect(page.getByText('30-day trend')).toBeVisible();
    await expect(page.getByText('last 30 days').first()).toBeVisible();
    const chartCount = await page.locator('svg').count();
    expect(chartCount).toBeGreaterThanOrEqual(2);

    // Clicking the DENGUE card fetches /explain/1 and shows the raw inputs.
    await page.locator('button:has-text("View signal breakdown")').first().click();
    await expect(page.getByText('Raw inputs behind this score')).toBeVisible();
    await expect(page.getByText('Trend signal')).toBeVisible();
    await expect(page.getByText('78 / 100')).toBeVisible();
    await expect(page.getByText('Humidity')).toBeVisible();
    await expect(page.getByText('91%')).toBeVisible();
    await expect(page.getByText('Rainfall')).toBeVisible();
    await expect(page.getByText('12.5 mm')).toBeVisible();
    await expect(page.getByText('Weather anomaly')).toBeVisible();
  });
});
