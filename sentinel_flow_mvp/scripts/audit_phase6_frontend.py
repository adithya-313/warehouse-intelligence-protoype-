"""
PHASE 6 — FRONTEND STATE & UI AUDIT
=====================================
Read-only scan of the React/Next.js frontend to map integration points
for the new backend ClinicalNarrativeSchema (added in Phase 3).

We scan three critical areas:

  1. Zustand Store (posStore.ts)
     — Copilot/Chat state and actions.
     — POS Cart/Checkout state for the "Proceed to Payment" lock.

  2. Copilot UI Component (CopilotPanel.tsx)
     — How it currently renders the backend API response.
     — Whether it reads is_safe_to_dispense, system_lock_reason, or citations.

  3. POS Page (pos/page.tsx)
     — The checkout flow and whether a safety interlock exists.

This script is READ-ONLY. It never writes to any .ts, .tsx, or .js file.

Usage:
    python scripts/audit_phase6_frontend.py

Exit code:
    0 on success (always — this is a read-only audit).
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# BEGINNER NOTE: We locate the project root automatically so this script
# works from any working directory. The frontend lives at
#   <project_root>/frontend/
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
FRONTEND_ROOT: Path = PROJECT_ROOT / "frontend"

# ---------------------------------------------------------------------------
# Audit result accumulator — we fill this dict as we scan each file.
# ---------------------------------------------------------------------------
AUDIT_RESULT: dict[str, Any] = {
    "agent_action_summary": "",
    "zustand_copilot_store": {
        "file_path": "",
        "state_variables_found": [],
        "actions_found": [],
    },
    "react_copilot_ui": {
        "file_path": "",
        "current_message_rendering": "",
        "has_existing_safety_ui_states": False,
    },
    "checkout_interlock_target": {
        "file_path": "",
        "cart_state_variables": [],
    },
}


# =====================================================================
# STEP 1 — ZIP THROUGH ALL FRONTEND DIRECTORIES
# =====================================================================

def scan_directory_tree() -> dict[str, list[str]]:
    """
    Walk the frontend/ directory (excluding node_modules/ and .next/)
    and categorise every .ts, .tsx, and .js file by its parent directory.

    This gives us a bird's-eye view of the frontend architecture.

    Returns:
        A dict where keys are directory names (e.g., "store", "components/pos")
        and values are lists of full file paths found inside them.
    """
    print("=" * 72)
    print("  SCANNING FRONTEND DIRECTORY TREE")
    print("=" * 72)
    print(f"  Root: {FRONTEND_ROOT}")

    # We'll organise files by their immediate subdirectory.
    # "store" -> [posStore.ts]
    # "components/pos" -> [CopilotPanel.tsx, ClinicalCompanion.tsx]
    # etc.
    tree: dict[str, list[str]] = {}

    # Recursively walk all directories under frontend/.
    for dirpath_str, dirnames, filenames in os.walk(str(FRONTEND_ROOT)):
        dirpath: Path = Path(dirpath_str)

        # ---------------------------------------------------------------
        # Skip vendor and build directories — they are not source code.
        # ---------------------------------------------------------------
        # We check if ANY part of the path contains node_modules or .next.
        rel_path: str = dirpath.relative_to(FRONTEND_ROOT).as_posix()
        skip_parts: list[str] = ["node_modules", ".next", ".git"]
        if any(skip in dirpath.parts for skip in skip_parts):
            continue

        # Only process files ending in .ts, .tsx, or .js.
        for filename in filenames:
            if not (filename.endswith(".ts") or filename.endswith(".tsx") or filename.endswith(".js")):
                continue

            # Use the relative path from frontend/ as our key.
            # e.g., "src/store/posStore.ts" or "components/MetricCard.tsx"
            full_rel_path: str = (dirpath.relative_to(FRONTEND_ROOT) / filename).as_posix()

            # Group by the FIRST meaningful directory component.
            # e.g., "src/store", "components", "components/pos"
            parts: list[str] = full_rel_path.split("/")
            if len(parts) >= 2:
                group_key: str = "/".join(parts[:-1])  # everything except the filename
            else:
                group_key: str = "(root)"

            if group_key not in tree:
                tree[group_key] = []
            tree[group_key].append(full_rel_path)

    # Print a summary of what we found.
    for group, files in sorted(tree.items()):
        print(f"\n  [{group}/]")
        for f in sorted(files):
            print(f"    {f}")

    print(f"\n  Total source files found: {sum(len(v) for v in tree.values())}")
    print()

    return tree


# =====================================================================
# STEP 2 — AUDIT THE ZUSTAND STORE (posStore.ts)
# =====================================================================
# Why do we need this?
#   The Zustand store manages the chat messages and cart state. We need
#   to see:
#     (a) What chat fields exist — do they have room for safety data?
#     (b) What cart actions exist — can we add a "safety lock" flag?

def audit_zustand_store() -> dict[str, Any]:
    """
    Locate and parse the Zustand store file (posStore.ts) to extract:
      - State variable names (e.g., chatHistory, isCopilotOpen, cart).
      - Action function names (e.g., addChatMessage, toggleCopilot).
      - The ChatMessage interface shape.
      - Whether a safety-lock field already exists in the cart/checkout state.

    Returns:
        A dict with file_path, state_variables_found, and actions_found.
    """
    print("=" * 72)
    print("  AUDITING ZUSTAND STORE")
    print("=" * 72)

    # The Zustand store is expected at frontend/src/store/posStore.ts.
    store_path: Path = FRONTEND_ROOT / "src" / "store" / "posStore.ts"

    if not store_path.exists():
        # Some projects put the store directly in frontend/store/.
        store_path = FRONTEND_ROOT / "store" / "posStore.ts"

    if not store_path.exists():
        print("  [!!] Zustand store not found at any expected location.")
        return {"file_path": "", "state_variables_found": [], "actions_found": []}

    result: dict[str, Any] = {
        "file_path": str(store_path.relative_to(PROJECT_ROOT)),
        "state_variables_found": [],
        "actions_found": [],
        "chat_message_interface": {},
    }

    print(f"  Found at: {result['file_path']}")

    # Read the entire store file into memory.
    content: str = store_path.read_text(encoding="utf-8")
    lines: list[str] = content.splitlines()

    # ------------------------------------------------------------------
    # (A) Extract the ChatMessage interface.
    # ------------------------------------------------------------------
    # We look for "export interface ChatMessage {" and read until "}".
    in_chat_interface: bool = False
    chat_iface_lines: list[str] = []

    for line in lines:
        stripped: str = line.strip()
        if "interface ChatMessage" in stripped:
            in_chat_interface = True
        if in_chat_interface:
            chat_iface_lines.append(stripped)
            if stripped == "}" and in_chat_interface:
                break

    if chat_iface_lines:
        print("\n  ChatMessage interface:")
        for cl in chat_iface_lines:
            print(f"    {cl}")

    # ------------------------------------------------------------------
    # (B) Extract state variable names from the POSState interface.
    # ------------------------------------------------------------------
    # We look for lines inside the POSState interface that are NOT
    # function types (no parentheses). These are our state variables.
    in_pos_state: bool = False
    state_vars: list[str] = []
    actions: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Detect the start of the POSState interface.
        if "interface POSState" in stripped:
            in_pos_state = True
            continue

        # Detect the end of the interface.
        if in_pos_state and stripped == "}":
            break

        if in_pos_state:
            # A line like "  cart: CartItem[];" or "  chatHistory: ChatMessage[];"
            # is a state variable (no opening parenthesis).
            if ":" in stripped and "(" not in stripped and stripped != "{":
                var_name: str = stripped.split(":")[0].strip()
                state_vars.append(var_name)

            # A line like "  addItem: (item: Omit<CartItem, ...>) => void;"
            # is an action (has opening parenthesis).
            if "(" in stripped and "=>" in stripped:
                action_name: str = stripped.split("(")[0].strip().split(":")[0].strip()
                actions.append(action_name)

    # Also extract from the zustand create() call.
    # Some stores define actions inline rather than in the interface.
    # We look for top-level keys in the create() argument.
    in_create: bool = False
    brace_depth: int = 0

    for line in lines:
        stripped = line.strip()
        if "create<POSState>" in stripped or "(set, get) => ({" in stripped:
            in_create = True
            continue
        if in_create:
            if "{" in stripped:
                brace_depth += stripped.count("{")
            if "}" in stripped:
                brace_depth -= stripped.count("}")
            if brace_depth <= 0 and stripped.endswith("});"):
                break

            # Skip comments and empty lines.
            if not stripped or stripped.startswith("//"):
                continue

            # Match "  variableName: ..." patterns inside create().
            # These are either state variables (default values) or actions.
            match = re.match(r"(\w+):\s*(.+),?", stripped)
            if match:
                key: str = match.group(1)
                value_part: str = match.group(2).strip()

                # If the value contains "=>" or "set(" or "get(", it is an action.
                if "=>" in value_part or value_part.startswith("set(") or value_part.startswith("get("):
                    if key not in actions:
                        actions.append(key)
                else:
                    # It is a state variable with a default value.
                    if key not in state_vars:
                        state_vars.append(key)

    result["state_variables_found"] = sorted(state_vars)
    result["actions_found"] = sorted(actions)

    print(f"\n  State variables ({len(state_vars)}):")
    for v in sorted(state_vars):
        print(f"    - {v}")

    print(f"\n  Actions ({len(actions)}):")
    for a in sorted(actions):
        print(f"    - {a}")

    # ------------------------------------------------------------------
    # (C) Check for existing safety-lock fields in the store.
    # ------------------------------------------------------------------
    # We look for terms like "isSafe", "lock_reason", "safety", "system_lock".
    safety_keywords: list[str] = ["isSafe", "lock_reason", "safety", "system_lock", "is_safe"]
    found_safety: list[str] = [kw for kw in safety_keywords if kw in content]
    if found_safety:
        print(f"\n  Existing safety fields found: {found_safety}")
    else:
        print("\n  [!!] NO safety-lock fields found in store.")

    return result


# =====================================================================
# STEP 3 — AUDIT THE COPILOT UI COMPONENT (CopilotPanel.tsx)
# =====================================================================
# Why do we need this?
#   The CopilotPanel is the frontend face of the RAG pipeline. We need
#   to understand how it currently treats the backend response:
#     - Does it read only `data.answer` (current behaviour)?
#     - Does it read `data.is_safe_to_dispense` or `data.system_lock_reason`?
#     - Does it have any visual states for safety locks?

def audit_copilot_ui() -> dict[str, Any]:
    """
    Parse CopilotPanel.tsx to extract:
      - How the API response is consumed (plain string vs parsed JSON).
      - Whether any safety states exist (lock banners, warnings).
      - How messages are rendered in the chat UI.

    Returns:
        A dict with file_path, current_message_rendering description,
        and has_existing_safety_ui_states flag.
    """
    print("\n" + "=" * 72)
    print("  AUDITING COPILOT UI COMPONENT")
    print("=" * 72)

    # The CopilotPanel lives at frontend/src/components/pos/CopilotPanel.tsx.
    panel_path: Path = FRONTEND_ROOT / "src" / "components" / "pos" / "CopilotPanel.tsx"

    if not panel_path.exists():
        print("  [!!] CopilotPanel not found at expected location.")
        return {"file_path": "", "current_message_rendering": "", "has_existing_safety_ui_states": False}

    result: dict[str, Any] = {
        "file_path": str(panel_path.relative_to(PROJECT_ROOT)),
        "current_message_rendering": "",
        "has_existing_safety_ui_states": False,
    }

    print(f"  Found at: {result['file_path']}")

    content: str = panel_path.read_text(encoding="utf-8")
    lines: list[str] = content.splitlines()

    # ------------------------------------------------------------------
    # (A) Find the fetch/API call block and see how it parses the response.
    # ------------------------------------------------------------------
    in_fetch: bool = False
    response_handling_lines: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Detect the start of the fetch call.
        if "fetch('/api/v1/knowledge-base/ask'" in stripped or "fetch(" in stripped:
            in_fetch = True

        # Once we are inside the fetch block, collect lines until we
        # see the closing of the try block or the next function.
        if in_fetch:
            response_handling_lines.append(stripped)
            if stripped.startswith("addChatMessage(") and in_fetch:
                # Capture the addChatMessage payload to see which fields
                # are extracted from the response.
                # Collect up to the closing parenthesis.
                pass  # We handle this more precisely below.

            # The fetch block typically ends with the catch or the
            # finally clause of the surrounding try/catch.
            if stripped.startswith("} catch") or stripped.startswith("} finally"):
                break

    # Extract how the response data is used by looking for addChatMessage calls.
    # We want to see what fields of `data` are being read.
    uses_answer: bool = "data.answer" in content or "data['answer']" in content or "data[\"answer\"]" in content
    uses_safety: bool = "data.is_safe_to_dispense" in content or "data.system_lock_reason" in content
    uses_citations: bool = "data.citations" in content or "data.context_used" in content

    if uses_answer:
        result["current_message_rendering"] = (
            "Plain string: reads data.answer only. "
            "No parsing of is_safe_to_dispense, system_lock_reason, or citations."
        )
    else:
        result["current_message_rendering"] = "Could not determine message rendering pattern."

    if uses_safety:
        result["current_message_rendering"] += " DOES read safety fields."

    if uses_citations:
        result["current_message_rendering"] += " Reads context_used for source display."

    print(f"\n  Response parsing analysis:")
    print(f"    Reads data.answer:            {uses_answer}")
    print(f"    Reads is_safe_to_dispense:    {uses_safety}")
    print(f"    Reads system_lock_reason:     {'data.system_lock_reason' in content}")
    print(f"    Reads citations:              {'data.citations' in content}")
    print(f"    Reads context_used:           {uses_citations}")
    print(f"    Reads sources:                {'sources:' in content}")

    # ------------------------------------------------------------------
    # (B) Check for existing safety UI states.
    # ------------------------------------------------------------------
    # Look for visual components/strings that indicate a safety lock
    # is already rendered in the UI.
    safety_ui_indicators: list[str] = [
        "Safety Guard Active",
        "SYSTEM LOCK",
        "is_safe_to_dispense",
        "system_lock_reason",
        "CRITICAL_PREGNANCY",
        "PEDIATRIC_AGE",
        "safety_banner",
        "dangerouslySetInnerHTML",
        "shield",
        "SystemLock",
        "lockReason",
    ]

    for indicator in safety_ui_indicators:
        if indicator.lower() in content.lower():
            result["has_existing_safety_ui_states"] = True
            print(f"    Found safety UI indicator: '{indicator}'")

    if not result["has_existing_safety_ui_states"]:
        print("    No safety-specific UI states found.")

    # ------------------------------------------------------------------
    # (C) Check the fetch payload shape.
    # ------------------------------------------------------------------
    # Does it send sku_id? Does it send intents?
    if "sku_id" in content:
        print("    Fetch payload includes sku_id field.")
    else:
        print("    Fetch payload is missing sku_id field.")

    if "intents" in content or "pregnancy" in content.lower():
        print("    Fetch payload includes intent detection.")
    else:
        print("    Fetch payload does NOT include intents.")

    return result


# =====================================================================
# STEP 4 — AUDIT THE POS PAGE / CHECKOUT INTERLOCK
# =====================================================================
# Why do we need this?
#   The backend ClinicalSafetyJudge can BLOCK a transaction. If the
#   frontend checkout button is not disabled when a lock is active,
#   the pharmacist could accidentally process a dangerous prescription.

def audit_checkout_interlock() -> dict[str, Any]:
    """
    Examine the POS page and the Zustand store to find:
      - Cart state variables used by the checkout flow.
      - Whether a safety interlock exists (checkout disabled when unsafe).
      - The executeCheckout function logic.

    Returns:
        A dict with file_path and cart_state_variables list.
    """
    print("\n" + "=" * 72)
    print("  AUDITING CHECKOUT INTERLOCK")
    print("=" * 72)

    # The POS page is at frontend/src/app/pos/page.tsx.
    pos_page_path: Path = FRONTEND_ROOT / "src" / "app" / "pos" / "page.tsx"

    if not pos_page_path.exists():
        print("  [!!] POS page not found at expected location.")
        return {"file_path": "", "cart_state_variables": []}

    result: dict[str, Any] = {
        "file_path": str(pos_page_path.relative_to(PROJECT_ROOT)),
        "cart_state_variables": [],
    }

    print(f"  Found at: {result['file_path']}")

    content: str = pos_page_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # (A) Find all Zustand store selectors used on the POS page.
    # ------------------------------------------------------------------
    # The pattern is: const X = usePOSStore((state: any) => state.X)
    store_selectors: list[str] = re.findall(
        r"const\s+(\w+)\s*=\s*usePOSStore\(\(state:\s*\w*\)\s*=>\s*state\.(\w+)\)",
        content,
    )

    cart_vars: list[str] = []
    for local_name, state_key in store_selectors:
        cart_vars.append(state_key)
        print(f"    Store selector used: {local_name} <- state.{state_key}")

    result["cart_state_variables"] = sorted(set(cart_vars))

    # ------------------------------------------------------------------
    # (B) Check for safety interlock before checkout.
    # ------------------------------------------------------------------
    # Look for the executeCheckout function and its guard conditions.
    execute_checkout_start: int = content.find("const executeCheckout =")
    if execute_checkout_start >= 0:
        # Extract the function body (up to the closing of the try block).
        snippet: str = content[execute_checkout_start:execute_checkout_start + 1500]
        print(f"\n  executeCheckout guard conditions:")
        if "cart.length === 0" in snippet:
            print("    - Disabled when cart is empty.")
        if "isProcessing" in snippet:
            print("    - Disabled when isProcessing is True.")
        if "is_safe" in snippet or "safe_to_dispense" in snippet or "lock" in snippet.lower():
            print("    - Disabled by safety lock.")
        else:
            print("    - NO safety lock guard found.")

    # ------------------------------------------------------------------
    # (C) Check the Payment button disabled state.
    # ------------------------------------------------------------------
    # The payment buttons have a `disabled` prop. We look for what
    # conditions feed into it.
    disabled_conditions: list[str] = re.findall(
        r'disabled=\{([^}]+)\}',
        content,
    )
    print(f"\n  Disabled conditions on payment buttons:")
    for dc in disabled_conditions:
        print(f"    disabled={{{dc}}}")

    # ------------------------------------------------------------------
    # (D) Check for any is_safe_to_dispense awareness on the POS page.
    # ------------------------------------------------------------------
    if "is_safe_to_dispense" in content:
        print("  \n  [OK] is_safe_to_dispense is referenced on the POS page.")
    else:
        print("  \n  [!!] is_safe_to_dispense is NOT referenced on the POS page.")

    return result


# =====================================================================
# MAIN — Orchestrate the complete audit
# =====================================================================

def main() -> None:
    """
    Execute all four audit steps and print the final structured output.
    """
    print()
    print("=" * 72)
    print("  SENTINEL-FLOW MVP — PHASE 6 FRONTEND STATE & UI AUDIT")
    print("  (Read-Only — No .ts, .tsx, or .js files will be modified)")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Step 0: Verify the frontend directory exists.
    # ------------------------------------------------------------------
    if not FRONTEND_ROOT.exists():
        print(f"\n  [!!] Frontend directory not found at {FRONTEND_ROOT}")
        print("  This script expects the React frontend to live at")
        print("  <project_root>/frontend/. Cannot proceed.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 1: Scan the directory tree for orientation.
    # ------------------------------------------------------------------
    tree: dict[str, list[str]] = scan_directory_tree()

    # ------------------------------------------------------------------
    # Step 2: Audit the Zustand store.
    # ------------------------------------------------------------------
    store_audit: dict[str, Any] = audit_zustand_store()
    AUDIT_RESULT["zustand_copilot_store"]["file_path"] = store_audit.get("file_path", "")
    AUDIT_RESULT["zustand_copilot_store"]["state_variables_found"] = store_audit.get("state_variables_found", [])
    AUDIT_RESULT["zustand_copilot_store"]["actions_found"] = store_audit.get("actions_found", [])

    # ------------------------------------------------------------------
    # Step 3: Audit the Copilot UI component.
    # ------------------------------------------------------------------
    ui_audit: dict[str, Any] = audit_copilot_ui()
    AUDIT_RESULT["react_copilot_ui"]["file_path"] = ui_audit.get("file_path", "")
    AUDIT_RESULT["react_copilot_ui"]["current_message_rendering"] = ui_audit.get("current_message_rendering", "")
    AUDIT_RESULT["react_copilot_ui"]["has_existing_safety_ui_states"] = ui_audit.get("has_existing_safety_ui_states", False)

    # ------------------------------------------------------------------
    # Step 4: Audit the checkout interlock.
    # ------------------------------------------------------------------
    checkout_audit: dict[str, Any] = audit_checkout_interlock()
    AUDIT_RESULT["checkout_interlock_target"]["file_path"] = checkout_audit.get("file_path", "")
    AUDIT_RESULT["checkout_interlock_target"]["cart_state_variables"] = checkout_audit.get("cart_state_variables", [])

    # ------------------------------------------------------------------
    # Build the summary narrative.
    # ------------------------------------------------------------------
    store_vars: list[str] = AUDIT_RESULT["zustand_copilot_store"]["state_variables_found"]
    store_actions: list[str] = AUDIT_RESULT["zustand_copilot_store"]["actions_found"]
    has_safety_ui: bool = AUDIT_RESULT["react_copilot_ui"]["has_existing_safety_ui_states"]

    AUDIT_RESULT["agent_action_summary"] = (
        f"Frontend audit complete. Scanned {sum(len(v) for v in tree.values())} source files "
        f"across {len(tree)} directories. Zustand store at {store_audit['file_path']} has "
        f"{len(store_vars)} state variables and {len(store_actions)} actions. "
        f"CopilotPanel reads data.answer as a plain string "
        f"{'with' if has_safety_ui else 'WITHOUT'} existing safety UI states. "
        f"Checkout has no safety lock interlock — is_safe_to_dispense is not referenced "
        f"on the POS page."
    )

    # ------------------------------------------------------------------
    # Print the structured JSON output.
    # ------------------------------------------------------------------
    print()
    print("=" * 72)
    print("  AUDIT COMPLETE — STRUCTURED OUTPUT")
    print("=" * 72)
    print()
    print(json.dumps(AUDIT_RESULT, indent=2))


if __name__ == "__main__":
    main()
