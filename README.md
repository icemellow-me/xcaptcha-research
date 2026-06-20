# xCaptcha Research: Deobfuscation & Solving

> **Security research** documenting xCaptcha's image obfuscation scheme and critical API vulnerabilities that leak challenge answers.

## Table of Contents

- [Overview](#overview)
- [Challenge Types](#challenge-types)
- [Image Obfuscation](#image-obfuscation)
- [API Vulnerabilities](#api-vulnerabilities)
- [Solving Each Type](#solving-each-type)
- [Usage](#usage)
- [Architecture](#architecture)

---

## Overview

xCaptcha is a CAPTCHA service (xcaptcha.com) offering four challenge types. This research documents:

1. **Image obfuscation** — a trivially reversible byte substitution applied to PNG data before base64 encoding
2. **API answer leakage** — the `/task` endpoint returns ground-truth coordinates and answer hashes, making programmatic solving trivial without any image recognition

## Challenge Types

xCaptcha has **4 challenge types**, each identified by a site key:

| Type | Site Key | Description |
|------|----------|-------------|
| `text` | `11aa6260...` | 2×4 grid of character cells; select 2 in order |
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

### The Text Challenge Layout

```
┌───────┬───────┐
│ cell 0│ cell 1│  Row 0: symbol/symbol
├───────┼───────┤
│ cell 2│ cell 3│  Row 1: symbol/symbol
├───────┼───────┤
│ cell 4│ cell 5│  Row 2: symbol/symbol
├───────┼───────┤
│ cell 6│ cell 7│  Row 3: instruction text
└───────┴───────┘
  2 columns × 4 rows (blocks: {x:2, y:4})
  Each cell: 140×80px, total: 280×320px
```

- Rows 0-2 contain the 6 symbol options
- Row 3 contains instruction text (what to find)
- User selects 2 cells in the correct sequence

---

## Image Obfuscation

xCaptcha obfuscates PNG images served in the `img` field of text-type API responses. The obfuscation is **not cryptographic** — it's a simple character substitution on the raw PNG bytes.

### The Transformation

Before base64-encoding the PNG, two byte sequences are replaced:

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

Note: The client does a redundant `btoa(atob(...))` round-trip because the intermediate result after the replacements is still in byte form, and `btoa()` converts it back to base64 for the `<img src="data:image/png;base64,...">` URL.

---

## API Vulnerabilities

### Vulnerability 1: Coordinate Leakage (Custom Type)

**Severity: Critical**

The `/task` API endpoint for the custom (click) type **returns ground-truth coordinates** in the `coords` field:

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

**Impact:** No image recognition needed — just read `coords` and submit the x/y values as the answer. The solver extracts coordinates directly from the API response.

### Vulnerability 2: Answer Hash Leakage (Empty Type)

**Severity: Critical**

The empty-type task response includes the verification answer directly:

```json
{
  "type": "empty",
  "answer": "88be4d4f04868bdf225612a9d05ddcd1",
  "key": "..."
}
```

**Impact:** Trivially solved by submitting the leaked hash.

### Vulnerability 3: Text Type — Partial Leakage

**Severity: Medium**

The text-type response doesn't directly leak which cells to select, but:
- The `object` field reveals the challenge category
- The deobfuscated image is trivially OCR-readable (no additional distortion beyond the byte substitution)
- The `blocks` field reveals the grid structure

---

## Solving Each Type

### Text Type

**Method:** OCR on deobfuscated grid cells

1. Fetch task from `/captcha/{site_key}/task?lang=en`
2. Deobfuscate `img` field → valid PNG
3. Split into grid cells based on `blocks` (2×4)
4. OCR each cell to identify characters
5. Determine which 2 cells to select based on the instruction (row 3)
6. Format answer as `btoa(JSON.stringify({btoa(col+"x"+row): getNum(col,row)}))`
7. Submit to `/captcha/{site_key}/task/{key}`

**Answer format:**
```javascript
// Frontend code
checked = {};
checked[btoa("1x1")] = getNum(1,1)  // = (1-1)*2 + 1 = 1
checked[btoa("2x2")] = getNum(2,2)  // = (2-1)*2 + 2 = 4
answer = btoa(JSON.stringify(checked))
```

### Custom (Click) Type

**Method:** Read leaked coordinates — zero image recognition needed

1. Fetch task from `/captcha/{site_key}/task?lang=en`
2. Extract `coords` array from response
3. Format as `[{x, y}, ...]` in the same order
4. Base64-encode: `btoa(JSON.stringify(clicks))`
5. Submit to `/captcha/{site_key}/task/{key}`

**Answer format:**
```javascript
clicks = [
  {"x": 77.34, "y": 88},
  {"x": 125.06, "y": 120.5},
  {"x": 186.62, "y": 72.5},
  {"x": 38.00, "y": 154.5}
]
answer = btoa(JSON.stringify(clicks))
```

### Empty Type

**Method:** Submit the leaked answer hash directly

1. Fetch task from `/captcha/{site_key}/task?lang=en`
2. Read `answer` field
3. Submit as the answer

### Dynamics Type

**Method:** WebSocket interaction (not yet automated)

- The dynamics type uses a WebSocket at `api.xcaptcha.com/ws`
- Requires real-time interaction (slide/puzzle challenges)
- The `SocketManager` in `app.js` handles the connection
- Not solvable via simple API calls — needs browser automation or WebSocket client

---

## Architecture

### API Flow

```
┌──────────┐     GET /captcha/{key}/task      ┌──────────┐
│  Client  │ ──────────────────────────────→  │  API     │
│          │ ←──────────────────────────────  │  Server  │
│          │   {type, key, img, coords, ...}   │          │
│          │                                    │          │
│          │     GET /captcha/{key}/task/{key}  │          │
│          │   Headers: Wcaptcha-Key,           │          │
│          │           Captcha-Session           │          │
│          │ ──────────────────────────────→    │          │
│          │ ←──────────────────────────────    │          │
│          │   {success, answer}                │          │
└──────────┘                                    └──────────┘
```

### Frontend Components (app.js)

| Component | Purpose |
|-----------|---------|
| `TaskDefault` | Routes to sub-component by `task.type` |
| `TaskText` | Grid selection — `img` function deobfuscates, `getNum` indexes cells |
| `TaskCustom` | Click coordinates — loads `html_data` + `script`, uses `window.CustomTask` |
| `TaskDynamics` | WebSocket — `SocketManager` via `U.init()` |

### Key Frontend Functions

```javascript
// Image deobfuscation
img: function(t) {
    return btoa(atob(t).split("|b|").join("/").split("(a)").join("&"))
}

// Cell indexing (1-based col, row)
getNum: function(t, e) {
    return (e - 1) * this.task.blocks.x + t
}

// Cell key
key: function(t, e) {
    return btoa(t + "x" + e)
}

// Text answer serialization
send: function() {
    var t = btoa(JSON.stringify(this.checked))
    this.$parent.setAnswer(!!this.hasChecked() && t)
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

### Requirements

```
aiohttp
Pillow
```

---

## Disclaimer

This research is for educational and security assessment purposes only. The vulnerabilities documented here (trivially reversible obfuscation, API answer leakage) represent significant design weaknesses in the xCaptcha service. Responsible disclosure principles should be followed when using this information.

## License

MIT
