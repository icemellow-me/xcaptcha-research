"""
xCaptcha image decoder v6 — handles the quirky xCaptcha PNG format.

The xCaptcha API's text-type PNGs have structural issues:
1. Bad CRCs on PLTE and pHYs chunks
2. Garbage bytes between IDAT chunks
3. Varying offsets between captcha instances

Strategy: Extract ONLY the zlib stream from the IDAT data,
skip everything that's not part of the zlib deflate stream.
"""
import base64, struct, zlib, io, os
import numpy as np
from PIL import Image


def extract_zlib_stream(raw: bytes) -> bytes:
    """
    Find and extract the zlib stream from xCaptcha PNG.
    We locate the first zlib header (78 9c/78 01/78 da/78 5e) in IDAT data
    and try to decompress, falling back to scanning for valid deflate blocks.
    """
    # Find IDAT type markers and grab their data
    chunks_data = []
    pos = 8
    while pos < len(raw):
        idx = raw.find(b'IDAT', pos)
        if idx < 0:
            break
        # Length is 4 bytes before the type
        if idx < 4:
            break
        chunk_len = struct.unpack('>I', raw[idx-4:idx])[0]
        if chunk_len > 0 and chunk_len < len(raw):
            data_start = idx + 4
            data_end = data_start + chunk_len
            if data_end <= len(raw):
                chunks_data.append(raw[data_start:data_end])
        pos = idx + 4
    
    if not chunks_data:
        raise ValueError("No IDAT data found")
    
    # Try combining all IDAT data
    combined = b''.join(chunks_data)
    try:
        return zlib.decompress(combined)
    except:
        pass
    
    # Try each chunk individually (one might contain the full stream)
    for chunk in chunks_data:
        try:
            return zlib.decompress(chunk)
        except:
            pass
        # Try DecompressObj to get partial results
        try:
            d = zlib.decompressobj()
            result = d.decompress(chunk)
            if result:
                return result
        except:
            pass
    
    # Last resort: use the browser approach
    raise ValueError("Cannot decompress xCaptcha PNG — need browser rendering fallback")


def decode_xcaptcha_png(raw: bytes) -> Image.Image:
    """Decode xCaptcha PNG — try multiple strategies."""
    # Strategy 1: Maybe PIL can open it after all (some are ok)
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        return img.convert('RGB')
    except:
        pass
    
    # Strategy 2: Fix all CRCs and try PIL again
    try:
        fixed = fix_all_crcs(raw)
        img = Image.open(io.BytesIO(fixed))
        img.load()
        return img.convert('RGB')
    except:
        pass
    
    # Strategy 3: Manual decode with zlib stream extraction
    try:
        # Parse IHDR
        ihdr_pos = raw.find(b'IHDR')
        if ihdr_pos >= 8:
            ihdr = raw[ihdr_pos+4:ihdr_pos+4+13]
            width = struct.unpack('>I', ihdr[0:4])[0]
            height = struct.unpack('>I', ihdr[4:8])[0]
            bit_depth = ihdr[8]
            color_type = ihdr[9]
            
            # Parse PLTE
            plte_pos = raw.find(b'PLTE')
            palette = None
            if plte_pos >= 0:
                plte_len = struct.unpack('>I', raw[plte_pos-4:plte_pos])[0]
                palette = raw[plte_pos+4:plte_pos+4+plte_len]
            
            # Extract and decompress IDAT
            decompressed = extract_zlib_stream(raw)
            
            # Build image from decompressed data
            return build_image_from_raw(decompressed, width, height, 
                                        bit_depth, color_type, palette)
    except Exception as e:
        pass
    
    raise ValueError("All PNG decoding strategies failed for xCaptcha image")


def fix_all_crcs(raw: bytes) -> bytes:
    """Fix ALL CRC values in a PNG by walking chunks and recalculating."""
    out = bytearray(raw[:8])  # Keep signature
    pos = 8
    
    while pos + 8 <= len(raw):
        chunk_len = struct.unpack('>I', raw[pos:pos+4])[0]
        chunk_type = raw[pos+4:pos+8]
        
        # Check if this looks like a valid chunk
        try:
            ct_str = chunk_type.decode('ascii')
            if not all(65 <= b <= 122 for b in chunk_type):
                # Not a valid chunk type — scan for next valid one
                for start in range(pos+1, min(pos+200, len(raw)-8)):
                    test_type = raw[start+4:start+8]
                    test_len = struct.unpack('>I', raw[start:start+4])[0]
                    if all(65 <= b <= 122 for b in test_type):
                        if test_len < len(raw) and start + 8 + test_len + 4 <= len(raw):
                            pos = start
                            break
                else:
                    break
                continue
        except:
            break
        
        # Valid chunk header — extract data and fix CRC
        data_end = pos + 8 + chunk_len
        if data_end + 4 > len(raw):
            # Truncated — just copy remaining
            out.extend(raw[pos:])
            break
        
        chunk_data = raw[pos+8:data_end]
        crc_data = chunk_type + chunk_data
        new_crc = zlib.crc32(crc_data) & 0xffffffff
        
        out.extend(raw[pos:pos+8])       # length + type
        out.extend(chunk_data)            # data
        out.extend(struct.pack('>I', new_crc))  # fixed CRC
        
        pos = data_end + 4  # Skip old CRC
    
    return bytes(out)


def build_image_from_raw(decompressed, width, height, bit_depth, color_type, palette=None):
    """Build a PIL Image from decompressed PNG pixel data."""
    if color_type == 3:  # Indexed
        bpp = 1
        row_bytes = width
    elif color_type == 2:  # RGB
        bpp = 3
        row_bytes = width * 3
    elif color_type == 0:  # Grayscale
        bpp = 1
        row_bytes = width
    else:
        bpp = 4
        row_bytes = width * 4
    
    stride = 1 + row_bytes
    pixels = np.zeros((height, row_bytes), dtype=np.int32)
    
    for y in range(height):
        rs = y * stride
        if rs + stride > len(decompressed):
            break
        
        ft = decompressed[rs]
        rd = list(decompressed[rs+1:rs+1+row_bytes])
        
        if ft == 0:
            pixels[y] = rd
        elif ft == 1:
            for x in range(bpp, row_bytes):
                rd[x] = (rd[x] + rd[x - bpp]) & 0xFF
            pixels[y] = rd
        elif ft == 2:
            if y > 0:
                for x in range(row_bytes):
                    rd[x] = (rd[x] + int(pixels[y-1, x])) & 0xFF
            pixels[y] = rd
        elif ft == 3:
            for x in range(row_bytes):
                l = int(pixels[y, x - bpp]) if x >= bpp else 0
                u = int(pixels[y-1, x]) if y > 0 else 0
                rd[x] = (rd[x] + (l + u) // 2) & 0xFF
            pixels[y] = rd
        elif ft == 4:
            for x in range(row_bytes):
                l = int(pixels[y, x - bpp]) if x >= bpp else 0
                u = int(pixels[y-1, x]) if y > 0 else 0
                ul = int(pixels[y-1, x - bpp]) if y > 0 and x >= bpp else 0
                p = l + u - ul
                pa, pb, pc = abs(p - l), abs(p - u), abs(p - ul)
                n = l if pa <= pb and pa <= pc else (u if pb <= pc else ul)
                rd[x] = (rd[x] + n) & 0xFF
            pixels[y] = rd
    
    pixels = pixels.astype(np.uint8)
    
    if color_type == 3 and palette:
        pal = np.frombuffer(palette, dtype=np.uint8).reshape(-1, 3)
        idx = pixels.reshape(height, width)
        mx = int(idx.max())
        if mx >= len(pal):
            pal = np.vstack([pal, np.zeros((mx + 1 - len(pal), 3), dtype=np.uint8)])
        return Image.fromarray(pal[idx], 'RGB')
    elif color_type == 2:
        return Image.fromarray(pixels.reshape(height, width, 3), 'RGB')
    return Image.fromarray(pixels.reshape(height, width), 'L')


def decode_xcaptcha_image(b64_str: str) -> Image.Image:
    raw = base64.b64decode(b64_str)
    return decode_xcaptcha_png(raw)


def extract_text_cells(img, bx, by, ref_ratio=0.19):
    w, h = img.size
    rh = int(h * ref_ratio)
    cw, ch = w // bx, (h - rh) // by
    ref = img.crop((0, 0, w, rh))
    cells = {}
    for row in range(by):
        for col in range(bx):
            x1, y1 = col * cw, rh + row * ch
            cells[row * bx + col] = img.crop((x1, y1, x1 + cw, y1 + ch))
    return ref, cells


if __name__ == '__main__':
    import asyncio, aiohttp, json
    
    async def test():
        async with aiohttp.ClientSession(
            headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
        ) as s:
            async with s.get('https://api.xcaptcha.com/captcha/11aa62606fb968f3674742df60598957/task?lang=en') as r:
                task = await r.json()
        
        img = decode_xcaptcha_image(task['img'])
        print(f'Image: {img.size} {img.mode}')
        img.save('/tmp/xcaptcha_decoded.png')
        print('Saved!')
        
        bx, by = task['blocks']['x'], task['blocks']['y']
        ref, cells = extract_text_cells(img, bx, by)
        ref.save('/tmp/xc_ref.png')
        d = '/tmp/xcaptcha_cells'
        os.makedirs(d, exist_ok=True)
        for idx, c in cells.items():
            c.save(f'{d}/cell_{idx}.png')
        print(f'Ref + {len(cells)} cells saved')
    
    asyncio.run(test())
