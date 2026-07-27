# D1 Preflight Investigation Report

## 1. Full Current Prompt Template
Located in `app/services/rag_pipeline.py` (lines 816-836), the prompt is hardcoded to assume a "SAFE" verdict and forces the AI to write a safety explanation:

```python
    prompt = f"""You are a strict clinical safety narrator for a pharmacy.

The system has determined this transaction is: SAFE — ALLOWED (Judge rule: {judge_triggered_rule}).
You must explain why this medication is safe based on the provided clinical context.

RULES:
1. Do NOT hallucinate or use outside medical knowledge.
2. If the provided context does not contain the answer, set narrative to "INSUFFICIENT CLINICAL DATA. CONSULT PHARMACIST."
3. Keep the narrative concise, professional, and direct.
4. You MUST return a valid JSON object with the following fields:
   - is_safe_to_dispense (boolean): Always true in this context.
   - narrative (string): Your explanation.
   - system_lock_reason (null): Always null in this context.
   - citations (array of strings): Any clinical sources referenced.

CLINICAL CONTEXT:
{context_blocks}

USER QUERY:
{query}
"""
```

## 2. Full Current Response Schema
The schema is defined in `app/domain/schemas.py` and enforced programmatically in `generate_clinical_response` via both `generation_config.response_schema` and `ClinicalNarrativeSchema(**parsed_data)`.

```python
class ClinicalNarrativeSchema(BaseModel):
    is_safe_to_dispense: StrictBool
    narrative: str
    system_lock_reason: str | None
    citations: list[str]
```

## 3. Consumers of the Response & Frontend Behavior
**Backend API**: The `/api/v1/knowledge-base/ask` route consumes this dictionary and maps it into a `RAGQueryResponse`.
**Frontend**: `frontend/src/components/pos/CopilotPanel.tsx` is the sole consumer.
- **`is_safe_to_dispense` missing?**: If `is_safe_to_dispense` is `undefined` (or true), the UI gracefully defaults to rendering a standard blue message bubble. It only triggers the red "blocked" UI if explicitly `false`. It will **not crash**.
- **`narrative` shape?**: The narrative is mapped to `msg.content` and rendered as plain text within a `<p>` tag inside the chat bubble. It handles any string. If the AI returns a general knowledge answer (e.g., "The difference is...") instead of a "safety explanation", it will render perfectly without crashing or looking broken.

## 4. Judge Verdict Placement
The Judge's deterministic safety check (`judge.evaluate_safety`) is invoked **unconditionally** in `generate_clinical_response` (Step 4), *before* the LLM generation (Step 6). 
- It runs even for general knowledge questions (e.g., "what is the difference between X and Y?").
- Because these general questions don't trigger contraindications, the Judge returns a "SAFE" verdict.
- This forces the prompt to tell the LLM: "The system has determined this transaction is: SAFE ... explain why this medication is safe," which is why the LLM hallucinates safety explanations for non-safety questions.
- *There is no mechanism checking if the question is actually about dispensing before running the Judge.*

## 5. Intent Signals
I have confirmed that `QuerySanitizer.extract_intents()` in `app/services/sanitizer.py` checks for exactly four broad flags:
- `pregnancy`
- `pediatric`
- `substitute`
- `objective`

**There is no signal anywhere** (in the payload, sanitizer, or IntentGate) that categorizes the specific type of clinical question being asked (e.g., symptom vs. dosage vs. comparison). The system treats all non-objective, non-substitute queries as a single monolithic "AMBIGUOUS / CLINICAL" bucket.

---
### Candidate Hypothesis (Not Applied)
**To fix the prompt:**
We need to decouple the *Judge's verdict* from the *LLM's persona*. 
1. The AI should act as a general clinical assistant answering the `USER QUERY` based on the `CLINICAL CONTEXT`.
2. The Judge's verdict (and `is_safe_to_dispense` / `system_lock_reason`) should be passed into the prompt as *additional context* (e.g., "Note: The safety engine flagged this as UNSAFE due to X"), rather than forcing the AI's entire goal to be "explain why this is safe." 
3. The LLM schema should remain the same to satisfy the frontend, but the prompt should instruct the LLM to simply answer the user's question in the `narrative` field, while passing through the Judge's safety flags accurately into the JSON.
