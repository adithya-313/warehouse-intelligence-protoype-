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
    // TEST 3: AUTOMATED PURCHASE ORDER PIPELINE (Deterministic Mocking)
    // ========================================================================
    // Beginner Note:
    //   The Preemptive Warning Banner at the top of the POS dashboard shows
    //   disease wave alerts. These alerts are fetched from the backend API
    //   at /api/v1/procurement/disease-wave-alerts.
    //
    //   Problem: Disease waves depend on real-time weather and search trend
    //   data. The backend may return ZERO alerts during testing, which means
    //   the banner would not appear and we could not test the "1-Click Approve PO"
    //   button.
    //
    //   Solution: We use page.route() to INTERCEPT the network request and
    //   return a FAKE alert response. This makes the test deterministic —
    //   it always passes regardless of external conditions.
    //
    //   We also mock the POST /api/v1/procurement/auto-po endpoint so that
    //   clicking "1-Click Approve PO" succeeds and we can verify the UI
    //   transitions to the success state.
    // ========================================================================

    test('Test Case 3: 1-Click Approve PO with deterministic mocking', async ({ page }) => {
      // =====================================================================
      // STEP 1: Mock the Disease Wave Alert API
      // =====================================================================
      // We intercept EVERY request to the disease-wave-alerts endpoint and
      // return a pre-baked JSON response.
      //
      // The mock alert says that "Paracetamol 650mg" (SKU: DOLO-650) has an
      // 85% probability of being needed soon, with an expected volume of
      // 500 units. We recommend supplier "SUPP-001" (MediCorp).
      //
      // We include 'alert_type: "DISEASE_WAVE"' because the
      // PreemptiveWarningBanner component filters alerts by this field.
      // =====================================================================
      await page.route('**/api/v1/procurement/disease-wave-alerts', async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              sku_id: 'DOLO-650',
              sku_name: 'Paracetamol 650mg',
              probability_score: 0.85,
              expected_volume: 500,
              recommended_supplier_id: 'SUPP-001',
              warning_message: 'Dengue season projected — DOLO-650 demand may spike.',
              alert_type: 'DISEASE_WAVE',
              title: 'Disease Wave Detected',
            },
          ]),
        });
      });

      // =====================================================================
      // STEP 2: Mock the Auto-PO Creation API
      // =====================================================================
      // When the pharmacist clicks "1-Click Approve PO", the frontend sends
      // a POST request to /api/v1/procurement/auto-po with the SKU, supplier,
      // and quantity. We simulate a successful response with a fake PO ID.
      // =====================================================================
      await page.route('**/api/v1/procurement/auto-po', async (route: Route) => {
        // Only intercept POST requests (the auto-po creation call)
        if (route.request().method() === 'POST') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              po_id: 'PO-MOCK-001',
              status: 'PENDING',
              message: 'Purchase Order routed successfully.',
            }),
          });
        } else {
          // Let other methods (GET, etc.) pass through normally
          await route.continue();
        }
      });

      // =====================================================================
      // STEP 3: Navigate to the POS Dashboard
      // =====================================================================
      // The PreemptiveWarningBanner is rendered inside the POS dashboard
      // page. It fetches alerts on mount via useEffect().
      await page.goto(`${BASE_URL}/pos`, { waitUntil: 'networkidle' });

      // =====================================================================
      // STEP 4: Wait for the Mock Alert Banner to Render
      // =====================================================================
      // We wait for the disease wave alert text to appear on screen.
      // The banner shows the warning message we provided in the mock.
      await page.waitForSelector('text=Dengue season projected', { timeout: 5000 });

      // =====================================================================
      // STEP 5: Click the "1-Click Approve PO" Button
      // =====================================================================
      // This triggers a POST request to create the purchase order.
      // The button text changes to "Routing PO..." while loading, then
      // shows the success message with the PO ID.
      const autoPoButton = page.locator('button:has-text("1-Click Approve PO")');
      await autoPoButton.click();

      // =====================================================================
      // STEP 6: Wait for the UI to Show Success State
      // =====================================================================
      // After the mocked POST returns successfully, the button text updates
      // to show the PO ID. We wait for this change.
      await page.waitForSelector('text=PO-MOCK-001', { timeout: 10000 });

      // =====================================================================
      // STEP 7: Assert Success State
      // =====================================================================
      // The success message confirms that the purchase order was routed.
      await expect(page.locator('text=PO-MOCK-001')).toBeVisible();

      console.log('✓ TEST 3 PASSED: Automated Purchase Order with deterministic mocking succeeded.');
    });

  });

});
