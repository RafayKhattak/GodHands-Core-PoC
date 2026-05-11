# ⚡ GodHands-Core-PoC: Deterministic Execution Engine

A proof-of-concept AI agent infrastructure that abandons fragile vision-based (X/Y coordinate) clicking in favor of **OS-level memory handles** for zero-fail reliability across both Web and Native Desktop applications.

Built as a technical exploration of the execution layer required for modern, enterprise-grade AI agents.

---

### 🌐 The Web Agent (Chrome CDP)

Bypasses the HTML DOM entirely. Extracts the raw Accessibility Tree (AXTree) via the Chrome DevTools Protocol, maps intents via Groq (Llama-3.3-70b), and executes directly using ephemeral `backendDOMNodeId` memory pointers.

https://github.com/user-attachments/assets/7d79bb01-f160-4793-99c8-fc457bebd6a0

### 🖥️ The Desktop Agent (Windows UIA)

Proves the "Universal App Bridge" concept. Uses the Windows `UIAutomation` API to hook into native legacy desktop apps (e.g., `calc.exe`). Extracts the UIA control tree and triggers actions natively via `InvokePattern`—zero pixel-guessing required.

> **[🎥 Insert Loom Video Link Here: Desktop Agent solving math on Windows Calculator]**

---

## 🧠 The Architecture

Standard AI web agents fail because they rely on computer vision (pixels) or massive, noisy HTML DOMs. This project operates on a strict **OBSERVE → THINK → ACT** loop using semantic OS trees.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        OBSERVE → THINK → ACT                            │
│                                                                         │
│  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐     │
│  │    [OBSERVE]    │    │     [THINK]     │    │      [ACT]       │     │
│  │                 │    │                 │    │                  │     │
│  │  Chrome CDP     │───▶│  Groq LLM      │───▶│  CDP Commands    │     │
│  │  AXTree Extract │    │  llama-3.3-70b  │    │  DOM.focus       │     │
│  │       or        │    │                 │    │  Input.insert    │     │
│  │  Windows UIA    │    │  JSON Plan      │    │       or         │     │
│  │  Control Tree   │    │{actions: [...]} │    │  UIA Invoke      │     │
│  └─────────────────┘    └─────────────────┘    └──────────────────┘     │
│           │                                               │             │
│           └──────────── WebSocket Telemetry ──────────────┘             │
│                              ▼                                          │
│                    ┌──────────────────┐                                 │
│                    │  Audit Dashboard │                                 │
│                    │  ws://localhost  │                                 │
│                    │     :8765        │                                 │
│                    └──────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1. [OBSERVE] The Extraction Layer

| Platform | Method | What It Extracts |
|----------|--------|-----------------|
| **Web** | Playwright → raw CDP session → `Accessibility.getFullAXTree` | The OS-level screen-reader tree from Chromium |
| **Desktop** | `uiautomation` → `WindowControl.GetChildren()` recursive walk | The native Windows UIA Control Tree |

**Result:** A highly compressed, semantic JSON map of **only actionable elements** (Buttons, Textboxes, Links) paired with hidden native memory handles.

```json
[
    {"id": 1, "role": "textbox", "name": "", "description": "", "value": ""},
    {"id": 2, "role": "textbox", "name": "", "description": "", "value": ""},
    {"id": 3, "role": "button",  "name": "login", "description": "", "value": ""}
]
```

> ☝️ Notice: no `backendDOMNodeId`, no HTML, no CSS selectors. The LLM sees a clean, minimal interface. The memory pointers are kept in a private dictionary that never leaves the process.

### 2. [THINK] The Decision Engine

- **LLM:** Groq (`llama-3.3-70b-versatile`) at `temperature=0.0` for deterministic output.
- **Input:** The sanitized tree (stripped of backend IDs to save context window and prevent hallucination).
- **Output:** A strict JSON execution plan referencing simple sequential IDs.
- **Constraint:** `response_format={"type": "json_object"}` forces the model to output valid JSON — no markdown wrappers, no explanations.

```json
{
    "actions": [
        {"action": "type", "id": 1, "value": "rafaykhattak123"},
        {"action": "type", "id": 2, "value": "fast1234"},
        {"action": "click", "id": 3}
    ]
}
```

### 3. [ACT] The Deterministic Execution

The engine maps the LLM's chosen IDs back to the **live memory pointers** (`backendDOMNodeId` or native `Control` objects) and triggers native OS/Browser actions directly in memory.

| Platform | Click Implementation | Type Implementation |
|----------|---------------------|---------------------|
| **Web** | `DOM.scrollIntoViewIfNeeded` → `DOM.getBoxModel` → `Input.dispatchMouseEvent` (press + release) | `DOM.focus` (by `backendNodeId`) → `Input.insertText` |
| **Desktop** | `InvokePattern.Invoke()` (native button activation, zero coordinates) | N/A for Calculator |

**No mouse movements. No coordinate math. No screen-resizing failures.**

### 4. [TELEMETRY] Real-Time Audit Trail

Both agents broadcast their internal state via WebSockets (`ws://localhost:8765`) to a local audit dashboard, providing a comprehensive, immutable log of the agent's decision-making process.

The dashboard features:
- 🟢 Live connection status indicator
- 📊 Per-phase message counters (OBSERVE / THINK / ACT)
- 🖥️ Terminal-style log viewer with phase-colored messages and auto-scroll
- 🔄 Auto-reconnect with 2-second retry

---

## 📂 Project Structure

```
GodHands YC F26/
├── agent.py                  # Unified web agent (OBSERVE → THINK → ACT + WebSocket)
├── desktop_agent.py          # Native Windows desktop agent (Calculator automation)
├── extract_ax_tree.py        # Standalone AXTree extraction script
├── llm_brain.py              # Standalone LLM planning script
├── executor.py               # Standalone CDP execution script
├── audit-dashboard/
│   └── index.html            # Real-time audit trail dashboard (dark mode)
├── ax_tree.json              # Generated: extracted accessibility tree
├── execution_plan.json       # Generated: LLM execution plan
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Windows OS** (required for `desktop_agent.py` to interact with native `calc.exe`)
- **Groq API Key** (for sub-second LLM inference — [get one free](https://console.groq.com))

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/GodHands-Core-PoC.git
   cd GodHands-Core-PoC
   ```

2. **Install dependencies:**
   ```bash
   pip install playwright websockets groq uiautomation
   playwright install chromium
   ```

3. **Set your Groq API Key:**
   ```powershell
   # Windows (PowerShell)
   $env:GROQ_API_KEY="your_api_key_here"
   ```

---

### Running the PoC

#### 1️⃣ Start the Audit Dashboard

Open `audit-dashboard/index.html` in your browser. It will immediately begin listening on `ws://localhost:8765` for agent telemetry.

```bash
start audit-dashboard\index.html
```

#### 2️⃣ Run the Web Agent

Opens a Chromium browser, extracts the AXTree from the Hacker News login page, asks the LLM for a plan, and deterministically types credentials and clicks "login".

```bash
python agent.py
```

#### 3️⃣ Run the Desktop Agent

Opens the native Windows Calculator, extracts the UIA control tree, asks the LLM how to calculate `7 + 5`, and presses the buttons natively without using the mouse.

```bash
python desktop_agent.py
```

---

## 🔑 Why This Matters

| Approach | Reliability | Speed | Scales Across Apps? |
|----------|-------------|-------|---------------------|
| **Vision/Pixel AI** (screenshot → GPT-4V → X/Y click) | ❌ Breaks on resize, DPI changes, theme changes | 🐢 Slow (image encoding + large model) | ❌ Needs retraining per app |
| **HTML DOM Parsing** (BeautifulSoup, CSS selectors) | ⚠️ Fragile to DOM changes | ⚡ Fast | ❌ Web only |
| **This Project (OS Accessibility Trees)** | ✅ Memory pointers are absolute | ⚡ Fast (text-only LLM) | ✅ Web + Desktop + Mobile* |

> *Mobile: Android has `AccessibilityNodeInfo`, iOS has `XCUIElement` — the same architecture applies.

The accessibility tree is the **universal interface** that every OS provides for screen readers. By hijacking it for automation, we get a deterministic, cross-platform execution layer that doesn't care about pixels, themes, screen sizes, or DPI settings.

---

## 🛠️ Technical Deep Dive

### Why `backendDOMNodeId` and not CSS selectors?

CSS selectors are **syntactic** — they describe the structure of HTML. If a developer adds a wrapper `<div>`, your selector breaks. `backendDOMNodeId` is a **memory pointer** assigned by Chrome's rendering engine to the actual DOM node object in memory. It's immune to structural changes during a session.

### Why strip IDs before sending to the LLM?

Two reasons:
1. **Context window efficiency:** `backendDOMNodeId` values are large integers that waste tokens.
2. **Anti-hallucination:** If the LLM sees raw memory addresses, it may fabricate plausible-looking but invalid IDs. By using simple sequential integers (1, 2, 3...), the LLM can only reference elements that actually exist.

### Why `InvokePattern` for Desktop?

`InvokePattern` is the Windows UIAutomation pattern that directly fires a button's programmatic action handler. It's the exact same mechanism that Windows Narrator (screen reader) uses. Unlike `SendInput` or `mouse_event`, it doesn't require the button to be visible, unoccluded, or at specific coordinates.

---

## 👨‍💻 About the Developer

I'm **Rafay Khattak**, a recent Computer Science graduate from **FAST NUCES**, focusing on AI agent infrastructure, systems engineering, and deterministic automation.

I built this over a weekend to demonstrate the massive reliability gap between probabilistic vision agents and deterministic OS-level execution.

**If you are building the execution layer for the next generation of AI agents, I'd love to talk.**

[LinkedIn](https://www.linkedin.com/in/rafaykhattak/) 

---

<p align="center">
  <sub>Built with ⚡ by a systems engineer who believes AI agents should never miss a click.</sub>
</p>
