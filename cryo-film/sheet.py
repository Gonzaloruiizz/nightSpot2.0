import sys
from PIL import Image
out, files = sys.argv[1], sys.argv[2:]
cols = 2; w, h = 960, 402
rows = (len(files) + 1) // 2
W = Image.new('RGB', (cols * w, rows * h))
for i, f in enumerate(files):
    im = Image.open(f)
    if im.size[1] == 1080: im = im.crop((0, 138, 1920, 942))
    W.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
W.save(out, quality=85)
