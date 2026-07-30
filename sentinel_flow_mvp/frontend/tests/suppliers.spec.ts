import { test, expect } from '@playwright/test';

test.describe('Supplier Page', () => {
  test('should display fetched vendors and not hardcoded data', async ({ page }) => {
    // Mock the backend API response
    await page.route('**/api/v1/suppliers*', async route => {
      const json = {
        total: 1,
        limit: 50,
        offset: 0,
        items: [
          {
            supplier_id: "TEST-LIVE-001",
            name: "Live Backend Vendor",
            industry_vertical: "LOGISTICS"
          }
        ]
      };
      await route.fulfill({ json });
    });

    // We assume the frontend dev server is running on localhost:3000
    // Actually, in our pipeline we just verify the fetch logic, so we can go to /suppliers
    await page.goto('http://localhost:3000/suppliers');

    // Wait for the loading state to disappear
    await expect(page.locator('text=Loading vendor intelligence...')).not.toBeVisible({ timeout: 5000 });

    // Ensure the old hardcoded data is NOT present
    await expect(page.locator('text=MediCorp Global')).not.toBeVisible();
    await expect(page.locator('text=Relief Logistics')).not.toBeVisible();

    // Ensure the fetched data IS present
    await expect(page.locator('text=Live Backend Vendor')).toBeVisible();
  });
});
