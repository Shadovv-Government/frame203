"""Итоговая (gold) разметка после сверки — codebook v1.1, раздел 9, шаг 4.

Вход:  reports/agreement/<задача>_items.csv (от src/agreement.py)
       labeling/resolution/<задача>_resolution.csv (заполнен на сверке)
Выход: data/annotations/<задача>_gold_<tag>.csv

  python src/build_gold.py sms  --tag pilot
  python src/build_gold.py cars --tag pilot

Правила:
* SMS: совпавшая у A и B метка — gold; расхождение — решение из файла сверки (пустое решение = ошибка).
* Рамки: сопоставленная пара — средние координаты (или рамка A / B, если указано use); пара или одиночная рамка
  с keep=0 удаляется; одиночная рамка попадает в gold только при keep=1. Атрибут при расхождении A и B
  ставится (1): пропустить перекрытие хуже, чем отметить лишнее; правило записать в отчёт.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ATTRS = ["occluded", "truncated", "group_of", "depiction", "inside"]


def read_resolution(name: str) -> pd.DataFrame:
    path = ROOT / "labeling" / "resolution" / f"{name}_resolution.csv"
    if not path.exists():
        sys.exit(f"нет файла сверки {path}: сначала src/agreement.py, затем заполнить файл")
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")


def sms(tag: str) -> pd.DataFrame:
    items = pd.read_csv(ROOT / "reports/agreement/sms_items.csv", dtype=str).fillna("")
    res = read_resolution("sms").set_index("id")
    bad = res[~res.gold_label.isin(["ham", "spam"])]
    if len(bad):
        sys.exit(f"не решено {len(bad)} расхождений (gold_label пуст): {list(bad.index[:5])}")
    bad = res[(res.gold_label == "spam") & (res.gold_subtype == "")]
    if len(bad):
        sys.exit(f"spam без gold_subtype: {list(bad.index[:5])}")
    rows = []
    for r in items.itertuples():
        if r.id in res.index:
            g = res.loc[r.id]
            same = r.label_A == r.label_B and r.subtype_A == r.subtype_B
            rows.append((r.id, g.gold_label, g.gold_subtype if g.gold_label == "spam" else "",
                         "agreed" if same else "resolved", g.note))
        else:
            rows.append((r.id, r.label_A, r.subtype_A if r.label_A == "spam" else "", "agreed", ""))
    gold = pd.DataFrame(rows, columns=["id", "label", "subtype", "resolution", "note"])
    meta = items[["id", "text", "label_src", "stratum", "source"]]
    return gold.merge(meta, on="id", how="left")


def cars(tag: str) -> pd.DataFrame:
    items = pd.read_csv(ROOT / "reports/agreement/cars_items.csv")
    res = read_resolution("cars").set_index("pair_id")
    need = items[items.status != "matched"].pair_id
    undecided = [k for k in need if k not in res.index or res.loc[k, "keep"] not in ("0", "1")]
    if undecided:
        sys.exit(f"не решено {len(undecided)} одиночных рамок (keep пуст): {undecided[:5]}")
    rows = []
    for r in items.to_dict("records"):
        dec = res.loc[r["pair_id"]] if r["pair_id"] in res.index else None
        if dec is not None and dec["keep"] == "0":
            continue
        if r["status"] == "matched":
            use = dec["use"] if dec is not None else ""
            if use in ("A", "B"):
                box = [r[f"{k}_{use}"] for k in ("x1", "y1", "x2", "y2")]
            else:
                box = [(r[f"{k}_A"] + r[f"{k}_B"]) / 2 for k in ("x1", "y1", "x2", "y2")]
            attrs = {a: int(max(r[f"{a}_A"], r[f"{a}_B"])) for a in ATTRS}
            how = "agreed" if dec is None else "resolved"
        else:
            s = "A" if r["status"] == "only_A" else "B"
            box = [r[f"{k}_{s}"] for k in ("x1", "y1", "x2", "y2")]
            attrs = {a: int(r.get(f"{a}_{s}", 0) or 0) for a in ATTRS}
            how = "resolved"
        rows.append({"image_id": r["id"], "x_min": round(box[0], 5), "y_min": round(box[1], 5),
                     "x_max": round(box[2], 5), "y_max": round(box[3], 5), **attrs, "resolution": how,
                     "pair_id": r["pair_id"]})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["sms", "cars"])
    ap.add_argument("--tag", default="pilot", help="pilot или main — попадает в имя файла")
    a = ap.parse_args()
    gold = sms(a.tag) if a.task == "sms" else cars(a.tag)
    out = ROOT / "data" / "annotations" / f"{a.task}_gold_{a.tag}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    gold.to_csv(out, index=False, encoding="utf-8")
    print(f"{out}: {len(gold)} строк; решено на сверке: {(gold.resolution == 'resolved').sum()}")
