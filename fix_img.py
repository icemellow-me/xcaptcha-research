"""Fix xCaptcha PNG CRC and extract text captcha image for analysis."""
import asyncio, aiohttp, json, base64, struct, zlib, io, sys
from PIL import Image

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
    sitekey = sys.argv[1] if len(sys.argv) > 1 else '11aa62606fb968f3674742df60598957'
    out_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/xcaptcha_text_working.png'
    
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        async with s.get(f'{HOST_API}/captcha/{sitekey}/task?lang=en') as r:
            task = await r.json()
    
    img_b64 = task['img']
    raw = base64.b64decode(img_b64)
    fixed = fix_png(raw)
    
    img = Image.open(io.BytesIO(fixed))
    w, h = img.size
    bx = task['blocks']['x']
    by = task['blocks']['y']
    
    print(f'Image: {w}x{h}, mode={img.mode}')
    print(f'Grid: {bx}x{by} = {bx*by} blocks')
    img.save(out_path)
    print(f'Saved to {out_path}')
    
    # Also split into reference + grid sections for analysis
    # Top section = reference text, bottom = grid of characters
    # With 280x320 and 2x4 grid: cell_w=140, cell_h for grid = ~64
    # Reference area is roughly top 60px
    ref_h = int(h * 0.2)
    grid_h = h - ref_h
    cell_w = w // bx
    cell_h = grid_h // by
    
    print(f'Ref area: 0-{ref_h}px')
    print(f'Grid area: {ref_h}-{h}px, cell={cell_w}x{cell_h}')
    
    # Extract and save individual cells
    import os
    cell_dir = '/tmp/xcaptcha_cells'
    os.makedirs(cell_dir, exist_ok=True)
    
    for row in range(by):
        for col in range(bx):
            x1 = col * cell_w
            y1 = ref_h + row * cell_h
            x2 = x1 + cell_w
            y2 = y1 + cell_h
            cell = img.crop((x1, y1, x2, y2))
            cell.save(f'{cell_dir}/cell_{row}_{col}.png')
            print(f'  Cell [{row},{col}]: ({x1},{y1})-({x2},{y2})')
    
    # Extract reference section
    ref = img.crop((0, 0, w, ref_h))
    ref.save(f'{cell_dir}/reference.png')
    print(f'  Reference: saved')

if __name__ == '__main__':
    asyncio.run(main())
