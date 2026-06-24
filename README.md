# xCaptcha Research: Deobfuscation, API Reverse Engineering & Solving

> **Security research** documenting xCaptcha's image obfuscation scheme, API protocol, critical vulnerabilities, and full solving pipeline — discovered via proxy-based traffic interception.

## Table of Contents

- [Overview](#overview)
- [BREAKTHROUGH: Proxy-Based API Reverse Engineering](#breakthrough-proxy-based-api-reverse-engineering)
- [Challenge Types](#challenge-types)
- [Image Obfuscation](#image-obfuscation)
- [API Protocol (Full)](#api-protocol-full)
- [API Vulnerabilities](#api-vulnerabilities)
- [Solving Each Type](#solving-each-type)
- [Usage](#usage)
- [Architecture](#architecture)

---

## Overview

xCaptcha is a CAPTCHA service (xcaptcha.com) offering four challenge types. This research documents:

1. **Image obfuscation** — a trivially reversible byte substitution applied to PNG data before base64 encoding
2. **API answer leakage** — the `/task` endpoint returns ground-truth coordinates and answer hashes for custom/empty types
3. **Full API protocol** — discovered via proxy interception, revealing the Bfp/D-id fingerprint headers, session flow, and answer format
4. **Text-type answer format** — the exact `btoa(JSON.stringify({btoa(col+"x"+row): getNum(col,row)}))` encoding with `Wcaptcha-Key` and `Captcha-Session` headers

---

## BREAKTHROUGH: Proxy-Based API Reverse Engineering

The complete API protocol was discovered by running the xCaptcha iframe page through a **local HTTP proxy interceptor** (port 9998) that injected JavaScript into the page. This approach captured every API call, header, and response body — without needing to decompile the JavaScript or read the minified source.

### The Approach

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  xCaptcha iframe  │────→│  Proxy :9998     │────→│  api.xcaptcha.com│
│  (browser)       │←────│  + JS injection   │←────│                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                               │
                         Logs ALL traffic:
                         • Request headers (Bfp, D-id, Captcha-Session)
                         • Request bodies
                         • Response bodies (task data, verification results)
                         • Full answer encoding format
```

### Step-by-Step

1. **Set up proxy**: `python3 proxy.py --inject intercept.js --port 9998`
2. **Load xCaptcha iframe page directly** in the browser through the proxy
3. **The injected `intercept.js`** monkey-patches `window.fetch` and `XMLHttpRequest` to log every call
4. **Captured the full API flow**:
   - `GET /captcha/{key}/init` — with `Bfp` header (browser fingerprint)
   - `GET /captcha/{key}/task?lang=en` — with `D-id` header (device ID = same as Bfp)
   - `GET /captcha/{key}/task/{answer}` — with `Wcaptcha-Key` + `Captcha-Session` headers

### Key Discoveries from Proxy Interception

#### 1. Browser Fingerprint (Bfp) Header

The `Bfp` header sent to `/init` is a **double-base64-encoded** structure:

```
Bfp: TVRJMExqQTBNelEzTlRJM05URTJNRGMwOk1UUTVPREl5TlRZNTpRVTVI...
```

Decoded (base64 → plaintext → base64 → values):

```
Part 0 (AudioContext):   124.04347527516074
Part 1 (Canvas):          149822569
Part 2 (WebGL):          ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device...))
Part 3 (Locale):          en-US
```

The `D-id` header equals `Bfp` — the same double-encoded fingerprint.

#### 2. Answer Encoding Confirmed

By clicking cells in the browser and watching the proxy log:

```
GET /captcha/{siteKey}/task/eyJNWGd4IjoxLCJNbmd4IjoyfQ==
Headers: 
  Captcha-Session: 5edbf23bb72fe323984dfc004a308fc1
  Wcaptcha-Key: b2f711a32df567bfb92efeebc7ccdc73
```

Decoded answer path `eyJNWGd4IjoxLCJNbmd4IjoyfQ==`:
```json
{"MXgx":1,"Mngx":2}
```

Which means:
- `MXgx` = base64("1x1") → column 1, row 1, cell number 1
- `Mngx` = base64("2x1") → column 2, row 1, cell number 2

#### 3. Response Feedback

The answer verification endpoint returns:
```json
// Correct answer:
{"success": true, "answer": "verification_token"}

// Wrong answer (with hint):
{"success": false, "c": 2}

// Wrong answer (no hint):
{"success": false}
```

The `c` field appears to indicate how many cells need to be selected (text type requires exactly 2).

#### 4. Text Challenge = "Same Code" Matching

The instruction text (previously assumed to be a generic "select X" instruction) is actually:

> **"Assemble from 2 elements the same code as shown above"**

This means the instruction area at the top of the image shows a **reference emoji/symbol**, and the solver must select the **2 cells that contain the same symbol** from the 8-cell grid below. It's a visual matching task, not a category classification.

The instruction area uses `background-position: 0px -220px` in the same sprite image.
The 8 data cells use positions like `0px -5px`, `-140px -5px`, etc.

---

## Challenge Types

xCaptcha has **4 challenge types**, each identified by a site key:

| Type | Site Key | Description |
|------|----------|-------------|
| `text` | `11aa6260...` | 2×4 grid of emoji cells; select 2 that match reference |
| `custom` | `5b4fc1a2...` | Click symbols at coordinates in correct order |
| `dynamics` | `506195d0...` | WebSocket-based slide/puzzle challenge |
| `empty` | `a537c95d...` | No-op challenge with leaked answer hash |

### The Custom (Click) Challenge Layout

```
┌──────────────────────────┐
│   [i1: reference strip]  │  ← Top: shows 4 symbols in ORDER
│   M  %  ☘  $            │     "Click these in this order"
├──────────────────────────┤
│                          │
│   [i2: scatter image]    │  ← Bottom: same symbols scattered
│      ☾   D              │     at random coordinates
│         V               │     User clicks them in order
│    T                    │
│                          │
└──────────────────────────┘
```

- **i1** (230×60px): The "text" strip showing what symbols to find and their required order
- **i2** (230×250px): The "click area" with those same symbols scattered at random positions
- User clicks the 4 symbols in the same order as shown in i1

### The Text Challenge Layout (CORRECTED)

```
┌───────┬───────┐
│ cell 0│ cell 1│  Row 1: bg-position 0px/-5px, -140px/-5px
├───────┼───────┤
│ cell 2│ cell 3│  Row 2: bg-position 0px/-60px, -140px/-60px
├───────┼───────┤
│ cell 4│ cell 5│  Row 3: bg-position 0px/-115px, -140px/-115px
├───────┼───────┤
│ cell 6│ cell 7│  Row 4: bg-position 0px/-170px, -140px/-170px
└───────┴───────┘
  2 columns × 4 rows (blocks: {x:2, y:4})
  Each cell: 140×55px, total raw image: 280×320px

┌───────────────────────┐
│   Instruction area     │  bg-position: 0px -220px (in same sprite)
│   "Assemble from 2     │  279×90px rendered
│    elements the same   │
│    code as shown above"│
│   [reference emoji]    │
└───────────────────────┘
```

**CRITICAL CORRECTION**: Earlier research assumed 6 data cells (3 rows) + instruction row. The actual layout is **8 data cells (4 rows)** + instruction area. The `blocks.y=4` in the API response means 4 data rows, not 3 data rows + 1 instruction row.

### Cell Background Positions

| Cell | Column | Row | bg-position | getNum |
|------|--------|-----|-------------|--------|
| 0 | 1 | 1 | `0px -5px` | 1 |
| 1 | 2 | 1 | `-140px -5px` | 2 |
| 2 | 1 | 2 | `0px -60px` | 3 |
| 3 | 2 | 2 | `-140px -60px` | 4 |
| 4 | 1 | 3 | `0px -115px` | 5 |
| 5 | 2 | 3 | `-140px -115px` | 6 |
| 6 | 1 | 4 | `0px -170px` | 7 |
| 7 | 2 | 4 | `-140px -170px` | 8 |

---

## Image Obfuscation

xCaptcha obfuscates PNG images served in the `img` field of text-type API responses. The obfuscation is **not cryptographic** — it's a simple character substitution on the raw PNG bytes.

### The Transformation

```
Original PNG bytes:    contains '/' (0x2F) and '&' (0x26)

Obfuscation step:
  '/' (0x2F)  →  '|b|'  (3 bytes: 0x7C 0x62 0x7C)
  '&' (0x26)  →  '(a)'  (3 bytes: 0x28 0x61 0x29)

Result: slightly larger data → base64-encoded → served as `img` field
```

### Why This Fails as Security

1. **No key material** — the replacements are static and hardcoded in `app.js`
2. **Deterministic** — same input always produces same output
3. **Self-documenting** — the deobfuscation code is in the publicly shipped frontend

### The Deobfuscation Code (from app.js)

```javascript
// xCaptcha app.js — the img function
img: function(t) {
    return btoa(
        atob(t)                          // base64-decode
            .split("|b|").join("/")      // |b| → /
            .split("(a)").join("&")      // (a) → &
    )
}
```

### Python Implementation

```python
def deobfuscate_image(img_b64: str) -> bytes:
    """Reverse xCaptcha's PNG byte obfuscation."""
    raw = base64.b64decode(img_b64)
    raw_str = raw.decode("latin-1")          # preserve all byte values
    deobfuscated = raw_str.replace("|b|", "/").replace("(a)", "&")
    return deobfuscated.encode("latin-1")    # back to valid PNG bytes
```

### Obfuscation Diagram

```
Server side:
  PNG bytes → replace '/' with '|b|', '&' with '(a)' → base64 → "img" field

Client side (app.js):
  "img" field → base64 decode → replace '|b|' with '/', '(a)' with '&' → base64 → valid PNG
```

---

## API Protocol (Full)

### Complete API Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  INITIALIZATION                                                  │
│                                                                  │
│  1. GET /captcha/{siteKey}/                                      │
│     → HTML page with CAPTCHA_SESSION, app.js, vendors.js          │
│     → CAPTCHA_SESSION stored in window.CAPTCHA_SESSION           │
│                                                                  │
│  2. GET /captcha/{siteKey}/init                                  │
│     Headers:                                                     │
│       Captcha-Session: {session}                                 │
│       Bfp: {double-base64 browser fingerprint}                   │
│       Dn: "" (usually empty)                                     │
│       client: {timestamp.offset}                                 │
│       wparams: "20.1280.720.1280.1"  (screen color/int info)    │
│     Response: {"status": true, "socket": false, "scripts": []}   │
│                                                                  │
│  3. GET /captcha/{siteKey}/task?lang=en                          │
│     Headers:                                                     │
│       Captcha-Session: {session}                                 │
│       D-id: {same as Bfp}                                        │
│     Response: task JSON (see below)                              │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  ANSWER SUBMISSION                                               │
│                                                                  │
│  4. GET /captcha/{siteKey}/task/{base64_answer}                 │
│     Headers:                                                     │
│       Captcha-Session: {session}                                 │
│       Wcaptcha-Key: {task.key}                                   │
│     Response:                                                     │
│       Success: {"success": true, "answer": "verification_token"} │
│       Wrong:   {"success": false}                                │
│       Wrong:   {"success": false, "c": N}  (N = required count) │
│                                                                  │
│  On success:                                                     │
│     parent.window.postMessage({                                  │
│       call: '__wcaptcha.success("verification_token")'          │
│     }, "*")                                                      │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  ON WRONG ANSWER                                                 │
│                                                                  │
│  5. GET /captcha/{siteKey}/task?lang=en                          │
│     Server automatically issues a NEW task after wrong answer    │
│     Same session, new key + img                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Bfp (Browser Fingerprint) Structure

```python
# Bfp is double-base64 encoded:
# Outer layer: base64 of "innerB64:innerB64:innerB64:locale"
# Inner layers: base64 of actual values

import base64

def decode_bfp(bfp: str) -> dict:
    """Decode the xCaptcha Bfp browser fingerprint."""
    outer = base64.b64decode(bfp).decode('utf-8')
    parts = outer.split(':')
    
    return {
        'audio_hash': base64.b64decode(parts[0]).decode('utf-8'),
        'canvas_hash': base64.b64decode(parts[1]).decode('utf-8'),
        'webgl_renderer': base64.b64decode(parts[2]).decode('utf-8'),
        'locale': parts[3],
    }

# Example decoded:
# {
#     'audio_hash': '124.04347527516074',
#     'canvas_hash': '149822569',
#     'webgl_renderer': 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)',
#     'locale': 'en-US'
# }
```

---

## API Vulnerabilities

### Vulnerability 1: Coordinate Leakage (Custom Type)

**Severity: Critical**

The `/task` API endpoint for the custom (click) type **returns ground-truth coordinates**:

```json
{
  "type": "custom",
  "key": "...",
  "i1": "/tasks/0er1/xyz.jpg",
  "i2": "/tasks/0er1/abc.jpg",
  "coords": [
    {"letter": "M", "x": 77.34, "y": 88},
    {"letter": "%", "x": 125.06, "y": 120.5},
    {"letter": "☘", "x": 186.62, "y": 72.5},
    {"letter": "$", "x": 38.00, "y": 154.5}
  ]
}
```

**Impact:** No image recognition needed — just read `coords` and submit.

### Vulnerability 2: Answer Hash Leakage (Empty Type)

**Severity: Critical**

```json
{
  "type": "empty",
  "answer": "88be4d4f04868bdf225612a9d05ddcd1",
  "key": "..."
}
```

### Vulnerability 3: Text Type — Fingerprint Spoofable

**Severity: Medium**

The `Bfp` header contains browser fingerprint data, but:
- No signature/HMAC — can be forged with any values
- Server doesn't verify the fingerprint matches the actual browser
- Generated proxy traffic used random fingerprints and still got valid tasks

---

## Solving Each Type

### Text Type

**Method:** Visual matching on deobfuscated grid cells

1. Fetch iframe page → extract `CAPTCHA_SESSION`
2. Send `/init` with Bfp fingerprint headers
3. Fetch `/task?lang=en` → get task with `img` and `key`
4. Deobfuscate `img` → valid PNG (280×320px)
5. Extract instruction area (y=220-310 in raw image)
6. Extract 8 data cells (4 rows × 2 cols, each 140×55px)
7. **Match**: Find 2 cells that visually match the reference emoji in the instruction area
8. Format answer: `btoa(JSON.stringify({btoa(col+"x"+row): getNum(col,row)}))`
9. Submit to `/captcha/{siteKey}/task/{answer}` with `Wcaptcha-Key` + `Captcha-Session`

**Answer format:**
```python
import base64, json

def format_text_answer(selected_cells: list) -> str:
    """
    selected_cells: list of (col, row) tuples, 1-based
    Example: [(1, 1), (2, 3)] means cell at col=1,row=1 and col=2,row=3
    """
    checked = {}
    blocks_x = 2  # from task['blocks']['x']
    for col, row in selected_cells:
        key = base64.b64encode(f"{col}x{row}".encode()).decode()
        num = (row - 1) * blocks_x + col
        checked[key] = num
    return base64.b64encode(json.dumps(checked).encode()).decode()

# Example: selecting cells at (1,1) and (2,1)
answer = format_text_answer([(1, 1), (2, 1)])
# Result: "eyJNWGd4IjoxLCJNbmd4IjoyfQ=="
# Decodes to: {"MXgx":1,"Mngx":2}
```

### Custom (Click) Type

**Method:** Read leaked coordinates — zero image recognition needed

```python
def format_custom_answer(coords: list) -> str:
    """Format clicked coordinates as answer."""
    clicks = [{"x": c["x"], "y": c["y"]} for c in coords]
    return base64.b64encode(json.dumps(clicks).encode()).decode()
```

### Empty Type

**Method:** Submit the leaked answer hash directly

```python
answer = task["answer"]  # Already exposed in API response
```

### Dynamics Type

**Method:** WebSocket interaction (not yet automated)

- Uses `wss://api.xcaptcha.com/ws`
- Requires real-time interaction (slide/puzzle challenges)
- The `SocketManager` in `app.js` handles the connection

---

## Architecture

### API Flow Diagram

```
                    ┌──────────────────────────────┐
                    │                              │
                    │  Browser with xCaptcha iframe │
                    │                              │
                    └──────┬───────────────────────┘
                           │
                    ┌──────▼───────────────────────┐
                    │  Proxy Interceptor :9998      │  ← injects JS to log fetch/XHR
                    │  (optional, for research)     │
                    └──────┬───────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   api.xcaptcha.com      │
              │                         │
              │  GET /captcha/{key}/     │ ← iframe HTML
              │  GET /.../init           │ ← Bfp fingerprint
              │  GET /.../task           │ ← challenge data
              │  GET /.../task/{ans}     │ ← verify answer
              └─────────────────────────┘
```

### Frontend Functions (from app.js)

```javascript
// Image deobfuscation
img: function(t) {
    return btoa(atob(t).split("|b|").join("/").split("(a)").join("&"))
}

// Cell indexing (1-based col, row)
getNum: function(t, e) {
    return (e - 1) * this.task.blocks.x + t
}

// Cell key generation
key: function(t, e) {
    return btoa(t + "x" + e)
}

// Text answer serialization (send on confirm)
send: function() {
    var t = btoa(JSON.stringify(this.checked))
    this.$parent.setAnswer(!!this.hasChecked() && t)
}

// Answer verification (checkAnswer)
checkAnswer: function(t) {
    fetch('https://{hostApi}/captcha/{siteKey}/task/' + t, {
        headers: {
            'Wcaptcha-Key': this.task.key,
            'Captcha-Session': window.CAPTCHA_SESSION
        }
    })
    .then(r => r.json())
    .then(r => {
        if (r.success) {
            this.finished(t.answer)
        } else {
            // Wrong answer → get new task
            this.getTask()
        }
    })
}

// Cell click handler (allows exactly 2 selections)
check: function(col, row, touch) {
    var key = this.key(col, row)
    if (this.checked[key] !== undefined) {
        delete this.checked[key]
    } else if (2 != Object.keys(this.checked).length) {
        this.checked[key] = this.getNum(col, row)
    }
    this.send()
}
```

### Verification Flow

After solving:
1. `setAnswer(answer)` → calls `checkAnswer(answer)`
2. `checkAnswer` GETs `/captcha/{siteKey}/task/{answer}`
3. On success: `parent.window.postMessage({call: '__wcaptcha.success("' + answer + '")'}, "*")`
4. The parent page receives the token via `message` event

---

## Usage

```bash
# Solve all types
python3 solver.py all

# Solve specific type
python3 solver.py text
python3 solver.py custom
python3 solver.py empty

# With custom site key
python3 solver.py --key YOUR_SITE_KEY
```

### Proxy-Based Research

```bash
# Start proxy with interceptor
python3 proxy.py --inject intercept.js --port 9998 --log traffic.log

# Load xCaptcha through proxy
chrome --proxy-server=http://localhost:9998
```

### Requirements

```
aiohttp
Pillow
```

---

## Research Timeline

1. **Phase 1 — Deobfuscation**: Discovered the `|b|`/`(a)` byte substitution in `app.js`
2. **Phase 2 — API Leakage**: Found that `/task` returns ground-truth coords for custom type and answer hash for empty type
3. **Phase 3 — Proxy Interception**: Built a local proxy interceptor (port 9998) with JS injection to capture live API traffic from the browser
4. **Phase 4 — Protocol Discovery**: Through proxy interception, discovered the complete API flow including Bfp/D-id fingerprint headers, Captcha-Session handling, and the exact answer encoding format
5. **Phase 5 — Grid Correction**: Discovered that `blocks.y=4` means 8 data cells (not 6), correcting a critical misunderstanding of the text challenge layout
6. **Phase 6 — Challenge Semantics**: Determined the text challenge instruction is "Assemble from 2 elements the same code as shown above" — a visual matching task, not category classification

---

## Disclaimer

This research is for educational and security assessment purposes only. The vulnerabilities documented here (trivially reversible obfuscation, API answer leakage) represent significant design weaknesses in the xCaptcha service. Responsible disclosure principles should be followed when using this information.

## License

MIT
