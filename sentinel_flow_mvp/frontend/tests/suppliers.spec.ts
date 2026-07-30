import { test, expect } from '@playwright/test';

test.describe('Supplier Page', () => {
  test('should display fetched vendors and re-fetch after add', async ({ page }) => {
    // 1. Initial list mock
    let fetchCount = 0;
    await page.route('**/api/v1/suppliers?*', async route => {
      fetchCount++;
      if (fetchCount === 1) {
        await route.fulfill({
          json: {
            total: 1,
            limit: 50,
            offset: 0,
            items: [
              { supplier_id: "TEST-LIVE-001", name: "Live Backend Vendor", industry_vertical: "LOGISTICS" }
            ]
          }
        });
      } else {
        // Second fetch (after add) includes the new vendor
        await route.fulfill({
          json: {
            total: 2,
            limit: 50,
            offset: 0,
            items: [
              { supplier_id: "TEST-LIVE-001", name: "Live Backend Vendor", industry_vertical: "LOGISTICS" },
              { supplier_id: "TEST-LIVE-002", name: "Freshly Fetched Vendor", industry_vertical: "PHARMACEUTICALS" }
            ]
          }
        });
      }
    });

    // Scorecard mock to prevent UI crash
    await page.route('**/api/v1/suppliers/*/scorecard', async route => {
      const url = route.request().url();
      const match = url.match(/\/api\/v1\/suppliers\/([^/]+)\/scorecard/);
      const id = match ? match[1] : "dummy";
      let name = "dummy";
      if (id === "TEST-LIVE-001") name = "Live Backend Vendor";
      if (id === "TEST-LIVE-002") name = "Freshly Fetched Vendor";

      await route.fulfill({
        json: {
          supplier_id: id, name: name, financial_loss_rupees: 0,
          delivery_success_rate: 100, trust_score: 100, risk_level: "TRUSTED", recent_failures: 0
        }
      });
    });

    // POST mock for adding vendor
    await page.route('**/api/v1/suppliers', async route => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          json: {
            supplier_id: "TEST-LIVE-002", name: "Freshly Fetched Vendor", industry_vertical: "PHARMACEUTICALS"
          }
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('http://localhost:3000/suppliers');

    // Wait for the loading state to disappear and first vendor to appear
    await expect(page.locator('text=Loading vendor intelligence...')).not.toBeVisible({ timeout: 8000 });
    await expect(page.locator('text=Live Backend Vendor')).toBeVisible();
    await expect(page.locator('text=MediCorp Global')).not.toBeVisible();

    // Add a new vendor via UI
    await page.click('button:has-text("Add Vendor")');
    // Assuming the modal has an input for Name and a submit button. Wait for modal to be visible.
    await expect(page.locator('text=Onboard Supplier')).toBeVisible();
    
    // The AddVendorModal has specific fields (from previous knowledge, it likely has Name and Industry)
    await page.fill('input[placeholder="Registered Vendor Name"]', 'Freshly Fetched Vendor');
    await page.fill('input[placeholder="Primary Contact Email"]', 'test@test.com');
    // We just click the create/submit button
    await page.click('button:has-text("Initialize Vendor Ledger")');

    // The modal should close and the re-fetch will happen.
    // We just wait for the loading indicator to NOT be visible.
    await expect(page.locator('text=Loading vendor intelligence...')).not.toBeVisible({ timeout: 8000 });

    // Ensure the new fetched data IS present
    await expect(page.locator('text=Freshly Fetched Vendor')).toBeVisible();
    
    // Verify the fetch count is at least 2 (initial mount + post-add)
    // Note: React StrictMode might cause an extra mount, resulting in 3.
    expect(fetchCount).toBeGreaterThanOrEqual(2);
  });
});
