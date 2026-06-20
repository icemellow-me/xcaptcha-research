#!/usr/bin/env python3
"""
xCaptcha Image Deobfuscation — standalone script.

Demonstrates the byte-substitution obfuscation used by xCaptcha
on PNG images served via the `img` field in text-type task responses.

Obfuscation:
  '/' (0x2F) → '|b|'   (3 bytes)
  '&' (0x26) → '(a)'   (3 bytes)

Applied to raw PNG bytes BEFORE base64 encoding.
Reversal: base64 decode → replace '|b|'→'/', '(a)'→'&' → valid PNG.
"""

import base64
import sys
from PIL import Image
import io


def deobfuscate(img_b64: str) -> bytes:
    """Reverse xCaptcha's PNG byte obfuscation."""
    raw = base64.b64decode(img_b64)
    raw_str = raw.decode("latin-1")
    deobfuscated = raw_str.replace("|b|", "/").replace("(a)", "&")
    return deobfuscated.encode("latin-1")


def obfuscate(png_bytes: bytes) -> str:
    """Apply xCaptcha's PNG byte obfuscation (for verification)."""
    raw_str = png_bytes.decode("latin-1")
    obfuscated = raw_str.replace("/", "|b|").replace("&", "(a)")
    return base64.b64encode(obfuscated.encode("latin-1")).decode()


def main():
    if len(sys.argv) < 2:
        print("Usage: deobfuscate.py <base64_img_string> [output.png]")
        print("       deobfuscate.py --test")
        sys.exit(1)

    if sys.argv[1] == "--test":
        # Round-trip test with a small PNG
        img = Image.new("RGB", (2, 2))
        img.putpixel((0, 0), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original = buf.getvalue()

        obf = obfuscate(original)
        restored = deobfuscate(obf)

        assert original == restored, "Round-trip failed!"
        print("✓ Round-trip test passed: obfuscate → deobfuscate = original")
        return

    img_b64 = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/xc_deobfuscated.png"

    png_bytes = deobfuscate(img_b64)
    img = Image.open(io.BytesIO(png_bytes))
    img.save(out_path)
    print(f"Deobfuscated image saved to {out_path} ({img.size} {img.mode})")


if __name__ == "__main__":
    main()
