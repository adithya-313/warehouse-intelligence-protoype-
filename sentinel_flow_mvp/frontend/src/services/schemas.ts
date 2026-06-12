import { z } from "zod";

export const HealthResponse = z.object({
  status: z.string(),
});

export const PredictResponse = z.object({
  status: z.string(),
  task_id: z.string(),
});

export const TaskResult = z.object({
  prediction_value: z.number(),
  confidence_score: z.number(),
  fallback_engaged: z.boolean(),
  model_version: z.string(),
  correlation_id: z.string(),
  historical_trajectory: z.array(z.number()),
  forecast_trajectory: z.array(z.number()),
});

export const TaskStatusResponse = z.object({
  status: z.string(),
  result: TaskResult.optional(),
  error: z.string().optional(),
});

export const SupplierResponse = z.object({
  supplier_id: z.string(),
});

export const AdapterResponse = z.object({
  id: z.string(),
  module_name: z.string(),
  base_model_version: z.string(),
  adapter_weights_path: z.string().nullable(),
  status: z.string(),
  created_at: z.string(),
});

export const AggregateWeightsResponse = z.object({
  aggregated_weights: z.array(z.number()),
  status: z.string(),
});

// ------------------------------------------------------------------
// Risk Dashboard Zod Schemas
// These define the exact contract between the FastAPI backend and
// the React frontend. Zod.parse() will throw a detailed error if
// the backend ever sends unexpected data.
// ------------------------------------------------------------------

// Defines the shape of a single risk item within a category.
// The severity field is constrained to exactly three string values
// matching the backend RiskItem.severity Pydantic field.
export const RiskItemSchema = z.object({
  supplier_id: z.string(),
  metric: z.string(),
  value: z.string(),
  severity: z.enum(["critical", "warning", "info"]),
});

// Defines the complete dashboard payload with three risk category arrays.
// Each array defaults to empty — this matches the backend's
// RiskDashboardResponse Pydantic model with default_factory=list.
export const RiskDashboardResponseSchema = z.object({
  stockouts: z.array(RiskItemSchema),
  dead_stock: z.array(RiskItemSchema),
  anomalies: z.array(RiskItemSchema),
});

// Inferred TypeScript type from the Zod schema.
// This gives us full IDE autocompletion and compile-time type checking
// without needing to maintain a separate TypeScript interface.
export type RiskDashboardResponse = z.infer<typeof RiskDashboardResponseSchema>;

export const SystemStatsSchema = z.object({
  total_telemetry_records: z.number(),
  total_suppliers: z.number(),
  active_adapters: z.number(),
  total_adapters: z.number(),
  neural_backbone: z.string(),
});
export type SystemStatsResponse = z.infer<typeof SystemStatsSchema>;
