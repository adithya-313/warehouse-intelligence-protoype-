// ============================================================================
// HOW THIS WORKS MODAL E2E TEST SUITE — Phase 4: Radar explainer modal
// ============================================================================
// Beginner Note — What This Test File Does:
//
//     This file verifies the "How this works" modal on /health-risk-radar:
//
//     1. Closed by default:   the trigger link is visible but the modal's
//                             content is NOT in the DOM at all (the modal
//                             unmounts entirely while closed — nothing hidden
//                             by CSS, nothing matching getByText).
//     2. Opens on click:      clicking the trigger shows the modal with all
//                             four content sections: data sources, the
//                             limited-data note, the risk-tier caveat, and
//                             the known limitations.
//     3. Closes on request:   the X button (and Escape) close it, and the
//                             content leaves the DOM again.
//
//     Why we mock network requests:
//         Same pattern as health-risk-radar.spec.ts — the live database has
//         zero scored rows, so we mock /current and /history with empty
//         payloads for a deterministic page render.
// ============================================================================

import { test, expect } from '@playwright/test';

const BASE_URL: string = 'http://localhost:3002';

const EMPTY_CURRENT = {
  pincode: '110001',
  scores: [],
};

const EMPTY_HISTORY = {
  pincode: '110001',
  days: 30,
  scores: [],
};

// ============================================================================
// SUITE: How This Works Modal
// ============================================================================

test.describe('How This Works Modal', () => {

  async function openRadar(page: import('@playwright/test').Page) {
    await page.route('**/api/v1/health-risk/current', (route) =>
      route.fulfill({ json: EMPTY_CURRENT })
    );
    await page.route('**/api/v1/health-risk/history*', (route) =>
      route.fulfill({ json: EMPTY_HISTORY })
    );
    await page.goto(`${BASE_URL}/health-risk-radar`, { waitUntil: 'load' });
  }

  // ==========================================================================
  // TEST 1: CLOSED BY DEFAULT
  // The trigger link is visible in the header, but the modal's copy does not
  // exist anywhere in the DOM while closed — it unmounts rather than being
  // hidden by CSS, so no stale text can collide with other assertions.
  // ==========================================================================

  test('is closed by default with no modal content in the DOM', async ({ page }) => {
    await openRadar(page);

    await expect(page.getByRole('button', { name: 'How this works' })).toBeVisible();

    // Section headings must be absent while the modal is closed.
    await expect(page.getByText('Where this comes from')).toHaveCount(0);
    await expect(page.getByText('Known limitations')).toHaveCount(0);
  });

  // ==========================================================================
  // TEST 2: OPENS ON TRIGGER CLICK WITH ALL KEY CLAIMS
  // Every claim asserted here is sourced from documented codebase facts
  // (scorer docstring, backtest doc, risk_tier caveat) — the test guards
  // against the copy being softened or removed later.
  // ==========================================================================

  test('opens on trigger click and shows all four sections', async ({ page }) => {
    await openRadar(page);

    await page.getByRole('button', { name: 'How this works' }).click();

    // Section 1 — the two real data sources.
    await expect(page.getByText('Where this comes from')).toBeVisible();
    await expect(page.getByText('Search trends', { exact: true })).toBeVisible();
    await expect(page.getByText('Weather conditions', { exact: false })).toBeVisible();
    await expect(page.getByText('two real signals for your area')).toBeVisible();

    // Section 2 — what the degraded-data pill means (substance, not the
    // verbatim pill phrase — that exact phrase must never exist twice).
    await expect(page.getByText('What the limited-data note means')).toBeVisible();
    await expect(page.getByText('thin evidence', { exact: false })).toBeVisible();

    // Section 3 — the risk-tier honesty caveat.
    await expect(page.getByText('About the risk levels')).toBeVisible();
    await expect(page.getByText('not a certified risk assessment')).toBeVisible();
    await expect(page.getByText('boundaries', { exact: false })).toBeVisible();

    // Section 4 — known limitations.
    await expect(page.getByText('Known limitations')).toBeVisible();
    await expect(page.getByText('chosen deliberately, not learned from data')).toBeVisible();
    await expect(page.getByText('Monsoon season', { exact: false })).toBeVisible();
    await expect(page.getByText('false alarms', { exact: false })).toBeVisible();
    await expect(page.getByText('early-stage signal, not a diagnosis')).toBeVisible();
  });

  // ==========================================================================
  // TEST 3: CLOSES VIA THE X BUTTON
  // Closing removes the modal from the DOM entirely, restoring the
  // closed-by-default state.
  // ==========================================================================

  test('closes via the X button and unmounts its content', async ({ page }) => {
    await openRadar(page);

    await page.getByRole('button', { name: 'How this works' }).click();
    await expect(page.getByText('Where this comes from')).toBeVisible();

    await page.getByRole('button', { name: 'Close' }).click();

    await expect(page.getByText('Where this comes from')).toHaveCount(0);
    await expect(page.getByText('Known limitations')).toHaveCount(0);
  });

  // ==========================================================================
  // TEST 4: CLOSES VIA ESCAPE
  // The Escape key closes the modal, matching InventoryTriageModal behaviour.
  // ==========================================================================

  test('closes via the Escape key', async ({ page }) => {
    await openRadar(page);

    await page.getByRole('button', { name: 'How this works' }).click();
    await expect(page.getByText('Where this comes from')).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(page.getByText('Where this comes from')).toHaveCount(0);
  });
});
