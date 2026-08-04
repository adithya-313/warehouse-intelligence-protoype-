export function calculateDaysLate(
  status: string,
  expectedDeliveryDateStr: string | null | undefined,
  actualDeliveryDateStr: string | null | undefined,
  todayStr: string = new Date().toISOString().split('T')[0]
): number {
  if (!expectedDeliveryDateStr) return 0;

  // We compare only the YYYY-MM-DD parts to avoid timezone issues.
  const expected = new Date(expectedDeliveryDateStr.split('T')[0]);
  const today = new Date(todayStr.split('T')[0]);

  if (status === 'SUBMITTED' || status === 'PARTIAL') {
    if (today > expected) {
      const diffTime = today.getTime() - expected.getTime();
      return Math.round(diffTime / (1000 * 60 * 60 * 24));
    }
  } else if (status === 'FULFILLED') {
    if (!actualDeliveryDateStr) return 0;
    const actual = new Date(actualDeliveryDateStr.split('T')[0]);
    if (actual > expected) {
      const diffTime = actual.getTime() - expected.getTime();
      return Math.round(diffTime / (1000 * 60 * 60 * 24));
    }
  }

  return 0;
}
