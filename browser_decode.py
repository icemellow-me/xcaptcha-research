"""
xCaptcha Image Decoder — Browser-based rendering
===================================================
xCaptcha's text-type API returns PNG images with deliberately broken
zlib streams (corrupt IDAT data). Standard PNG libraries can't decode them.
Browsers handle this because their PNG decoders have error recovery.

This module uses the Hermes browser to:
1. Create a minimal HTML page that injects the base64 image
2. Renders it on a canvas 
3. Extracts the decoded image as a clean PNG via canvas.toDataURL()
"""
import asyncio, aiohttp, json, base64, io, os, time
import numpy as np
from PIL import Image

DECODER_HTML = """<!DOCTYPE html>
<html><head><title>xCaptcha Decoder</title></head>
<body>
<canvas id="c"></canvas>
<div id="status">Loading...</div>
<script>
const B64 = '__B64_PLACEHOLDER__';
async function run() {
    try {
        const img = new Image();
        img.src = 'data:image/png;base64,' + B64;
        await new Promise((ok, no) => { img.onload = ok; img.onerror = no; });
        const c = document.getElementById('c');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        const ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0);
        window.result = c.toDataURL('image/png');
        window.imgW = img.naturalWidth;
        window.imgH = img.naturalHeight;
        document.getElementById('status').textContent = 'READY';
        document.title = 'READY';
    } catch(e) {
        document.getElementById('status').textContent = 'ERROR:' + e.message;
        document.title = 'ERROR';
    }
}
run();
</script>
</body></html>"""


def decode_xcaptcha_text_image_browser(b64_str: str) -> Image.Image:
    """
    Decode xCaptcha text-type image using browser rendering.
    Browsers have lenient PNG parsers that handle the deliberate corruption
    in xCaptcha's API responses.
    
    Returns a PIL Image.
    """
    from hermes_tools import terminal, browser_navigate, browser_snapshot, browser_console
    
    # Save the HTML decoder page
    html = DECODER_HTML.replace('__B64_PLACEHOLDER__', b64_str)
    html_path = '/tmp/xcaptcha_decoder.html'
    with open(html_path, 'w') as f:
        f.write(html)
    
    # We can't directly use browser tools here — this is called from async context
    # Instead, we'll save the image data for the browser step
    raise NotImplementedError("Use browser_decode_image() standalone function instead")


def extract_text_cells(img: Image.Image, bx: int, by: int, ref_ratio: float = 0.19):
    """
    Extract reference text + grid cells from xCaptcha text type image.
    
    Layout:
    - Top ~19%: Reference section showing target characters
    - Bottom ~81%: bx*by grid of character blocks
    
    Returns: (ref_img, cells_dict)
    """
    w, h = img.size
    rh = int(h * ref_ratio)
    cw = w // bx
    ch = (h - rh) // by
    
    ref = img.crop((0, 0, w, rh))
    cells = {}
    for row in range(by):
        for col in range(bx):
            x1 = col * cw
            y1 = rh + row * ch
            cells[row * bx + col] = img.crop((x1, y1, x1 + cw, y1 + ch))
    
    return ref, cells


def compare_cells(ref_img: Image.Image, cells: dict, bx: int, by: int) -> list:
    """
    Compare reference text with grid cells using pixel similarity.
    Returns ordered list of cell indices that best match the reference.
    
    For xCaptcha text type:
    - Reference shows the target characters to find
    - Grid shows many characters, user must click the matching ones in order
    - Answer format: comma-separated x,y center coordinates of matching cells
    """
    ref_arr = np.array(ref_img).astype(float)
    
    scores = {}
    for idx, cell in cells.items():
        cell_arr = np.array(cell).astype(float)
        # Resize cell to match reference dimensions for comparison
        if cell_arr.shape != ref_arr.shape:
            cell_resized = cell.resize((ref_img.width, ref_img.height), Image.LANCZOS)
            cell_arr = np.array(cell_resized).astype(float)
        
        # Compute similarity (lower = more similar)
        diff = np.abs(ref_arr - cell_arr).mean()
        scores[idx] = diff
    
    # Sort by similarity (lower diff = better match)
    sorted_cells = sorted(scores.items(), key=lambda x: x[1])
    return sorted_cells


def get_cell_center(idx: int, bx: int, by: int, cell_w: int, cell_h: int, 
                     offset_x: int = 0, offset_y: int = 0) -> tuple:
    """Get the center (x, y) coordinates of a cell in the grid."""
    row = idx // bx
    col = idx % bx
    cx = offset_x + col * cell_w + cell_w // 2
    cy = offset_y + row * cell_h + cell_h // 2
    return (cx, cy)
