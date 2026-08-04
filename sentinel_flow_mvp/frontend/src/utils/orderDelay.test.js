const fs = require('fs');

// A quick and dirty regex to extract the function from the TS file so we can test it in JS
const tsCode = fs.readFileSync('./src/utils/orderDelay.ts', 'utf8');
const jsCode = tsCode.replace(/export function calculateDaysLate/g, 'function calculateDaysLate').replace(/: string \| null \| undefined/g, '').replace(/: string/g, '').replace(/: number/g, '').replace(/ = new Date\(\).toISOString\(\).split\('T'\)\[0\]/g, '');

eval(jsCode);

console.log("--- Delay Calculation Tests ---");

// Helper to log test output
function runTest(name, status, expected, actual, today) {
    const todayStr = today || new Date().toISOString().split('T')[0];
    const result = calculateDaysLate(status, expected, actual, todayStr);
    console.log(`[${name}]`);
    console.log(`Status: ${status} | Expected: ${expected} | Actual: ${actual} | Today: ${todayStr}`);
    console.log(`=> ${result} days late\n`);
}

runTest("0 days late (not yet due)", "SUBMITTED", "2026-08-10", null, "2026-08-01");
runTest("1-2 days late (SUBMITTED)", "SUBMITTED", "2026-08-01", null, "2026-08-02"); // 1 day
runTest("3-6 days late (PARTIAL)", "PARTIAL", "2026-08-01", null, "2026-08-05"); // 4 days
runTest("7+ days late (SUBMITTED)", "SUBMITTED", "2026-08-01", null, "2026-08-10"); // 9 days

runTest("FULFILLED but was late", "FULFILLED", "2026-08-01", "2026-08-05", "2026-08-10"); // 4 days (historical)
runTest("FULFILLED on time", "FULFILLED", "2026-08-01", "2026-08-01", "2026-08-10"); // 0 days
runTest("FULFILLED early", "FULFILLED", "2026-08-05", "2026-08-01", "2026-08-10"); // 0 days
