import {
  AdapterResponse,
  AggregateWeightsResponse,
  HealthResponse,
  PredictResponse,
  RiskDashboardResponse,
  RiskDashboardResponseSchema,
  SupplierResponse,
  TaskStatusResponse,
  SystemStatsResponse,
  SystemStatsSchema,
} from './schemas';
import { z, ZodSchema } from 'zod';

export interface NotificationResponse {
  id: number;
  title: string;
  message: string;
  alert_type: string;
  // Deep-link to the risk score this alert points at (null for SYSTEM/non-risk alerts).
  health_risk_score_id?: number | null;
  // External reference ID (e.g. PO ID, SKU ID)
  reference_id?: string | null;
  // Disease this alert concerns (derived server-side from the linked score row).
  disease_category?: string | null;
  is_read: boolean;
  created_at: string;
}

export interface PurchaseOrderLineItem {
  sku_id: string;
  ordered_qty: number;
  delivered_qty: number;
  cost_price: number;
  expected_mrp: number;
}

export interface PurchaseOrderResponse {
  po_id: string;
  supplier_id: string;
  supplier_name: string;
  order_date: string | null;
  expected_delivery_date: string | null;
  status: string;
  items: PurchaseOrderLineItem[];
}

// ============================================================================
// HEALTH RISK RADAR TYPES
// Mirrors the backend health_risk Pydantic schemas (app/health_risk/api/schemas.py).
// ============================================================================

export interface HealthRiskScore {
  id: number;
  disease_category: string;
  score: number;
  confidence: string;
  computed_at: string;
}

export interface HealthRiskCurrentScore extends HealthRiskScore {
  // "Low" | "Moderate" | "High" | "Severe" — computed server-side, /current only.
  risk_tier: string;
  // "real_data" | "degraded" — only present on /current.
  data_status: string;
}

export interface HealthRiskCurrentResponse {
  pincode: string;
  scores: HealthRiskCurrentScore[];
}

export interface HealthRiskHistoryResponse {
  pincode: string;
  days: number;
  scores: HealthRiskScore[];
}

export interface HealthRiskContributingFactors {
  trend_score: number | null;
  humidity_percent: number | null;
  rain_mm: number | null;
  weather_anomaly: number | null;
}

export interface HealthRiskExplainResponse {
  id: number;
  pincode: string;
  disease_category: string;
  score: number;
  confidence: string;
  computed_at: string;
  contributing_factors: HealthRiskContributingFactors;
}

let _apiKey: string = '';
// IMPORTANT: This must exactly match the tenant_id seeded in the database.
// All medication_batches, notifications, procurement alerts, etc. are scoped to this tenant.
// Run `SELECT DISTINCT tenant_id FROM medication_batches;` to verify the correct value.
const DEFAULT_TENANT = "PHARM-001";

export function setApiKey(key: string) {
  _apiKey = key;
}

export function getApiKey(): string {
  return _apiKey;
}

/**
 * A beginner-friendly utility to ensure backend JSON objects 
 * have the critical fields we expect, preventing silent UI failures.
 */
function validateRequiredFields(data: any, path: string) {
  if (!data || typeof data !== 'object') {
    throw new Error(`Invalid Response: The backend returned a non-object for ${path}`);
  }

  // Example defensive checks based on route
  if (path.includes('/tasks/')) {
    if (!('status' in data)) {
      throw new Error('Contract Violation: The backend response is missing the required "status" field.');
    }
  }

  // Add other route-specific checks here as needed
}

async function request<T extends z.ZodTypeAny>(
  method: string,
  path: string,
  schema: T,
  body?: unknown,
  timeoutMs: number = 15000,
  signal?: AbortSignal
): Promise<z.infer<T>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (_apiKey) {
    headers['X-API-Key'] = _apiKey;
  }
  headers['X-Tenant-ID'] = DEFAULT_TENANT;

  // If an external signal is provided (e.g., for React unmounts), use it.
  // Otherwise, use the internal timeout controller.
  const controller = new AbortController();
  let id: NodeJS.Timeout | undefined;
  let activeSignal = signal;

  if (!activeSignal) {
    id = setTimeout(() => controller.abort(), timeoutMs);
    activeSignal = controller.signal;
  }

  try {
    const res = await fetch(`${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: activeSignal,
    });
    if (id) clearTimeout(id);

    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        throw new Error('Authentication Failed: Please check your API Key');
      }
      if (res.status >= 500) {
        throw new Error('Server Error: The intelligence backend is currently unreachable.');
      }
      const text = await res.text();
      throw new Error(`[${res.status}] ${path}: ${text.slice(0, 300)}`);
    }

    const raw = await res.json();
    
    // Defensive runtime check to ensure critical fields exist
    validateRequiredFields(raw, path);
    
    return schema.parse(raw);
  } catch (error: any) {
    if (id) clearTimeout(id);
    if (error instanceof z.ZodError) {
      throw new Error(
        `Response validation failed for ${path}: ${error.issues
          .map((e: any) => e.message)
          .join('; ')}`
      );
    }
    // Handle DOMException AbortError gracefully
    if (error.name === 'AbortError') {
      throw new Error('Request Aborted: The operation was cancelled or timed out.');
    }
    if (error.message === 'Failed to fetch' || error.message.includes('NetworkError')) {
      throw new Error('Network Error: Unable to connect to the backend server.');
    }
    throw error;
  }
}

export const api = {
  get: async (url: string) => {
    const res = await fetch(url, { headers: { 'X-Tenant-ID': DEFAULT_TENANT } });
    if (!res.ok) throw new Error(`API Error: ${res.status}`);
    return res.json();
  },

  post: async (url: string, body: any) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': DEFAULT_TENANT },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API Error ${res.status}: ${text.slice(0, 300)}`);
    }
    return res.json();
  },

  health: () =>
    request('GET', '/api/v1/ingestion/health', HealthResponse),

  predict: (payload: {
    module_id: string;
    supplier_id: string;
    sku_id: string;
    route_id: string;
    compute_budget: number;
  }, signal?: AbortSignal) =>
    request('POST', '/api/v1/predict', PredictResponse, payload, 15000, signal),

  getTaskStatus: (task_id: string, signal?: AbortSignal) =>
    request('GET', `/api/v1/tasks/${task_id}`, TaskStatusResponse, undefined, 15000, signal),

  getMetrics: () =>
    request('GET', '/metrics', z.string()).then((text) => {
      const lines = text.split('\n');
      const parse = (name: string) => {
        for (const l of lines) {
          if (l.startsWith(name + ' ')) {
            const parts = l.split(' ');
            return parseFloat(parts[parts.length - 1]);
          }
        }
        return 0;
      };
      return {
        model_drift_alert: parse('model_drift_alert'),
        drift_alerts_total: parse('drift_alerts_total'),
      };
    }),

  aggregateWeights: (payload: Array<{
    supplier_id: string;
    round_number: number;
    weights: number[];
  }>) =>
    request('POST', '/api/v1/federated/weights/aggregate', AggregateWeightsResponse, payload),

  listSuppliers: () =>
    request('GET', '/api/v1/suppliers', z.array(SupplierResponse)),

  listAdapters: () =>
    request('GET', '/api/v1/adapters', z.array(AdapterResponse)),

  async fetchNotifications(): Promise<NotificationResponse[]> {
    try {
      // Removed trailing slash to prevent FastAPI 307 redirect and CORS preflight failure
      const response = await fetch(`/api/v1/notifications`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return [];
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch notifications:", error);
      return [];
    }
  },

  async markNotificationRead(id: number): Promise<{status: string}> {
    const response = await fetch(`/api/v1/notifications/${id}/read`, {
      method: 'PATCH',
      headers: { 'X-Tenant-ID': DEFAULT_TENANT },
    });
    if (!response.ok) throw new Error("Failed to mark notification as read");
    return await response.json();
  },

  async fetchHealthRiskCurrent(): Promise<HealthRiskCurrentResponse | null> {
    try {
      const response = await fetch(`/api/v1/health-risk/current`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch health risk current:", error);
      return null; // Graceful degradation
    }
  },

  async fetchHealthRiskHistory(days: number): Promise<HealthRiskHistoryResponse | null> {
    try {
      const response = await fetch(`/api/v1/health-risk/history?days=${days}`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch health risk history:", error);
      return null; // Graceful degradation
    }
  },

  async fetchHealthRiskExplain(scoreId: number): Promise<HealthRiskExplainResponse | null> {
    try {
      const response = await fetch(`/api/v1/health-risk/explain/${scoreId}`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch health risk explain:", error);
      return null; // Graceful degradation
    }
  },

  async fetchPurchaseOrder(poId: string): Promise<PurchaseOrderResponse | null> {
    try {
      const response = await fetch(`/api/v1/purchase-orders/${poId}`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch purchase order details:", error);
      return null;
    }
  },

  async searchInventory(q: string): Promise<any[]> {
    try {
      const headers: Record<string, string> = {
        'X-Tenant-ID': DEFAULT_TENANT,
      };
      if (_apiKey) {
        headers['X-API-Key'] = _apiKey;
      }
      const response = await fetch(`/api/v1/inventory/search?q=${encodeURIComponent(q)}`, {
        headers,
        cache: 'no-store'
      });
      if (!response.ok) return [];
      return await response.json();
    } catch (error) {
      console.error("Failed to search inventory:", error);
      return [];
    }
  },

  // Beginner Note: This function sends the user's cart items to the backend checkout endpoint.
  // We explicitly inject the required X-Tenant-ID and X-API-Key headers to pass the backend authentication guards.
  // We also forward the optional customer identity so the backend can upsert the patient profile
  // within the same ACID transaction and link the receipt for future refill reminders.
  async submitCheckout(
    cartItems: any[],
    customerPhone?: string,
    customerName?: string,
    paymentMethod?: PaymentMethod
  ): Promise<{ receipt_id: string, message: string }> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Tenant-ID': DEFAULT_TENANT,
    };
    
    // Inject the global API key if it's set
    if (_apiKey) {
      headers['X-API-Key'] = _apiKey;
    }

    // Generate a cryptographically unique idempotency key for every checkout attempt.
    // Beginner Note: This UUID is stored in Redis on the backend. If the pharmacist
    // accidentally clicks "Pay" twice, the second request has the SAME key and the
    // backend returns 409 Conflict — preventing a double charge.
    const checkoutIdempotencyKey: string = crypto.randomUUID();

    // Format the payload exactly as the backend expects (CheckoutRequestSchema)
    const checkoutPayload = {
      items: cartItems.map(item => ({
        batch_id: item.batch_id,
        sku_id: item.sku_id,
        name: item.name || '',
        quantity: item.quantity,
        price: item.price
      })),
      payment_method: paymentMethod || 'CASH',
      idempotency_key: checkoutIdempotencyKey,
      customer_phone: customerPhone || null,
      customer_name: customerName || null
    };

    const response = await fetch(`/api/v1/pos/checkout`, {
      method: 'POST',
      headers,
      body: JSON.stringify(checkoutPayload)
    });

    if (!response.ok) {
      const errorData = await response.text();
      throw new Error(`Checkout failed: ${errorData}`);
    }

    return await response.json();
  },

  // Beginner Note: This function is called by the POS progressive disclosure UI when the
  // pharmacist types a phone number. It checks if a patient with that number already exists.
  // If found, the UI shows a "Returning Patient" badge. If not found (404), the UI
  // reveals a name input field for a new patient registration.
  async lookupPatient(phone: string): Promise<{ patient_id: string, name: string, phone_number: string } | null> {
    try {
      const response = await fetch(`/api/v1/pos/patient/lookup/${encodeURIComponent(phone)}`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
      });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  },
  
  async fetchTransactionHistory(): Promise<TransactionHistoryItem[]> {
    try {
      const response = await fetch('/api/v1/pos/history', {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) throw new Error("Failed to fetch transaction history");
      const data: any[] = await response.json();
      return data.map(tx => ({
        ...tx,
        items: tx.items || [],
        payment_method: tx.payment_method || 'CASH',
      }));
    } catch {
      return [];
    }
  }
};

export interface CrossSellItem {
  recommended_sku: string;
  confidence_score: number;
}

export interface GenericAlternative {
  sku_id: string;
  batch_id: string;
  profit_score: number;
  mrp: number;
  cost: number;
}

export interface RecommendationResponse {
  status: string;
  scanned_sku: string;
  cross_sells: CrossSellItem[];
  generic_alternatives: GenericAlternative[];
}

export type PaymentMethod = 'CASH' | 'UPI' | 'CARD';

export interface TransactionItem {
  productId: string;
  name: string;
  price: number;
  quantity: number;
  total: number;
}

export interface TransactionHistoryItem {
  id: string;
  timestamp: string;
  total_amount_inr: number;
  payment_method: PaymentMethod;
  customer_name: string | null;
  customer_phone: string | null;
  items: TransactionItem[];
}

/**
 * Fetches the risk dashboard data from the backend API.
 *
 * This function does NOT use the shared `request()` utility because the
 * risk dashboard endpoint does not require an API key (no X-API-Key header).
 * It uses bare fetch() + Zod.parse() to validate the response shape.
 *
 * Returns a strongly typed RiskDashboardResponse with three arrays:
 * stockouts, dead_stock, and anomalies.
 */
export async function fetchRiskDashboard(): Promise<RiskDashboardResponse> {
  // Send a GET request to the Next.js proxied backend endpoint.
  // The relative URL routes through next.config.js rewrites to the API.
  const response = await fetch('/api/v1/risk/dashboard', {
    headers: { 'X-Tenant-ID': DEFAULT_TENANT }
  });

  // If the backend returns a non-200 status, throw immediately
  // so the calling component can display the error to the user.
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }

  // Parse the raw JSON body.
  const data = await response.json();

  // Validate the data against our Zod schema.
  // If the backend ever changes the response shape, Zod.parse() will
  // throw a descriptive error that we can surface in the UI.
  return RiskDashboardResponseSchema.parse(data);
}

export interface CatalogItem {
  supplier_id: string;
  skus: string[];
}

export async function fetchHardwareCatalog(): Promise<CatalogItem[]> {
  const response = await fetch('/api/v1/risk/catalog', {
    headers: { 'X-Tenant-ID': DEFAULT_TENANT },
    cache: 'no-store'
  });
  if (!response.ok) throw new Error("Failed to fetch catalog");
  return response.json();
}

export async function fetchSystemStats(): Promise<SystemStatsResponse> {
  const response = await fetch('/api/v1/system/stats', {
    headers: { 'X-Tenant-ID': DEFAULT_TENANT },
    cache: 'no-store'
  });
  if (!response.ok) throw new Error("Failed to fetch system stats");
  return SystemStatsSchema.parse(await response.json());
}

export async function fetchRecommendations(skuId: string): Promise<RecommendationResponse> {
  const response = await fetch(`/api/v1/pos/recommendations/${encodeURIComponent(skuId)}`, {
    headers: { 'X-Tenant-ID': DEFAULT_TENANT },
    cache: 'no-store'
  });
  if (!response.ok) throw new Error(`Failed to fetch recommendations: ${response.status}`);
  return response.json();
}
