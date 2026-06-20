"""Use pypng to decode the xCaptcha image (more lenient than PIL)."""
import asyncio, aiohttp, json, base64, struct, zlib, io, sys, os
import png

HOST_API = 'https://api.xcaptcha.com'

def fix_png(data: bytes) -> bytes:
    """Rewrite PNG with correct CRC for every chunk."""
    pos = 8
    output = bytearray(data[:8])
    while pos < len(data):
        if pos + 8 > len(data):
            break
        chunk_len = struct.unpack('>I', data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        if not all(32 <= b < 127 for b in chunk_type):
            break
        chunk_end = pos + 4 + 4 + chunk_len + 4
        if chunk_end > len(data):
            output.extend(data[pos:])
            break
        payload = data[pos+4:pos+8+chunk_len]
        crc = zlib.crc32(payload) & 0xffffffff
        output.extend(data[pos:pos+8+chunk_len])
        output.extend(struct.pack('>I', crc))
        pos = chunk_end
    return bytes(output)

async def main():
    sitekey = '11aa62606fb968f3674742df60598957'
    
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        async with s.get(f'{HOST_API}/captcha/{sitekey}/task?lang=en') as r:
            task = await r.json()
    
    img_b64 = task['img']
    raw = base64.b64decode(img_b64)
    fixed = fix_png(raw)
    
    # Save fixed PNG
    with open('/tmp/xc_fixed3.png', 'wb') as f:
        f.write(fixed)
    
    # Try pypng reader (more lenient)
    try:
        reader = png.Reader(bytes=fixed)
        w, h, pixels, metadata = reader.read()
        print(f'pypng: {w}x{h}, metadata={metadata}')
        
        # Convert to PIL-compatible via numpy
        import numpy as np
        from PIL import Image
        
        rows = list(pixels)
        if metadata.get('alpha'):
            arr = np.array(rows, dtype=np.uint8).reshape(h, w, 4)
            img = Image.fromarray(arr, 'RGBA')
        elif metadata.get('palette'):
            arr = np.array(rows, dtype=np.uint8).reshape(h, w)
            # Get palette
            palette = metadata['palette']
            pal_arr = np.array(list(palette), dtype=np.uint8).reshape(-1, 3)
            img = Image.fromarray(arr, 'P')
            pal_img = []
            for r_val, g_val, b_val in pal_arr:
                pal_img.extend([r_val, g_val, b_val])
            img.putpalette(pal_img)
        else:
            arr = np.array(rows, dtype=np.uint8).reshape(h, w, 3)
            img = Image.fromarray(arr, 'RGB')
        
        print(f'Image via pypng: {img.size} {img.mode}')
        img.save('/tmp/xcaptcha_text_working.png')
        print('Saved!')
        
    except Exception as e:
        print(f'pypng error: {e}')
        # Try even more aggressive: decompress IDAT directly
        import re
        print('Trying IDAT decompression directly...')
        
        # Collect all IDAT chunks
        pos = 8
        idat_data = b''
        while pos < len(fixed):
            if pos + 8 > len(fixed):
                break
            chunk_len = struct.unpack('>I', fixed[pos:pos+4])[0]
            chunk_type = fixed[pos+4:pos+8]
            if chunk_type == b'IDAT':
                idat_data += fixed[pos+8:pos+8+chunk_len]
            pos += 4 + 4 + chunk_len + 4
        
        # Decompress
        try:
            decompressed = zlib.decompress(idat_data)
            print(f'IDAT decompressed: {len(decompressed)} bytes')
            # Parse IHDR for dimensions
            ihdr = fixed[16:29]  # after len(4) + type(4)
            w_ihdr = struct.unpack('>I', ihdr[0:4])[0]
            h_ihdr = struct.unpack('>I', ihdr[4:8])[0]
            bit_depth = ihdr[8]
            color_type = ihdr[9]
            print(f'IHDR: {w_ihdr}x{h_ihdr}, bit_depth={bit_depth}, color_type={color_type}')
        except Exception as e2:
            print(f'Decompress error: {e2}')

if __name__ == '__main__':
    asyncio.run(main())
