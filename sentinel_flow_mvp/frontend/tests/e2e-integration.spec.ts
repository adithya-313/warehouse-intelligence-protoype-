// ============================================================================
// E2E INTEGRATION TEST SUITE — Phase 10: Clinical Copilot + Auto-PO Pipeline
// ============================================================================
// Beginner Note — What This Test File Does:
//
//     This file simulates a pharmacist using the Sentinel-Flow POS system.
//     We have three test scenarios:
//
//     1. Clinical Safety Breaker:
//        The pharmacist asks a broad/unsafe question to the AI Clinical Copilot.
//        We expect the system to REJECT the answer because the confidence is
//        too low (below the 85% safety threshold).
//
//     2. In-Network Grounded Generation:
//        The pharmacist asks a common Indian pharmacy question ("is dolo safe?").
//        The RAG pipeline should find the matching clinical knowledge and return
//        it with a verified source citation (DOLO-650).
//
//     3. Automated Purchase Order Pipeline:
//        We simulate a disease wave alert by intercepting the backend network
//        call and returning a FAKE alert. Then we watch the pharmacist click
//        "1-Click Approve PO" and verify the success state.
//
//     Why we mock network requests in Test 3:
//         Disease waves depend on real weather/trend data from external APIs.
//         We cannot guarantee those APIs return data during a test run.
//         By mocking, we create a deterministic test that always passes
//         regardless of external conditions.
// ============================================================================

import { test, expect, Page, Route } from '@playwright/test';

// ============================================================================
// TEST BASE URL
// The Playwright config (playwright.config.ts) sets baseURL to
// http://localhost:3002. All page.goto() calls use this as the root.
// ============================================================================

const BASE_URL: string = 'http://localhost:3002';

// ============================================================================
// SUITE: Clinical Copilot Safety & RAG Pipeline
// ============================================================================

test.describe('Clinical Copilot Safety & RAG Pipeline', () => {

  // ==========================================================================
  // TEST 1: CLINICAL SAFETY BREAKER
  // ==========================================================================
  // Beginner Note:
  //   The Clinical Copilot has a hard-coded safety threshold (85% confidence).
  //   When a pharmacist asks a very broad question like "What is the medicine
  //   for chickenpox?" the AI cannot find a single high-confidence match in
  //   the knowledge base. Instead of guessing (which could harm the patient),
  //   the system returns a safety warning.
  //
  //   We verify this by:
  //     1. Opening the Copilot panel.
  //     2. Typing a broad, unsafe query.
  //     3. Pressing Enter to submit.
  //     4. Checking that the last AI response contains "CLINICAL SAFETY BREAKER".
  // ==========================================================================

  test('Test Case 1: Clinical Safety Breaker rejects broad / unsafe queries', async ({ page }) => {
    // Step 1: Navigate to the POS Dashboard
    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'networkidle' });

    // Step 2: Open the Clinical Copilot panel.
    // The Copilot is hidden by default. We click the "Clinical Copilot" button
    // in the header (identified by the text inside the motion.button).
    const copilotButton = page.locator('button:has-text("Clinical Copilot")');
    await copilotButton.click();

    // Step 3: Wait for the Copilot panel to slide in.
    // The panel contains an input field with placeholder "Verify clinical safety..."
    await page.waitForSelector('input[placeholder="Verify clinical safety..."]', { timeout: 5000 });

    // Step 4: Type a broad / unsafe query.
    // "What is the medicine for chickenpox?" is too broad — there is no single
    // high-confidence match in the knowledge base for this question.
    const aiInput = page.locator('input[placeholder="Verify clinical safety..."]');
    await aiInput.fill('What is the medicine for chickenpox?');

    // Step 5: Press Enter to submit the query.
    await aiInput.press('Enter');

    // Step 6: Wait for the AI response to appear.
    // AI messages are rendered inside <p> tags within a div that has the
    // class "mr-auto". We wait for the last such <p> to contain the safety
    // breaker message.
    // Allow time for the API call + response rendering.
    await page.waitForTimeout(2000);

    // Step 7: Assert that the system rejected the query.
    // The Semantic Search engine should return a safety_warning when no
    // results pass the 85% confidence threshold. The AI response will
    // contain "CLINICAL SAFETY BREAKER" in the message.
    const aiResponseContainer = page.locator('.mr-auto p').last();
    await expect(aiResponseContainer).toContainText('CLINICAL SAFETY BREAKER', { timeout: 10000 });

    console.log('✓ TEST 1 PASSED: Clinical Safety Breaker correctly rejected unsafe query.');
  });

  // ==========================================================================
  // TEST 2: IN-NETWORK GROUNDED GENERATION
  // ==========================================================================
  // Beginner Note:
  //   "is dolo safe?" is a known query that matches the clinical knowledge
  //   base entry for DOLO-650 (Paracetamol). The RAG pipeline should find
  //   this match with high confidence (above 85%) and return a grounded
  //   answer with a verified source citation.
  //
  //   We verify this by:
  //     1. Re-opening the Copilot panel.
  //     2. Typing "is dolo safe?".
  //     3. Checking that the AI response includes "Verified Sources" and
  //        the DOLO-650 SKU ID.
  // ==========================================================================

  test('Test Case 2: In-Network Grounded Generation returns verified source', async ({ page }) => {
    await page.goto(`${BASE_URL}/pos`, { waitUntil: 'networkidle' });

    // Open the Copilot panel
    const copilotButton = page.locator('button:has-text("Clinical Copilot")');
    await copilotButton.click();

    await page.waitForSelector('input[placeholder="Verify clinical safety..."]', { timeout: 5000 });

    // Type a safe, in-network query
    const aiInput = page.locator('input[placeholder="Verify clinical safety..."]');
    await aiInput.fill('is dolo safe?');
    await aiInput.press('Enter');

    // Wait for the response to render
    await page.waitForTimeout(3000);

    // Assert that the AI response contains a verified source citation.
    // The CopilotPanel renders sources inside a div with a "Verified Sources"
    // header and the SKU ID (DOLO-650) in the source content.
    const aiResponseContainer = page.locator('.mr-auto p').last();
    await expect(aiResponseContainer).toContainText('DOLO-650', { timeout: 10000 });

    console.log('✓ TEST 2 PASSED: In-Network Grounded Generation returned DOLO-650 source.');
  });

  // ==========================================================================
  // SUITE: Automated Purchase Order Pipeline
  // ==========================================================================

  test.describe('Automated Purchase Order Pipeline', () => {

    // ========================================================================
    // TEST 3: HEALTH RISK BANNER WITH DETERMINISTIC MOCKING
    // ========================================================================
    // Beginner Note:
    //   The Preemptive Warning Banner at the top of the POS dashboard shows
    //   the latest health risk scores for this pharmacy, fetched from
    //   /api/v1/health-risk/current.
    //
    //   Problem: Real risk scores come from the background Celery scoring job,
    //   which needs live weather/trend data. During testing the /current
    //   endpoint may return an empty score list, which means the banner
    //   would not appear.
    //
    //   Solution: We use page.route() to INTERCEPT the network request and
    //   return a FAKE /current payload (one real_data disease and one
    //   degraded disease). This makes the test deterministic — it always
    //   passes regardless of external conditions.
    //
    //   The "1-Click Approve PO" action was removed from this banner (its
    //   probability/volume numbers were hardcoded placeholders) — the new
    //   banner shows the real score + confidence and an explain drill-down.
    // ========================================================================

    test('Test Case 3: Health risk banner renders real scores with deterministic mocking', async ({ page }) => {
      // =====================================================================
      // STEP 1: Mock the Health Risk Current API
      // =====================================================================
      // We intercept every request to /api/v1/health-risk/current and return
      // two pre-baked disease scores: DENGUE (real data, high score) and
      // LEPTOSPIROSIS (degraded — the evidence base has gone quiet).
      // =====================================================================
      await page.route('**/api/v1/health-risk/current', async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
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
          }),
        });
      });

      // =====================================================================
      // STEP 2: Mock the Explain API for the drill-down
      // =====================================================================
      await page.route('**/api/v1/health-risk/explain/1', async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
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
          }),
        });
      });

      // =====================================================================
      // STEP 3: Navigate to the POS Dashboard
      // =====================================================================
      // The PreemptiveWarningBanner is rendered inside the POS dashboard
      // page. It fetches /current on mount via useEffect().
      await page.goto(`${BASE_URL}/pos`, { waitUntil: 'load' });

      // =====================================================================
      // STEP 4: Wait for the Mock Risk Banner to Render
      // =====================================================================
      // Both diseases, their scores and confidence levels appear in the
      // banner, and the degraded disease shows its honest note.
      await page.waitForSelector('text=DENGUE', { timeout: 5000 });
      await expect(page.getByText('82.4')).toBeVisible();
      await expect(page.getByText('Confidence HIGH')).toBeVisible();
      await expect(page.getByText('based on limited recent data')).toBeVisible();

      // =====================================================================
      // STEP 5: Expand the "See details" drill-down
      // =====================================================================
      // Clicking a disease item fetches /explain/1 and shows the raw
      // contributing factors behind the score.
      const seeDetailsButton = page.locator('button:has-text("See details")').first();
      await seeDetailsButton.click();

      // =====================================================================
      // STEP 6: Wait for the Explain Data to Render
      // =====================================================================
      await page.waitForSelector('text=Raw inputs behind this score', { timeout: 5000 });

      // =====================================================================
      // STEP 7: Assert Success State
      // =====================================================================
      await expect(page.getByText('Trend signal')).toBeVisible();
      await expect(page.getByText('78 / 100')).toBeVisible();

      console.log('✓ TEST 3 PASSED: Health risk banner with deterministic mocking succeeded.');
    });

  });

});
