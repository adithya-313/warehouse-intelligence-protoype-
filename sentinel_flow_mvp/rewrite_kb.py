import sys
import re

file_path = 'app/api/v1/knowledge_base.py'
with open(file_path, 'r') as f:
    content = f.read()

if 'import uuid' not in content:
    content = 'import uuid\nimport time\n' + content

# Find the start of the function body
start_idx = content.find('    # =====================================================================\n    # STEP 0: SANITIZE THE QUERY')

if start_idx == -1:
    print('Could not find start of function')
    sys.exit(1)

end_marker = '        citations=rag_data.get("citations", []),\n    )\n'
end_idx = content.find(end_marker) + len(end_marker)

if end_idx == -1:
    print('Could not find end of function')
    sys.exit(1)

original_body = content[start_idx:end_idx]

indented_body = '\n'.join('    ' + line if line else line for line in original_body.split('\n'))

new_header = '''    import uuid
    import time

    correlation_id = str(uuid.uuid4())
    start_time = time.monotonic()
    
    # This dict collects facts about this one request as we go, so we can log exactly
    # one clean summary line at the very end, no matter which exit door the request leaves through.
    request_metrics = {
        "intent": None,
        "path_taken": None,
        "fallback_triggered": False,
        "drug_resolved": None,
        "disambiguation_triggered": False,
    }
    
    try:
'''

new_footer = '''    except Exception:
        # we don't know the outcome, but log what we captured so far
        raise
    finally:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        request_metrics["latency_ms"] = latency_ms
        request_metrics["correlation_id"] = correlation_id
        logger.info(
            "request_completed",
            extra=request_metrics,
        )
'''

# Now let's inject the request_metrics updates before each return.
# Exit 1 (NO_INTENT early return)
indented_body = indented_body.replace(
    '        if bucket == IntentBucket.NO_INTENT and not any(intents.values()):\n            return RAGQueryResponse(',
    '        if bucket == IntentBucket.NO_INTENT and not any(intents.values()):\n            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n            request_metrics["path_taken"] = "none"\n            request_metrics["fallback_triggered"] = True\n            # drug_resolved is None since resolve_drug_entity was not called\n            return RAGQueryResponse('
)

# Exit 2 (IntentGate failure fallback)
indented_body = indented_body.replace(
    '            # FINAL FAIL-SAFE: No regex drug AND no catalog match.\n            # ------------------------------------------------------------------\n            return RAGQueryResponse(',
    '            # FINAL FAIL-SAFE: No regex drug AND no catalog match.\n            # ------------------------------------------------------------------\n            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n            request_metrics["path_taken"] = "none"\n            request_metrics["fallback_triggered"] = True\n            request_metrics["drug_resolved"] = False\n            request_metrics["disambiguation_triggered"] = False\n            return RAGQueryResponse('
)

# Exit 3 (no_match fallback)
indented_body = indented_body.replace(
    '        if resolution["status"] == "no_match":\n            return RAGQueryResponse(',
    '        if resolution["status"] == "no_match":\n            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n            request_metrics["drug_resolved"] = False\n            request_metrics["disambiguation_triggered"] = False\n            request_metrics["fallback_triggered"] = True\n            request_metrics["path_taken"] = "none"\n            return RAGQueryResponse('
)

# Exit 4 (disambiguate)
indented_body = indented_body.replace(
    '        elif resolution["status"] == "disambiguate":\n            return RAGQueryResponse(',
    '        elif resolution["status"] == "disambiguate":\n            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n            request_metrics["drug_resolved"] = False\n            request_metrics["disambiguation_triggered"] = True\n            request_metrics["path_taken"] = "none"\n            return RAGQueryResponse('
)

# Exit 5 (substitute bypass)
indented_body = indented_body.replace(
    '            return RAGQueryResponse(\n                query=payload.query,\n                answer=formatted_response,\n                context_used=[],\n                is_safe_to_dispense=True,\n                system_lock_reason=None,\n                citations=[],\n            )',
    '            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n            request_metrics["drug_resolved"] = True\n            request_metrics["disambiguation_triggered"] = False\n            request_metrics["path_taken"] = "substitute"\n            return RAGQueryResponse(\n                query=payload.query,\n                answer=formatted_response,\n                context_used=[],\n                is_safe_to_dispense=True,\n                system_lock_reason=None,\n                citations=[],\n            )'
)

# Exit 6 (successful fall-through)
indented_body = indented_body.replace(
    '        return RAGQueryResponse(\n            query=payload.query,\n            answer=rag_data["answer"],',
    '        request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)\n        request_metrics["drug_resolved"] = True\n        request_metrics["disambiguation_triggered"] = False\n        request_metrics["path_taken"] = rag_data.get("path_taken")\n        return RAGQueryResponse(\n            query=payload.query,\n            answer=rag_data["answer"],'
)

new_content = content[:start_idx] + new_header + indented_body + new_footer + content[end_idx:]

with open(file_path, 'w') as f:
    f.write(new_content)
print("Script finished successfully")
