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

  test('modal and panel should be positioned correctly within viewport', async ({ page }) => {
    // Generate 10 vendors
    const vendors = Array.from({ length: 10 }).map((_, i) => ({
      supplier_id: `TEST-POS-${i}`,
      name: `Vendor ${i}`,
      industry_vertical: "PHARMACEUTICALS"
    }));

    await page.route('**/api/v1/suppliers?*', async route => {
      await route.fulfill({
        json: {
          total: 10,
          limit: 50,
          offset: 0,
          items: vendors
        }
      });
    });

    await page.route('**/api/v1/suppliers/*/scorecard', async route => {
      const url = route.request().url();
      const match = url.match(/\/api\/v1\/suppliers\/([^/]+)\/scorecard/);
      const id = match ? match[1] : "dummy";
      // extract the number from TEST-POS-X
      const num = id.split('-').pop();
      await route.fulfill({
        json: {
          supplier_id: id, name: `Vendor ${num}`, financial_loss_rupees: 0,
          delivery_success_rate: 100, trust_score: 100, risk_level: "TRUSTED", recent_failures: 0
        }
      });
    });

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('http://localhost:3000/suppliers');
    await expect(page.locator('text=Vendor 9').first()).toBeVisible({ timeout: 10000 });

    // 1. Test Add Vendor Modal (triggered from top)
    await page.click('button:has-text("Add Vendor")');
    const modalHeader = page.locator('text=Onboard Supplier');
    await expect(modalHeader).toBeVisible();
    
    // Check position of modal - should be within viewport
    const modalBox = await modalHeader.boundingBox();
    expect(modalBox).not.toBeNull();
    // Modal is centered, so Y should be roughly in the middle of 800px viewport, well within 0-800 bounds
    expect(modalBox!.y).toBeGreaterThan(0);
    expect(modalBox!.y).toBeLessThan(800);
    
    // Close modal
    await page.locator('.fixed.inset-0').locator('button').first().click();
    await expect(modalHeader).not.toBeVisible();

    // 2. Test Order Stock Panel on 5th vendor
    // Scroll down to the 5th vendor to ensure the page has scrolled
    const vendor5 = page.locator('text=Vendor 5');
    await vendor5.scrollIntoViewIfNeeded();
    
    // Click its Order Stock button. We can find the button near Vendor 5.
    const orderBtn = page.locator('div').filter({ hasText: 'Vendor 5' }).locator('button:has-text("Order Stock")').first();
    await orderBtn.click();
    
    const panelHeader = page.locator('text=Manifest Builder');
    await expect(panelHeader).toBeVisible();

    // Check position of panel
    const panelBox = await panelHeader.boundingBox();
    expect(panelBox).not.toBeNull();
    // It is fixed top-0, so it should be near y=0 of the viewport (not scrolled out of view)
    expect(panelBox!.y).toBeGreaterThanOrEqual(0);
    expect(panelBox!.y).toBeLessThan(100);
  });
});
