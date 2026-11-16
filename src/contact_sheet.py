"""Контактный лист для визуальной проверки кандидатов: миниатюры с номерами в сетке."""
import sys
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
cand = pd.read_csv(ROOT / "data/interim/car_enrichment/candidates.csv")
start, end = int(sys.argv[1]), int(sys.argv[2])
out = Path(sys.argv[3])
sub = cand.iloc[start:end]
cols, cell = 4, 330
rows = (len(sub) + cols - 1) // cols
sheet = Image.new("RGB", (cols * cell, rows * cell), "white")
d = ImageDraw.Draw(sheet)
for k, r in enumerate(sub.itertuples()):
    im = Image.open(ROOT / r.file_path)
    im.thumbnail((cell - 6, cell - 26))
    x, y = (k % cols) * cell, (k // cols) * cell
    sheet.paste(im, (x + 3, y + 22))
    d.rectangle([x, y, x + 120, y + 20], fill="black")
    d.text((x + 4, y + 4), f"{r.id[-4:]} {r.stratum[:10]}", fill="yellow")
sheet.save(out, quality=85)
print(out, sheet.size)
