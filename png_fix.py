import struct, zlib, io
from PIL import Image

def fix_png_crc(data: bytes) -> bytes:
    """Fix CRC values for all chunks in a PNG that has bad CRCs."""
    data = bytearray(data)
    pos = 8  # Skip PNG signature
    
    while pos < len(data):
        if pos + 8 > len(data):
            break
        chunk_len = struct.unpack('>I', data[pos:pos+4])[0]
        chunk_type = bytes(data[pos+4:pos+8])
        
        if not all(32 <= b < 127 for b in chunk_type):
            break
        
        chunk_end = pos + 4 + 4 + chunk_len + 4
        if chunk_end > len(data):
            break
        
        # Fix CRC
        chunk_data = bytes(data[pos+4:pos+8+chunk_len])  # type + data
        correct_crc = zlib.crc32(chunk_data) & 0xffffffff
        crc_offset = pos + 8 + chunk_len  # CRC position
        struct.pack_into('>I', data, crc_offset, correct_crc)
        
        pos = chunk_end
    
    return bytes(data)


def decode_xcaptcha_img(b64_str: str) -> Image.Image:
    """Decode xCaptcha base64 image, fixing CRC issues if present."""
    import base64
    raw = base64.b64decode(b64_str)
    
    try:
        return Image.open(io.BytesIO(raw))
    except Exception:
        # Fix CRCs and retry
        fixed = fix_png_crc(raw)
        return Image.open(io.BytesIO(fixed))
