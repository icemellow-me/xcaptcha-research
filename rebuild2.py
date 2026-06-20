"""Rebuild xCaptcha PNG handling multiple IDAT chunks."""
import asyncio, aiohttp, json, base64, struct, zlib, io, os

HOST_API = 'https://api.xcaptcha.com'

def rebuild_from_raw(raw: bytes) -> bytes:
    """Parse and rebuild PNG with fixed CRCs, handling all chunk types."""
    chunks = []
    pos = 8  # Skip signature
    sig = raw[:8]
    
    while pos < len(raw):
        if pos + 8 > len(raw):
            break
        chunk_len = struct.unpack('>I', raw[pos:pos+4])[0]
        chunk_type_bytes = raw[pos+4:pos+8]
        
        is_valid = all(65 <= b <= 122 for b in chunk_type_bytes)
        if not is_valid:
            # Try to find next valid chunk
            print(f'  Invalid chunk at {pos}, scanning forward...')
            # Scan byte by byte for known chunk types
            for candidate in [b'IHDR', b'PLTE', b'IDAT', b'tRNS', b'pHYs', b'sRGB', b'gAMA', b'cHRM', b'iTXt', b'tEXt', b'IEND']:
                idx = raw.find(candidate, pos + 4)
                if idx > 0 and idx < len(raw) - 8:
                    # The length should be 4 bytes before the type
                    candidate_start = idx - 4
                    # Verify it could be a valid length
                    test_len = struct.unpack('>I', raw[candidate_start:candidate_start+4])[0]
                    if test_len < len(raw):  # Reasonable length
                        pos = candidate_start
                        print(f'  Resuming at {pos} ({candidate.decode()} chunk)')
                        break
            else:
                break
            continue
        
        chunk_type = chunk_type_bytes.decode('ascii')
        chunk_data_start = pos + 8
        chunk_end = chunk_data_start + chunk_len + 4  # data + CRC
        
        if chunk_end > len(raw) + 4:
            print(f'  Chunk {chunk_type} at {pos}: len={chunk_len} exceeds file, truncating')
            chunk_end = len(raw)
        
        # Extract and fix CRC
        chunk_type_data = raw[pos+4:chunk_data_start + chunk_len]  # type + data
        correct_crc = struct.pack('>I', zlib.crc32(chunk_type_data) & 0xffffffff)
        
        chunk_bytes = raw[pos:chunk_data_start + chunk_len] + correct_crc
        chunks.append(chunk_bytes)
        print(f'  Chunk {chunk_type}: pos={pos}, len={chunk_len}, end={chunk_end}, CRC fixed')
        
        pos = chunk_end
    
    output = sig + b''.join(chunks)
    return output

async def main():
    async with aiohttp.ClientSession(
        headers={'Origin': 'https://xcaptcha.com', 'Referer': 'https://xcaptcha.com/'},
    ) as s:
        async with s.get(f'{HOST_API}/captcha/11aa62606fb968f3674742df60598957/task?lang=en') as r:
            task = await r.json()
    
    raw = base64.b64decode(task['img'])
    print(f'Raw: {len(raw)} bytes')
    
    # Find all IDAT occurrences
    pos = 0
    while True:
        idx = raw.find(b'IDAT', pos)
        if idx < 0:
            break
        idat_len = struct.unpack('>I', raw[idx-4:idx])[0]
        print(f'IDAT at {idx-4}: len={idat_len}')
        pos = idx + 4
    
    iend_idx = raw.find(b'IEND')
    if iend_idx > 0:
        print(f'IEND at {iend_idx-4}')
    
    # Rebuild
    fixed = rebuild_from_raw(raw)
    print(f'Rebuilt: {len(fixed)} bytes')
    
    with open('/tmp/xc_rebuilt2.png', 'wb') as f:
        f.write(fixed)
    
    from PIL import Image
    img = Image.open(io.BytesIO(fixed))
    print(f'IMAGE: {img.size} {img.mode}')
    img.save('/tmp/xcaptcha_text_working.png')
    print('SAVED!')

if __name__ == '__main__':
    asyncio.run(main())
