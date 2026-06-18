import winrt.windows.graphics.imaging as imaging
import winrt.windows.media.ocr as ocr
import winrt.windows.storage.streams as streams
import winrt.windows.globalization as gl
import io
from PIL import Image, ImageDraw

# Create a simple test image with text
img = Image.new('RGB', (400, 100), (255, 255, 255))
draw = ImageDraw.Draw(img)
draw.text((20, 30), 'Hello World from Windows OCR GPU', fill=(0, 0, 0))

buf = io.BytesIO()
img.save(buf, format='PNG')
buf.seek(0)

data = buf.read()
ras = streams.InMemoryRandomAccessStream()
ras.write_async(data).get()
ras.seek(0)

decoder = imaging.BitmapDecoder.create_async(ras).get()
bitmap = decoder.get_software_bitmap_async().get()

lang = gl.Language('en-US')
eng = ocr.OcrEngine.try_create_from_language(lang)
print(f'Engine created: {eng is not None}')

result = eng.recognize_async(bitmap).get()
print(f'Lines: {len(result.lines)}')
for line in result.lines:
    print(f'  Line: "{line.text}"')
    for word in line.words:
        bbox = word.bounding_rect
        print(f'    Word: "{word.text}" at ({int(bbox.x)},{int(bbox.y)}-{int(bbox.width)}x{int(bbox.height)})')
