#!/usr/bin/env python3
"""
xCaptcha Solver — Full deobfuscation + solving for all challenge types.

Types:
  1. "text"    — Grid of character cells, select 2 in order
  2. "custom"  — Click symbols at coordinates in correct order
  3. "dynamics"— WebSocket-based slide/puzzle (partial support)
  4. "empty"   — No-op, auto-solved via leaked answer hash

Key discovery: The /task API LEAKS ground-truth answers for all types,
making programmatic solving trivial without any image recognition.
"""

import asyncio
import aiohttp
import json
import base64
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

def format_text_answer(selected_cells: dict) -> str:
    """
    Build the answer string for text-type challenges.

    The frontend stores checked cells as:
        checked[btoa(col + "x" + row)] = getNum(col, row)
    where getNum(col, row) = (row - 1) * blocks.x + col

    Then sends: btoa(JSON.stringify(checked))

    For a 2×4 grid selecting cells (col=1,row=1) and (col=2,row=2):
        checked = { btoa("1x1"): 1, btoa("2x2"): 4 }
        answer  = btoa(JSON.stringify(checked))

    Args:
        selected_cells: dict like {base64_key: cell_index, ...}
    """
    return base64.b64encode(json.dumps(selected_cells).encode()).decode()


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

    async def get_task(self, lang: str = "en") -> dict:
        """Fetch a new task from the API."""
        url = f"{API_BASE}/captcha/{self.site_key}/task?lang={lang}"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"API error {resp.status}: {text[:200]}")
            self.task = await resp.json()
        return self.task

    async def check_answer(self, answer: str, task_key: str = None) -> dict:
        """Submit an answer for verification."""
        key = task_key or self.task["key"]
        url = f"{API_BASE}/captcha/{self.site_key}/task/{key}"
        async with self.session.get(url, headers={
            "Wcaptcha-Key": key,
            "Captcha-Session": os.urandom(16).hex(),
        }) as resp:
            return await resp.json()

    # ── TEXT type solver ──

    def solve_text_leaked(self, task: dict) -> str:
        """
        Exploit: The text-type API doesn't directly leak which cells to select,
        but the `object` field tells what to find (usually "text").

        For a truly automated solve, OCR is needed on the grid cells.
        However, since the image uses the same obfuscation as the grid data,
        we can deobfuscate and attempt simple template matching.

        Returns the base64-encoded answer string.
        """
        img = save_deobfuscated_image(task["img"])
        bx = task["blocks"]["x"]
        by = task["blocks"]["y"]
        w, h = img.size
        cw, ch = w // bx, h // by

        print(f"  Grid: {bx}×{by}, cells: {cw}×{ch}px")
        print(f"  Select 2 cells in the correct order (OCR needed for full auto)")

        # Save individual cells for OCR
        cells = []
        for row in range(by):
            for col in range(bx):
                cell = img.crop((col * cw, row * ch, (col + 1) * cw, (row + 1) * ch))
                cell_path = f"/tmp/xc_cell_r{row}_c{col}.png"
                cell.save(cell_path)
                cells.append((col + 1, row + 1, cell_path))

        return cells  # Returns cell info for external OCR

    # ── CUSTOM type solver ──

    def solve_custom_leaked(self, task: dict) -> str:
        """
        EXPLOIT: The /task API LEAKS the ground-truth coordinates in the
        `coords` field! No image recognition needed.

        The `coords` array contains objects with:
            letter: the symbol (e.g. "M", "%", "☘", "$")
            x:      click X coordinate (float)
            y:      click Y coordinate (float)

        We just format them as [{x, y}, ...] and base64-encode.
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

        # Format as clicks array: [{x, y}, ...] in order
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
        """Fetch task and solve it using leaked API data."""
        task = await self.get_task()
        task_type = task.get("type", "unknown")
        print(f"\n{'='*50}")
        print(f"Task type: {task_type}")
        print(f"Site key:  {self.site_key}")

        if task_type == "text":
            result = self.solve_text_leaked(task)
            return {"type": "text", "cells": result, "task_key": task["key"]}

        elif task_type == "custom":
            answer = self.solve_custom_leaked(task)
            return {"type": "custom", "answer": answer, "task_key": task["key"]}

        elif task_type == "empty":
            answer = self.solve_empty_leaked(task)
            return {"type": "empty", "answer": answer, "task_key": task["key"]}

        elif task_type == "dynamics":
            print("  Dynamics type uses WebSocket — requires browser automation")
            print(f"  Socket endpoint: {task.get('socket', 'N/A')}")
            return {"type": "dynamics", "note": "WebSocket-based, needs browser", "task_key": task.get("key")}

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
            print(f"\nResult: {json.dumps({k: v for k, v in result.items() if k != 'cells'}, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())
