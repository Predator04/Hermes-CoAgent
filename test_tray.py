"""Test pystray import and basic functionality."""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

ICON_SIZE = 64

try:
    import pystray
    from PIL import Image, ImageDraw
    print("pystray imported OK")
except ImportError as e:
    print(f"pystray NOT available: {e}")
    sys.exit(1)

try:
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (17, 17, 34, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, ICON_SIZE - 4, ICON_SIZE - 4], fill=(102, 126, 234, 255))
    print("Icon image created OK")
except Exception as e:
    print(f"Icon creation failed: {e}")
    sys.exit(1)

print("Full pystray test PASSED")
