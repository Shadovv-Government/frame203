"""Сбор реальных фотографий автомобилей для ручного обогащения подвыборки Open Images (класс Car).

Источники: Wikimedia Commons (API MediaWiki) и Openverse (API, фильтр лицензий CC0 / CC BY / CC BY-SA).
Для каждого файла сохраняются URL страницы, автор, лицензия, дата обращения, SHA-256 и dHash.
Квоты по стратам — словарь STRATA. Отбор кандидатов внутри выдачи поиска — случайный, seed 42.

Запуск из корня репозитория:  python src/build_car_enrichment.py
Результат: data/raw/images_new/<источник>/*.jpg и data/interim/car_enrichment/candidates.csv
Финальный набор утверждается после визуальной проверки (поле keep в car_enrichment_manifest.csv).
"""
from __future__ import annotations

import hashlib
import html
import io
import random
import re
import time
from pathlib import Path

import pandas as pd
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "images_new"
OUT = ROOT / "data" / "interim" / "car_enrichment"
OUT.mkdir(parents=True, exist_ok=True)
SEED = 42
ACCESS_DATE = "2026-11-01"
H = {"User-Agent": "frame203-coursework/1.0 (https://github.com/Shadovv-Government/frame203)"}
MAX_SIDE = 1024
ALLOWED = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? ?\d(\.\d)?|cc-by(-sa)?-\d(\.\d)?)", re.I)

STRATA = {
    # страта: (запросы Wikimedia, запросы Openverse, квота WM, квота OV)
    "rain_wet": (["cars street rain", "traffic rain wet road"], ["car rain street", "traffic rain"], 10, 6),
    "night": (["traffic night city cars", "cars street night"], ["traffic night street", "cars night city"], 10, 6),
    "dense_traffic": (["traffic jam cars", "parking lot cars"], ["traffic jam", "parking lot cars"], 10, 6),
    "snow_winter": (["cars snow street", "snow covered cars"], ["cars snow street", "winter traffic"], 8, 4),
    "unusual_view": (["street view from above cars", "cars aerial view street"], ["cars from above street", "car interior view road"], 8, 4),
}


def wm_search(q: str, limit: int = 50) -> list[dict]:
    p = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:bitmap",
         "gsrnamespace": 6, "gsrlimit": limit, "prop": "imageinfo",
         "iiprop": "url|size|extmetadata|mime", "iiurlwidth": MAX_SIDE}
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=p, headers=H, timeout=60)
    r.raise_for_status()
    out = []
    for page in r.json().get("query", {}).get("pages", {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        artist = re.sub(r"<[^>]+>", "", html.unescape(md.get("Artist", {}).get("value", ""))).strip()
        out.append({
            "source": "Wikimedia Commons", "title": page["title"], "landing_url": ii.get("descriptionurl"),
            "download_url": ii.get("thumburl") or ii.get("url"), "width": ii.get("width"), "height": ii.get("height"),
            "mime": ii.get("mime"), "license": lic, "license_url": md.get("LicenseUrl", {}).get("value", ""),
            "author": artist[:120], "provider": "wikimedia",
        })
    return out


def ov_search(q: str, limit: int = 20) -> list[dict]:
    p = {"q": q, "license": "cc0,by,by-sa", "page_size": limit, "mature": "false",
         "category": "photograph"}   # без ключа API: page_size <= 20
    r = requests.get("https://api.openverse.org/v1/images/", params=p, headers=H, timeout=60)
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        lic = f"CC {it['license'].upper()} {it.get('license_version') or ''}".strip().replace("CC CC0", "CC0")
        out.append({
            "source": "Openverse", "title": it.get("title") or it["id"], "landing_url": it.get("foreign_landing_url"),
            "download_url": it.get("url"), "width": it.get("width"), "height": it.get("height"),
            "mime": "image/" + (it.get("filetype") or "jpeg"), "license": lic, "license_url": it.get("license_url", ""),
            "author": (it.get("creator") or "")[:120], "provider": it.get("source") or it.get("provider"),
            "ov_id": it["id"],
        })
    return out


def dhash(img: Image.Image, size: int = 8) -> str:
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.tobytes())
    bits = "".join("1" if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else "0"
                   for r in range(size) for c in range(size))
    return f"{int(bits, 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# Flickr-идентификаторы изображений исходной подвыборки — чтобы не взять тот же кадр через Openverse
oi_meta = pd.read_csv(ROOT / "data" / "raw" / "oi" / "validation-images-with-rotation.csv",
                      usecols=["OriginalURL", "OriginalLandingURL"])
oi_flickr_ids = set(oi_meta.OriginalLandingURL.fillna("").str.extract(r"/(\d{6,})/?$")[0].dropna())

import sys
ROUND = int(sys.argv[1]) if len(sys.argv) > 1 else 1
if ROUND == 2:   # добор: точнее сформулированные запросы, Openverse недоступен (таймауты 01.11.2026)
    STRATA = {
        "rain_wet": (["car driving in rain road", "wet street parked cars rain"], [], 10, 0),
        "night": (["parked cars street at night", "car headlights street night"], [], 10, 0),
        "dense_traffic": (["cars parked along street", "city street traffic cars"], [], 12, 0),
        "snow_winter": (["car driving snow road", "cars parked snow street"], [], 8, 0),
        "unusual_view": (["car rear view road", "parking garage cars interior", "cars seen from bridge road"], [], 12, 0),
    }
rnd = random.Random(SEED + ROUND)
rows, hashes = [], []
if ROUND > 1 and (OUT / "candidates.csv").exists():
    prev = pd.read_csv(OUT / "candidates.csv")
    rows, hashes = prev.to_dict("records"), prev.dhash.tolist()
for stratum, (wm_q, ov_q, n_wm, n_ov) in STRATA.items():
    for src, queries, quota, fn in (("wm", wm_q, n_wm, wm_search), ("ov", ov_q, n_ov, ov_search)):
        pool = []
        for q in queries:
            try:
                pool += [dict(c, query=q) for c in fn(q)]
            except Exception as e:      # сбой API фиксируется, страта добирается из другого запроса
                print("search failed", src, q, e)
            time.sleep(1.0)
        rnd.shuffle(pool)
        taken = 0
        for c in pool:
            if taken >= quota:
                break
            if not c["download_url"] or not ALLOWED.match(c["license"].strip()):
                continue
            if "NC" in c["license"].upper() or "ND" in c["license"].upper():
                continue
            if (c["width"] or 0) < 640 or c["mime"] not in ("image/jpeg", "image/jpg", "image/png"):
                continue
            if src == "ov" and c["provider"] == "wikimedia":
                continue             # дубль канала Wikimedia
            fid = re.search(r"/(\d{6,})/?$", c["landing_url"] or "")
            if fid and fid.group(1) in oi_flickr_ids:
                continue             # кадр уже есть в Open Images
            if any(r_["landing_url"] == c["landing_url"] for r_ in rows):
                continue
            try:
                resp = requests.get(c["download_url"], headers=H, timeout=60)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            except Exception as e:
                print("download failed", c["download_url"][:80], e)
                continue
            if max(img.size) > MAX_SIDE:
                img.thumbnail((MAX_SIDE, MAX_SIDE))
            dh = dhash(img)
            if any(hamming(dh, h) <= 6 for h in hashes):
                continue             # почти-дубль уже взятого кадра
            hashes.append(dh)
            idx = len(rows) + 1
            fname = f"car_new_{idx:04d}.jpg"
            folder = RAW / ("wikimedia" if src == "wm" else "openverse")
            folder.mkdir(parents=True, exist_ok=True)
            img.save(folder / fname, quality=92)
            rows.append({**c, "id": f"img_new_{idx:04d}", "file_name": fname,
                         "file_path": str((folder / fname).relative_to(ROOT)).replace("\\", "/"),
                         "stratum": stratum, "saved_w": img.width, "saved_h": img.height,
                         "sha256": hashlib.sha256((folder / fname).read_bytes()).hexdigest(),
                         "dhash": dh, "access_date": ACCESS_DATE})
            taken += 1
            time.sleep(0.5)
        print(f"{stratum:14s} {src}: {taken}/{quota}")

cand = pd.DataFrame(rows)
cand.to_csv(OUT / "candidates.csv", index=False, encoding="utf-8")
print(cand.groupby(["stratum", "source"]).size())
print(cand.license.value_counts())
