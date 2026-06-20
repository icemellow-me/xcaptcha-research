"""Debug: dump all chunks in the raw xCaptcha PNG."""
import asyncio, aiohttp, json, base64, struct, zlib

HOST_API = 'https://api.xcaptcha.com'

async def main():
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        async with s.get(f'{HOST_API}/captcha/11aa62606fb968f3674742df60598957/task?lang=en') as r:
            task = await r.json()
    
    raw = base64.b64decode(task['img'])
    print(f'Total bytes: {len(raw)}')
    
    # Walk chunks
    pos = 8
    while pos < len(raw):
        if pos + 8 > len(raw):
            print(f'  EOF at {pos}')
            break
        chunk_len = struct.unpack('>I', raw[pos:pos+4])[0]
        chunk_type_bytes = raw[pos+4:pos+8]
        
        # Is this a valid chunk type?
        is_valid = all(65 <= b <= 122 for b in chunk_type_bytes)  # rough ASCII check
        
        if not is_valid:
            print(f'  INVALID chunk at pos {pos}: type={chunk_type_bytes.hex()} declared_len={chunk_len}')
            # Show context
            print(f'  Context: {raw[pos:pos+32].hex()}')
            
            # Maybe the issue is that PLTE is longer than 768?
            # Or there's something weird in between
            # Let's scan forward for known chunk types
            for search in [b'IDAT', b'tRNS', b'pHYs', b'IEND']:
                idx = raw.find(search, pos)
                if idx > 0:
                    print(f'  Found {search} at offset {idx} (relative {idx-pos})')
            break
        
        chunk_type = chunk_type_bytes.decode('ascii')
        chunk_data_start = pos + 8
        chunk_end = chunk_data_start + chunk_len + 4  # +4 for CRC
        
        if chunk_end > len(raw):
            print(f'  Chunk {chunk_type}: len={chunk_len} would end at {chunk_end}, file={len(raw)}')
            break
        
        # Verify CRC
        payload = raw[pos+4:chunk_data_start + chunk_len]
        expected_crc = zlib.crc32(payload) & 0xffffffff
        actual_crc = struct.unpack('>I', raw[chunk_end-4:chunk_end])[0]
        crc_status = 'OK' if expected_crc == actual_crc else f'BAD(exp={expected_crc:#010x} got={actual_crc:#010x})'
        
        print(f'  Chunk {chunk_type}: len={chunk_len}, pos={pos}-{chunk_end}, CRC={crc_status}')
        pos = chunk_end

if __name__ == '__main__':
    asyncio.run(main())
