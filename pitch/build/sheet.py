# Контактные листы из снимков: python sheet.py <папка> <префикс результата> [колонок=2] [штук на лист=6] [ширина ячейки=960]
import sys, glob, os
from PIL import Image

src, out = sys.argv[1], sys.argv[2]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 2
per = int(sys.argv[4]) if len(sys.argv) > 4 else 6
cw = int(sys.argv[5]) if len(sys.argv) > 5 else 960
files = sorted(glob.glob(os.path.join(src, '*.jpg')))
ch = cw * 9 // 16
for n in range(0, len(files), per):
    part = files[n:n + per]
    rows = (len(part) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cw + (cols + 1) * 8, rows * ch + (rows + 1) * 8), (60, 62, 68))
    for i, f in enumerate(part):
        im = Image.open(f).convert('RGB').resize((cw, ch), Image.LANCZOS)
        sheet.paste(im, (8 + (i % cols) * (cw + 8), 8 + (i // cols) * (ch + 8)))
    name = '%s-%d.jpg' % (out, n // per + 1)
    sheet.save(name, quality=88)
    print(name, [os.path.basename(f) for f in part])
