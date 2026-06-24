#!/usr/bin/env python3
"""
xCaptcha Solver — Full deobfuscation + solving for all challenge types.

Types:
  1. "text"    — 2×4 grid of emoji cells; select 2 matching the reference
  2. "custom"  — Click symbols at coordinates in correct order
  3. "dynamics"— WebSocket-based slide/puzzle (partial support)
  4. "empty"   — No-op, auto-solved via leaked answer hash

Key discoveries:
  - The /task API LEAKS ground-truth answers for custom/empty types
  - Text type uses 8 cells (2×4 grid), NOT 6 — blocks.y=4 is ALL data rows
  - Instruction "Assemble from 2 elements the same code as shown above"
    means: find the 2 cells matching the reference emoji at top
  - Answer format: btoa(JSON.stringify({btoa(col+"x"+row): getNum(col,row)}))
  - Answer URL: /captcha/{siteKey}/task/{answer_base64}
  - Required headers: Wcaptcha-Key + Captcha-Session
  - Bfp/D-id: double-base64 browser fingerprint (spoofable)
"""

import asyncio
import aiohttp
import json
import base64
import re
import sys
import os
from PIL import Image
import io

# ─── Site keys for the xcaptcha.com demo ───
SITE_KEYS = {
    "text":     "11aa62606fb968f3674742df60598957",
    "dynamics": "506195d06393f98584931a6ede3cb64c",
    "custom":   "5b4fc1a221c3e79c9bac190363808884",
    "empty":    "a537c95d43097aed9cd8a295ecdc2a79",
}

API_BASE = "https://api.xcaptcha.com"


# ─────────────────────────────────────────────
#  Image Deobfuscation
# ─────────────────────────────────────────────

def deobfuscate_image(img_b64: str) -> bytes:
    """
    Deobfuscate xCaptcha's base64-encoded PNG images.

    The obfuscation is a simple character replacement applied to the
    raw PNG bytes BEFORE base64 encoding:
        '/'  →  '|b|'
        '&'  →  '(a)'

    To reverse: decode base64 → replace '|b|' back to '/' and '(a)'
    back to '&' → result is a valid PNG.

    This is applied to the `img` field in text-type task responses.
    """
    raw = base64.b64decode(img_b64)
    raw_str = raw.decode("latin-1")          # bytes → str preserving all 0-255
    deobfuscated = raw_str.replace("|b|", "/").replace("(a)", "&")
    return deobfuscated.encode("latin-1")     # str → bytes


def save_deobfuscated_image(img_b64: str, path: str = None) -> Image.Image:
    """Deobfuscate and save image. Returns PIL Image."""
    png_bytes = deobfuscate_image(img_b64)
    img = Image.open(io.BytesIO(png_bytes))
    if path:
        img.save(path)
        print(f"  Saved deobfuscated image → {path} ({img.size} {img.mode})")
    return img


# ─────────────────────────────────────────────
#  Answer Formatting
# ─────────────────────────────────────────────

def format_text_answer(selected_cells: list, blocks_x: int = 2) -> str:
    """
    Build the answer string for text-type challenges.

    The frontend stores checked cells as:
        checked[btoa(col + "x" + row)] = getNum(col, row)
    where getNum(col, row) = (row - 1) * blocks.x + col

    Then sends: btoa(JSON.stringify(checked))

    Args:
        selected_cells: list of (col, row) tuples, 1-based
        blocks_x: number of columns (from task['blocks']['x'])

    Example:
        >>> format_text_answer([(1, 1), (2, 1)])
        'eyJNWGd4IjoxLCJNbmd4IjoyfQ=='
        >>> import base64, json
        >>> json.loads(base64.b64decode('eyJNWGd4IjoxLCJNbmd4IjoyfQ=='))
        {'MXgx': 1, 'Mngx': 2}
        >>> base64.b64decode('MXgx').decode()
        '1x1'
    """
    checked = {}
    for col, row in selected_cells:
        key = base64.b64encode(f"{col}x{row}".encode()).decode()
        num = (row - 1) * blocks_x + col
        checked[key] = num
    return base64.b64encode(json.dumps(checked).encode()).decode()


def format_custom_answer(coords: list) -> str:
    """
    Build the answer string for custom-type challenges.

    The frontend collects clicks as:
        clicks.push({x: e.offsetX, y: e.offsetY})
    Then sends: btoa(JSON.stringify(clicks))

    Args:
        coords: list of {"x": float, "y": float} dicts in order
    """
    return base64.b64encode(json.dumps(coords).encode()).decode()


# ─────────────────────────────────────────────
#  Bfp Fingerprint Generation
# ─────────────────────────────────────────────

def generate_bfp(audio_hash: str = "124.04347527516074",
                 canvas_hash: str = "149822569",
                 webgl_renderer: str = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)",
                 locale: str = "en-US") -> str:
    """
    Generate a Bfp (Browser Fingerprint) header value.

    The Bfp is double-base64 encoded:
      outer = base64(inner_audio_b64 + ":" + inner_canvas_b64 + ":" + inner_webgl_b64 + ":" + locale)

    This header is required for /init and reused as D-id for /task.
    The server doesn't verify the fingerprint matches the actual browser.
    """
    audio_b64 = base64.b64encode(audio_hash.encode()).decode()
    canvas_b64 = base64.b64encode(canvas_hash.encode()).decode()
    webgl_b64 = base64.b64encode(webgl_renderer.encode()).decode()

    inner = f"{audio_b64}:{canvas_b64}:{webgl_b64}:{locale}"
    return base64.b64encode(inner.encode()).decode()


def decode_bfp(bfp: str) -> dict:
    """Decode a Bfp header value back to its components."""
    outer = base64.b64decode(bfp).decode('utf-8')
    parts = outer.split(':')

    return {
        'audio_hash': base64.b64decode(parts[0]).decode('utf-8') if len(parts) > 0 else '',
        'canvas_hash': base64.b64decode(parts[1]).decode('utf-8') if len(parts) > 1 else '',
        'webgl_renderer': base64.b64decode(parts[2]).decode('utf-8') if len(parts) > 2 else '',
        'locale': parts[3] if len(parts) > 3 else '',
    }


# ─────────────────────────────────────────────
#  API Client
# ─────────────────────────────────────────────

class XcaptchaClient:
    """Async client for the xCaptcha API with built-in solving."""

    def __init__(self, site_key: str = None, site_type: str = None):
        if site_key:
            self.site_key = site_key
        elif site_type and site_type in SITE_KEYS:
            self.site_key = SITE_KEYS[site_type]
        else:
            raise ValueError("Provide site_key or site_type (text/dynamics/custom/empty)")

        self.session = None
        self.captcha_session = None
        self.bfp = None
        self.task = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={
                "Origin": "https://xcaptcha.com",
                "Referer": "https://xcaptcha.com/",
            }
        )
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def init_session(self):
        """Initialize a captcha session: fetch iframe → extract session → send init."""
        # 1. Fetch iframe page to get CAPTCHA_SESSION
        iframe_url = f"{API_BASE}/captcha/{self.site_key}/?lang=en&orig_lang=en"
        async with self.session.get(iframe_url) as resp:
            html = await resp.text()

        # Extract CAPTCHA_SESSION
        match = re.search(r"CAPTCHA_SESSION\s*=\s*'([^']+)'", html)
        if not match:
            raise Exception("Could not extract CAPTCHA_SESSION from iframe")
        self.captcha_session = match.group(1)
        print(f"  Session: {self.captcha_session}")

        # 2. Generate Bfp fingerprint
        self.bfp = generate_bfp()

        # 3. Send /init with Bfp
        init_resp = await self.session.get(
            f"{API_BASE}/captcha/{self.site_key}/init",
            headers={
                "Captcha-Session": self.captcha_session,
                "Bfp": self.bfp,
                "Dn": "",
                "client": "1782284470300.9204",
                "wparams": "20.1280.720.1280.1",
            }
        )
        init_data = await init_resp.json()
        print(f"  Init: {init_data}")
        return init_data

    async def get_task(self, lang: str = "en") -> dict:
        """Fetch a new task from the API."""
        if not self.captcha_session:
            await self.init_session()

        url = f"{API_BASE}/captcha/{self.site_key}/task?lang={lang}"
        async with self.session.get(url, headers={
            "Captcha-Session": self.captcha_session,
            "D-id": self.bfp or generate_bfp(),
        }) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"API error {resp.status}: {text[:200]}")
            self.task = await resp.json()
        return self.task

    async def check_answer(self, answer: str, task_key: str = None) -> dict:
        """Submit an answer for verification."""
        key = task_key or self.task["key"]
        url = f"{API_BASE}/captcha/{self.site_key}/task/{answer}"
        async with self.session.get(url, headers={
            "Wcaptcha-Key": key,
            "Captcha-Session": self.captcha_session,
        }) as resp:
            return await resp.json()

    # ── TEXT type solver ──

    def extract_text_cells(self, task: dict) -> list:
        """
        Extract individual cell images from a text-type task.

        Returns list of dicts with:
          - col, row (1-based)
          - getNum (cell index)
          - key (base64 of "col x row")
          - image (PIL Image of the cell)
          - position (background-position string)
        """
        img = save_deobfuscated_image(task["img"])
        bx = task["blocks"]["x"]
        by = task["blocks"]["y"]

        # Cell dimensions from the JS: style_block sets background-position
        # Position formula: -140*(col-1), -55*(row-1)-5
        # Cell render size: 139×50px (as observed in browser DOM)

        # Raw image size: 280×320
        # Cell crop from raw image: 140×55px each
        cell_w, cell_h = 140, 55
        cells = []

        for row in range(1, by + 1):
            for col in range(1, bx + 1):
                # Crop from raw image (row-1)*55 starting at y=5 for row 1
                y_offset = (row - 1) * 55 + 5
                x_offset = (col - 1) * 140

                cell_img = img.crop((
                    x_offset, y_offset,
                    x_offset + cell_w, y_offset + cell_h
                ))

                key = base64.b64encode(f"{col}x{row}".encode()).decode()
                num = (row - 1) * bx + col

                cells.append({
                    "col": col,
                    "row": row,
                    "getNum": num,
                    "key": key,
                    "image": cell_img,
                    "bg_position": f"{-140*(col-1)}px {-55*(row-1)-5}px",
                })

                # Save cell for inspection
                cell_path = f"/tmp/xc_cell_{col}x{row}.png"
                cell_img.save(cell_path)

        # Also extract instruction area (y=220, h=90 in rendered, y=220 in raw)
        instr_img = img.crop((0, 220, 280, 320))
        instr_img.save("/tmp/xc_instruction.png")

        print(f"  Grid: {bx}×{by}, {len(cells)} cells extracted")
        print(f"  Instruction area saved to /tmp/xc_instruction.png")
        return cells

    def extract_instruction_text(self, task: dict) -> str:
        """
        The text-type instruction is rendered in the image at bg-position 0px -220px.
        The known English instruction is:
          "Assemble from 2 elements the same code as shown above"
        """
        return "Assemble from 2 elements the same code as shown above"

    # ── CUSTOM type solver ──

    def solve_custom_leaked(self, task: dict) -> str:
        """
        EXPLOIT: The /task API LEAKS the ground-truth coordinates in the
        `coords` field! No image recognition needed.
        """
        coords = task.get("coords", [])
        if not coords:
            raise ValueError("No coords in task response — API may have been patched")

        # Parse coords (API returns it as a JSON string sometimes)
        if isinstance(coords, str):
            coords = json.loads(coords)

        print(f"  LEAKED {len(coords)} target coordinates:")
        for c in coords:
            print(f"    Find {c['letter']} at ({c['x']:.1f}, {c['y']:.1f})")

        clicks = [{"x": c["x"], "y": c["y"]} for c in coords]
        answer = format_custom_answer(clicks)

        print(f"  Answer (base64): {answer}")
        return answer

    # ── EMPTY type solver ──

    def solve_empty_leaked(self, task: dict) -> str:
        """
        EXPLOIT: The empty-type API response contains `answer` with the
        verification hash directly! Just submit it.
        """
        answer = task.get("answer", "")
        print(f"  LEAKED answer hash: {answer}")
        return answer

    # ── Main solve entry point ──

    async def solve(self) -> dict:
        """Fetch task and solve it."""
        if not self.captcha_session:
            await self.init_session()

        task = await self.get_task()
        task_type = task.get("type", "unknown")
        print(f"\n{'='*50}")
        print(f"Task type: {task_type}")
        print(f"Site key:  {self.site_key}")

        if task_type == "text":
            cells = self.extract_text_cells(task)
            instruction = self.extract_instruction_text(task)

            print(f"\n  Instruction: \"{instruction}\"")
            print(f"  Select 2 cells that match the reference emoji")
            print(f"  Cells saved to /tmp/xc_cell_*.png")
            print(f"  Reference saved to /tmp/xc_instruction.png")
            print(f"\n  Answer format: btoa(JSON.stringify({{btoa(col+'x'+row): getNum}}))")
            print(f"  Submit: GET /captcha/{{siteKey}}/task/{{answer}}")
            print(f"  With headers: Wcaptcha-Key={task['key']}")

            return {"type": "text", "cells": cells, "task_key": task["key"],
                    "instruction": instruction, "format": "see format_text_answer()"}

        elif task_type == "custom":
            answer = self.solve_custom_leaked(task)
            result = await self.check_answer(answer)
            return {"type": "custom", "answer": answer, "result": result,
                    "task_key": task["key"]}

        elif task_type == "empty":
            answer = self.solve_empty_leaked(task)
            result = await self.check_answer(answer)
            return {"type": "empty", "answer": answer, "result": result,
                    "task_key": task["key"]}

        elif task_type == "dynamics":
            print("  Dynamics type uses WebSocket — requires browser automation")
            print(f"  Socket endpoint: {task.get('socket', 'N/A')}")
            return {"type": "dynamics", "note": "WebSocket-based, needs browser",
                    "task_key": task.get("key")}

        else:
            print(f"  Unknown type: {task_type}")
            return {"type": task_type, "raw": task}


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    types_to_solve = ["text", "custom", "empty"] if target == "all" else [target]

    for t in types_to_solve:
        if t not in SITE_KEYS:
            print(f"Unknown type: {t}")
            continue

        async with XcaptchaClient(site_type=t) as client:
            result = await client.solve()
            # Don't print raw cell data — just summary
            summary = {k: v for k, v in result.items()
                       if k not in ("cells", "raw")}
            print(f"\nResult: {json.dumps(summary, indent=2, default=str)}")


if __name__ == "__main__":
    asyncio.run(main())
