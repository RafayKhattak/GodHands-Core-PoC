import asyncio
import json
import os
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from groq import Groq
import websockets

ACTIONABLE_ROLES = {
    "button", "textbox", "link", "combobox", "checkbox",
    "searchbox", "radio", "switch", "slider", "menuitem",
    "menuitemcheckbox", "menuitemradio", "spinbutton",
    "treeitem", "listbox", "option",
}

SYSTEM_PROMPT = (
    "You are a deterministic UI automation agent. You will be provided with a "
    "JSON array of UI elements. You must output a JSON object with a single key "
    "'actions' that contains an array of actions to achieve the user's objective. "
    "Allowed actions are 'click' and 'type'. For 'type', you must include the "
    "'value'. Reference elements ONLY by their 'id'. You must respond in pure JSON."
)

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


def extract_node_value(prop):
    if not prop:
        return ""
    if isinstance(prop, dict) and "value" in prop:
        inner = prop["value"]
        if isinstance(inner, dict) and "value" in inner:
            return inner["value"]
        return inner
    return ""


def parse_ax_tree(node_id, nodes_map, counter, sanitized, mapping):
    node = nodes_map.get(node_id)
    if not node:
        return
    role_obj = node.get("role", {})
    role = role_obj.get("value", "") if isinstance(role_obj, dict) else ""
    if role in ACTIONABLE_ROLES and not node.get("ignored", False):
        name_obj = node.get("name", {})
        name = name_obj.get("value", "") if isinstance(name_obj, dict) else ""
        props_list = node.get("properties", [])
        props_map = {
            p.get("name"): extract_node_value(p.get("value"))
            for p in props_list if "name" in p
        }
        current_id = counter[0]
        sanitized.append({
            "id": current_id, "role": role, "name": name,
            "description": props_map.get("description", ""),
            "value": props_map.get("value", ""),
        })
        backend_dom_node_id = node.get("backendDOMNodeId")
        if backend_dom_node_id is not None:
            mapping[current_id] = backend_dom_node_id
        counter[0] += 1
    for child_id in node.get("childIds", []):
        parse_ax_tree(child_id, nodes_map, counter, sanitized, mapping)


async def call_llm(client, sanitized_tree):
    sanitized_json = json.dumps(sanitized_tree, indent=2)
    user_prompt = (
        f"Here is the UI: {sanitized_json}. "
        "Please log me in with the username 'rafaykhattak123' and password 'fast1234'."
    )
    await broadcast("[THINK] Sending sanitized AXTree to Groq LLM...")
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


async def execute_action(client, action, mapping):
    action_type = action.get("action")
    element_id = action.get("id")
    backend_id = mapping.get(element_id)
    if backend_id is None:
        await broadcast(f"  ⚠ No backendDOMNodeId for id {element_id}. Skipping.")
        return

    if action_type == "type":
        value = action.get("value", "")
        await broadcast(f"  Focusing element (backendNodeId={backend_id})...")
        await client.send("DOM.focus", {"backendNodeId": backend_id})
        await broadcast(f"  Typing: '{value}'")
        await client.send("Input.insertText", {"text": value})

    elif action_type == "click":
        await broadcast(f"  Scrolling into view (backendNodeId={backend_id})...")
        await client.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})
        await broadcast(f"  Getting box model...")
        box_resp = await client.send("DOM.getBoxModel", {"backendNodeId": backend_id})
        quad = box_resp.get("model", {}).get("content", [])
        if len(quad) < 8:
            await broadcast(f"  ⚠ Invalid quad: {quad}. Cannot click.")
            return
        x = sum(quad[0::2]) / 4
        y = sum(quad[1::2]) / 4
        await broadcast(f"  Clicking at center ({x:.1f}, {y:.1f})...")
        await client.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        await asyncio.sleep(0.1)
        await client.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
    else:
        await broadcast(f"  ⚠ Unknown action type: '{action_type}'. Skipping.")


async def main():
    # Start WebSocket server on ws://localhost:8765
    ws_server = await websockets.serve(ws_handler, "localhost", 8765)
    print("[WS] Server started on ws://localhost:8765")
    print("[WS] Open the audit dashboard, then waiting 3s for connection...")
    await asyncio.sleep(3)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        await broadcast("Error: GROQ_API_KEY environment variable is not set.")
        ws_server.close()
        return
    groq_client = Groq(api_key=api_key)

    async with async_playwright() as p:
        await broadcast("Launching Chromium (non-headless)...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        url = "https://news.ycombinator.com/login"
        await broadcast(f"Navigating to {url}...")
        await page.goto(url, wait_until="networkidle")

        await broadcast("Waiting for login form to be rendered and attached...")
        await page.wait_for_selector('form[action="login"]', state="attached", timeout=5000)
        await broadcast("Login form is ready.")

        cdp = await page.context.new_cdp_session(page)
        await cdp.send("DOM.enable")

        # [OBSERVE]
        await broadcast("[OBSERVE] Fetching full Accessibility Tree via CDP...")
        response = await cdp.send("Accessibility.getFullAXTree")
        nodes_list = response.get("nodes", [])
        if not nodes_list:
            await broadcast("[OBSERVE] Failed to capture the accessibility tree.")
            await browser.close()
            ws_server.close()
            return

        nodes_map = {str(n["nodeId"]): n for n in nodes_list}
        root_candidates = [n for n in nodes_list if "parentId" not in n]
        root_id = str(root_candidates[0]["nodeId"]) if root_candidates else str(nodes_list[0]["nodeId"])

        sanitized_tree = []
        node_mapping = {}
        counter = [1]
        parse_ax_tree(root_id, nodes_map, counter, sanitized_tree, node_mapping)

        await broadcast(f"[OBSERVE] Extracted {len(sanitized_tree)} actionable nodes.")
        await broadcast(f"[OBSERVE] Sanitized tree:\n{json.dumps(sanitized_tree, indent=2)}")

        # [THINK]
        try:
            plan = await call_llm(groq_client, sanitized_tree)
        except Exception as e:
            await broadcast(f"[THINK] LLM call failed: {e}")
            await browser.close()
            ws_server.close()
            return

        actions = plan.get("actions", [])
        if not actions:
            await broadcast("[THINK] LLM returned no actions.")
            await browser.close()
            ws_server.close()
            return

        await broadcast(f"[THINK] LLM returned {len(actions)} action(s).")

        # [ACT]
        for i, action in enumerate(actions):
            await broadcast(f"[ACT] Action {i+1}/{len(actions)}: {action.get('action')} on id {action.get('id')}")
            try:
                await execute_action(cdp, action, node_mapping)
            except Exception as e:
                await broadcast(f"  ✖ Error: {e}")
            await asyncio.sleep(1)

        await broadcast("✅ All actions executed.")
        await broadcast("Waiting 10 seconds to observe the result...")
        await asyncio.sleep(10)

        await browser.close()
        await broadcast("Browser closed.")

    ws_server.close()
    await ws_server.wait_closed()
    print("[WS] Server shut down.")


if __name__ == "__main__":
    asyncio.run(main())
