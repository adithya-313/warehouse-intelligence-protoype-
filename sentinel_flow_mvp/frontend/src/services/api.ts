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

export interface DiseaseWaveAlert {
  sku_id: string;
  sku_name: string;
  probability_score: number;
  expected_volume: number;
  recommended_supplier_id: string;
  warning_message: string;
}

export interface NotificationResponse {
  id: number;
  title: string;
  message: string;
  alert_type: string;
  is_read: boolean;
  created_at: string;
}

export interface AutoPOResponse {
  po_id: number;
  status: string;
  message: string;
}

let _apiKey: string = '';
const DEFAULT_TENANT = "system_admin";

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

  async fetchWaveAlerts(): Promise<DiseaseWaveAlert[]> {
    try {
      const response = await fetch(`/api/v1/procurement/disease-wave-alerts`, {
        headers: { 'X-Tenant-ID': DEFAULT_TENANT },
        cache: 'no-store'
      });
      if (!response.ok) return [];
      return await response.json();
    } catch (error) {
      console.error("Failed to fetch wave alerts:", error);
      return []; // Graceful degradation
    }
  },

  async createAutoPO(sku_id: string, supplier_id: string, quantity: number): Promise<AutoPOResponse> {
    const response = await fetch(`/api/v1/procurement/auto-po`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'X-Tenant-ID': DEFAULT_TENANT 
      },
      body: JSON.stringify({ sku_id, supplier_id, quantity }),
    });
    if (!response.ok) throw new Error("Failed to create Purchase Order");
    return await response.json();
  },

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
};

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
