import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from groq import Groq
import websockets
import uiautomation as auto

# ---------------------------------------------------------------------------
# Roles we consider actionable in the UIA control tree.
# We focus on Buttons since that's what Calculator is made of.
# ---------------------------------------------------------------------------
ACTIONABLE_CONTROL_TYPES = {"ButtonControl", "MenuItemControl"}

# ---------------------------------------------------------------------------
# System prompt — constrains the LLM to deterministic JSON-only output
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a deterministic desktop automation agent. You will be provided "
    "with a JSON array of UI controls from a Windows desktop application. "
    "You must output a JSON object with a single key 'actions' that contains "
    "an array of actions to achieve the user's objective. The only allowed "
    "action is 'click'. Reference controls ONLY by their 'id'. "
    "You must respond in pure JSON."
)

# ---------------------------------------------------------------------------
# WebSocket — identical broadcast setup to agent.py
# ---------------------------------------------------------------------------
CONNECTED_CLIENTS = set()


async def ws_handler(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[WS] Client connected. Total: {len(CONNECTED_CLIENTS)}")
    try:
        async for _ in websocket:
            pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        print(f"[WS] Client disconnected. Total: {len(CONNECTED_CLIENTS)}")


async def broadcast(message: str):
    """Send a timestamped log to all connected dashboard clients AND print locally."""
    print(message)
    if not CONNECTED_CLIENTS:
        return
    payload = json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log": message,
    })
    stale = set()
    for ws in CONNECTED_CLIENTS:
        try:
            await ws.send(payload)
        except websockets.exceptions.ConnectionClosed:
            stale.add(ws)
    CONNECTED_CLIENTS.difference_update(stale)


# ============================= OBSERVE =====================================

def walk_control_tree(control, counter, sanitized, control_map, depth=0):
    """
    Recursively walks the UIA control tree starting from *control*.

    For every actionable control (Button, MenuItem):
      - A sanitized dict {id, type, name} is appended to *sanitized*.
      - The live UIA Control object is stored in *control_map* keyed by id.

    Args:
        control:     The current uiautomation.Control object.
        counter:     Mutable [int] for assigning sequential ids.
        sanitized:   List of cleaned controls sent to the LLM.
        control_map: Dict mapping id → live Control object (kept in memory).
        depth:       Current recursion depth (for safety).
    """
    if depth > 15:
        return  # Prevent infinite recursion in deep trees

    control_type = control.ControlTypeName

    if control_type in ACTIONABLE_CONTROL_TYPES:
        name = control.Name
        # Skip unnamed or empty controls — they're usually decorative
        if name and name.strip():
            current_id = counter[0]
            sanitized.append({
                "id": current_id,
                "type": control_type.replace("Control", "").lower(),
                "name": name,
            })
            control_map[current_id] = control
            counter[0] += 1

    # Recurse into children
    for child in control.GetChildren():
        walk_control_tree(child, counter, sanitized, control_map, depth + 1)


# ============================== THINK ======================================

async def call_llm(client, sanitized_tree):
    """Send the sanitized control tree to Groq and return the parsed action plan."""
    sanitized_json = json.dumps(sanitized_tree, indent=2)
    user_prompt = (
        f"Here is the Windows Calculator UI: {sanitized_json}. "
        "Please calculate 7 + 5."
    )

    await broadcast("[THINK] Sending sanitized control tree to Groq LLM...")
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    raw = completion.choices[0].message.content
    await broadcast(f"[THINK] Raw LLM response:\n{raw}")
    return json.loads(raw)


# =============================== ACT ======================================

async def execute_click(control, name):
    """
    Click a UIA control deterministically.
    Tries InvokePattern first (most reliable), falls back to Click().
    """
    try:
        # InvokePattern is the most deterministic way to activate a button —
        # it fires the button's action without needing coordinates at all.
        invoke = control.GetInvokePattern()
        if invoke:
            invoke.Invoke()
            return
    except Exception:
        pass

    # Fallback: use the UIA Click which internally resolves the control's
    # bounding rect and clicks its center. Still deterministic (no pixel guessing).
    control.Click()


# =============================== MAIN ======================================

async def main():
    # Start WebSocket server
    ws_server = await websockets.serve(ws_handler, "localhost", 8765)
    print("[WS] Server started on ws://localhost:8765")
    print("[WS] Open the audit dashboard, waiting 3s for connection...")
    await asyncio.sleep(3)

    # Initialize Groq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        await broadcast("Error: GROQ_API_KEY environment variable is not set.")
        ws_server.close()
        return
    groq_client = Groq(api_key=api_key)

    # ── [LAUNCH] ──────────────────────────────────────────────
    await broadcast("[LAUNCH] Opening Windows Calculator...")
    subprocess.Popen("calc.exe")
    # Give the UWP app a moment to fully render
    await asyncio.sleep(2)

    # Hook into the Calculator window via UIA
    await broadcast("[LAUNCH] Searching for Calculator window...")
    calc_window = auto.WindowControl(searchDepth=1, Name="Calculator")

    if not calc_window.Exists(maxSearchSeconds=5):
        await broadcast("[LAUNCH] ✖ Could not find Calculator window. Aborting.")
        ws_server.close()
        return

    await broadcast("[LAUNCH] Calculator window found. Bringing to foreground...")
    calc_window.SetFocus()
    await asyncio.sleep(0.5)

    # ── [OBSERVE] ─────────────────────────────────────────────
    await broadcast("[OBSERVE] Walking the UIA control tree...")
    sanitized_tree = []
    control_map = {}   # id → live UIA Control object (in-memory only)
    counter = [1]

    walk_control_tree(calc_window, counter, sanitized_tree, control_map)

    await broadcast(f"[OBSERVE] Extracted {len(sanitized_tree)} actionable controls.")
    await broadcast(f"[OBSERVE] Sanitized tree:\n{json.dumps(sanitized_tree, indent=2)}")

    # ── [THINK] ───────────────────────────────────────────────
    try:
        plan = await call_llm(groq_client, sanitized_tree)
    except Exception as e:
        await broadcast(f"[THINK] LLM call failed: {e}")
        ws_server.close()
        return

    actions = plan.get("actions", [])
    if not actions:
        await broadcast("[THINK] LLM returned no actions.")
        ws_server.close()
        return

    await broadcast(f"[THINK] LLM returned {len(actions)} action(s).")

    # ── [ACT] ─────────────────────────────────────────────────
    for i, action in enumerate(actions):
        element_id = action.get("id")
        control = control_map.get(element_id)

        if control is None:
            await broadcast(f"[ACT] ⚠ No control found for id {element_id}. Skipping.")
            continue

        control_name = control.Name
        await broadcast(f"[ACT] Action {i+1}/{len(actions)}: click '{control_name}' (id={element_id})")

        try:
            await execute_click(control, control_name)
            await broadcast(f"  ✓ Clicked '{control_name}' successfully.")
        except Exception as e:
            await broadcast(f"  ✖ Error clicking '{control_name}': {e}")

        # Brief pause so we can visually track each press
        await asyncio.sleep(1)

    await broadcast("✅ All actions executed.")

    # Wait so we can see the result on the calculator display
    await broadcast("Waiting 5 seconds to observe the result...")
    await asyncio.sleep(5)

    # Close Calculator
    await broadcast("[CLEANUP] Closing Calculator...")
    try:
        calc_window.GetWindowPattern().Close()
    except Exception:
        os.system("taskkill /f /im CalculatorApp.exe >nul 2>&1")
    await broadcast("Calculator closed.")

    ws_server.close()
    await ws_server.wait_closed()
    print("[WS] Server shut down.")


if __name__ == "__main__":
    asyncio.run(main())
