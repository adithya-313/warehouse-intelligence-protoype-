# Architectural Update: Frontend Async Polling
**Status:** Integrated and Verified.
**Description:** To support the Celery/Redis backend decoupling, the Next.js frontend fetch logic (`api.ts` and `InferenceConsole.tsx`) was rewritten. 
**Behavior:** The UI now handles HTTP 202 Responses, extracts the `task_id`, and initiates a 1000ms polling loop against `GET /api/v1/tasks/{task_id}`. The UI gracefully displays a loading state until the `SUCCESS` payload is received.
