"""
xCaptcha text-type solver — Uses browser rendering for image decode.

Since xCaptcha's PNG images have corrupt internal structure (bad CRCs + 
garbage bytes between IDAT chunks), we use the browser to render the
challenge image, then extract cells from the rendered canvas.
"""
import asyncio, aiohttp, json, base64, struct, zlib, io, os, time, re
import numpy as np
from PIL import Image

# The xCaptcha text-type actually works in the browser without issue
# because browsers have lenient PNG parsers that ignore CRC errors.
# So we'll use the browser to:
# 1. Load the xCaptcha widget
# 2. Navigate to the task page  
# 3. Extract the rendered canvas/image data
# 4. Extract cells from the image

async def get_text_task(sitekey: str, lang: str = "en") -> dict:
    """Fetch a text-type task from xCaptcha API."""
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        url = f'https://api.xcaptcha.com/captcha/{sitekey}/task?lang={lang}'
        async with s.get(url) as r:
            return await r.json()


def decode_via_raw_png(b64_str: str) -> Image.Image | None:
    """
    Try to decode xCaptcha PNG by extracting zlib from raw binary.
    The trick: find every zlib header (78 xx) in the raw bytes,
    attempt decompression from each, and use the one that works.
    """
    raw = base64.b64decode(b64_str)
    
    # Scan for zlib headers
    zlib_headers = [b'\x78\x01', b'\x78\x5e', b'\x78\x9c', b'\x78\xda']
    
    for header in zlib_headers:
        pos = 0
        while True:
            idx = raw.find(header, pos)
            if idx < 0:
                break
            
            # Try decompressing from this point to end of file
            try:
                d = zlib.decompressobj()
                result = d.decompress(raw[idx:])
                if len(result) > 100:  # Got meaningful data
                    return result
            except:
                pass
            
            # Try: from this header to just before IDAT CRC boundary issues
            # Find next IDAT type marker after this position
            next_idat = raw.find(b'IDAT', idx + 2)
            if next_idat > 0:
                # Data extends from idx to end of next IDAT chunk data
                next_len = struct.unpack('>I', raw[next_idat-4:next_idat])[0]
                end = next_idat + 4 + next_len
                try:
                    d = zlib.decompressobj()
                    result = d.decompress(raw[idx:end])
                    if len(result) > 100:
                        return result
                except:
                    pass
            
            pos = idx + 2
    
    return None


def decode_xcaptcha_image_browser(task: dict) -> Image.Image:
    """
    Decode xCaptcha image using the browser (most reliable).
    Injects the image into an HTML page, renders via <canvas>,
    then extracts pixels.
    """
    # This is handled by the browser tools
    pass


def decode_xcaptcha_image(task: dict) -> Image.Image:
    """
    Master decoder for xCaptcha images with all fallback strategies.
    
    The xCaptcha API returns PNG images that have:
    1. Bad CRCs on PLTE/pHYs chunks
    2. Garbage bytes INSERTED between IDAT chunks (breaking zlib)
    
    Strategy:
    1. Try standard PIL decode (works for some instances)
    2. Fix CRCs then try PIL  
    3. Try raw zlib decompression scanning for valid streams
    4. Use browser rendering as last resort
    """
    b64_str = task.get('img', '')
    raw = base64.b64decode(b64_str) if b64_str else b''
    
    # Strategy 1: Try PIL directly (some images are fine)
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img.convert('RGB')
    except:
        pass
    
    # Strategy 2: Fix CRCs
    try:
        fixed = _fix_png_crcs(raw)
        img = Image.open(io.BytesIO(fixed))
        img.load()
        return img.convert('RGB')
    except:
        pass
    
    # Strategy 3: Extract zlib from raw binary
    decompressed = decode_via_raw_png(b64_str)
    if decompressed:
        return _build_from_decompressed(decompressed, raw)
    
    # Strategy 4: Browser rendering
    raise ValueError(
        "Cannot decode xCaptcha PNG programmatically. "
        "Use browser rendering (load xCaptcha widget, capture canvas)."
    )
