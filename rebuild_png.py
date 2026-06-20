"""Rebuild xCaptcha PNG by parsing with known chunk positions."""
import asyncio, aiohttp, json, base64, struct, zlib, io, os, sys

HOST_API = 'https://api.xcaptcha.com'

async def main():
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        async with s.get(f'{HOST_API}/captcha/11aa62606fb968f3674742df60598957/task?lang=en') as r:
            task = await r.json()
    
    raw = base64.b64decode(task['img'])
    
    # Known chunk positions from debug:
    # IHDR: 8-33 (OK CRC)
    # PLTE: 33-813 (BAD CRC, data is 33+8=41 to 41+768=809, CRC at 809-812)
    # pHYs: 813-846 (len=9, type at 817, data 821-829, CRC 829-832)  
    # IDAT: at 842 relative to 813 = 813+4(len)+4(type)=813+8+9(data)+4(CRC)=813+25=838?
    # Wait, pHYs: pos=813, len=9, so: 813 + 4(len) + 4(type) + 9(data) + 4(CRC) = 813 + 21 = 834
    # But IDAT was found at 813+29 = 842. Let me check...
    # 813 + 4(len) + 4(type) + 9(data) + 4(CRC) = 813+4+4+9+4 = 834
    # Hmm, 842 != 834. That means there's 8 bytes between pHYs end and IDAT start.
    # Actually the context showed: ...fbc6e7f3 00000009 70485973...
    # fbc6e7f3 is the PLTE CRC (4 bytes at pos 809-812)
    # Then pHYs starts at 813
    # pHYs: 00000009 (len=9) 70485973 (type=pHYs) ...9 bytes data... + 4 bytes CRC
    # pHYs total: 813 + 4 + 4 + 9 + 4 = 834
    
    # Wait, looking at context: 844d23dd000000097048597300000ec400000ec401952b0e1b00002000494441
    # Let me re-parse:
    # 844d23dd = PLTE CRC (at bytes 809-812)
    # 00000009 = pHYs length
    # 70485973 = "pHYs"  
    # 00000ec4 00000ec4 = pixels per unit X and Y
    # 01 = unit specifier (meter)
    # 952b0e1b = pHYs CRC? No, only 9 bytes of data: 00000ec4 00000ec4 01
    # Then CRC of pHYs
    
    # Let me just rebuild from known positions
    sig = raw[:8]
    ihdr = raw[8:33]  # IHDR chunk
    
    # PLTE: keep data, fix CRC
    plte_header = raw[33:41]  # len + type
    plte_data = raw[41:809]  # 768 bytes
    plte_crc = struct.pack('>I', zlib.crc32(raw[37:41] + plte_data) & 0xffffffff)  # type+data
    
    # pHYs starts at 813: raw[813:834]
    phys_chunk = raw[813:834]
    # Fix pHYs CRC too
    phys_len = struct.unpack('>I', phys_chunk[0:4])[0]  # 9
    phys_type = phys_chunk[4:8]
    phys_data = phys_chunk[8:8+phys_len]
    phys_crc = struct.pack('>I', zlib.crc32(phys_type + phys_data) & 0xffffffff)
    phys_fixed = phys_chunk[:8+phys_len] + phys_crc
    
    # IDAT: starts around 834-842 area
    # Let me find it properly
    idat_start = raw.find(b'IDAT') - 4  # 4 bytes before "IDAT" is the length
    idat_len = struct.unpack('>I', raw[idat_start:idat_start+4])[0]
    idat_end = idat_start + 4 + 4 + idat_len + 4
    print(f'IDAT: start={idat_start}, len={idat_len}, end={idat_end}')
    
    idat_chunk = raw[idat_start:idat_end]
    # Fix IDAT CRC
    idat_type = idat_chunk[4:8]
    idat_data = idat_chunk[8:8+idat_len]
    idat_crc = struct.pack('>I', zlib.crc32(idat_type + idat_data) & 0xffffffff)
    idat_fixed = idat_chunk[:8+idat_len] + idat_crc
    
    # IEND
    iend_pos = raw.find(b'IEND') - 4
    iend_chunk = raw[iend_pos:iend_pos+12]  # 4(len=0)+4(type)+4(CRC)
    
    # Rebuild PNG
    output = sig + ihdr + plte_header + plte_data + plte_crc + phys_fixed + idat_fixed + iend_chunk
    print(f'Rebuilt PNG: {len(output)} bytes')
    
    with open('/tmp/xc_rebuilt.png', 'wb') as f:
        f.write(output)
    
    # Test with PIL
    from PIL import Image
    img = Image.open(io.BytesIO(output))
    print(f'IMAGE: {img.size} {img.mode}')
    img.save('/tmp/xcaptcha_text_working.png')
    print('SUCCESS!')
    
    # Extract cells for analysis
    bx = task['blocks']['x']
    by = task['blocks']['y']
    w, h = img.size
    print(f'Grid: {bx}x{by}')
    
    # Determine reference/grid split
    # For 280x320 with 2x4 grid: each cell ~140x64
    # Reference takes roughly top 20-25%
    ref_h = 64  # Approximate
    cell_w = w // bx
    cell_h = (h - ref_h) // by
    
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
    
    ref = img.crop((0, 0, w, ref_h))
    ref.save(f'{cell_dir}/reference.png')
    print('Cells extracted!')

if __name__ == '__main__':
    asyncio.run(main())
