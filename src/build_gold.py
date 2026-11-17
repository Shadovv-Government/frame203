"""Итоговая (gold) разметка после сверки — codebook v1.1, раздел 9, шаг 4.

Вход:  reports/agreement/<задача>_items.csv (от src/agreement.py)
       labeling/resolution/<задача>_resolution.csv (заполнен на сверке)
Выход: data/annotations/<задача>_gold_<tag>.csv

  python src/build_gold.py sms  --tag pilot
  python src/build_gold.py cars --tag pilot

Правила:
* SMS: gold берётся из согласия либо файла сверки; exclude=1 с причиной исключает сообщение.
* Рамки: сопоставленная пара — средние координаты (или рамка A / B, если указано use); пара или одиночная рамка
  с keep=0 удаляется; одиночная рамка попадает в gold только при keep=1. Атрибут при расхождении A и B
  ставится (1): пропустить перекрытие хуже, чем отметить лишнее; правило записать в отчёт.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from annotation_sets import ROOT, STAGES, SMS_SUBTYPES, stage_dir
ATTRS = ["occluded", "truncated", "group_of", "depiction", "inside"]


def read_resolution(name: str, tag: str, key: str, required: set[str]) -> pd.DataFrame:
    path = stage_dir(ROOT / "labeling" / "resolution", tag) / f"{name}_resolution.csv"
    if not path.exists():
        sys.exit(f"нет файла сверки {path}: сначала src/agreement.py, затем заполнить файл")
    res = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    if res[key].duplicated().any() or "" in set(res[key]):
        sys.exit(f"Повторяющиеся или пустые ID в {path}")
    res = res.set_index(key)
    pending = required - set(res.index)
    if pending:
        sys.exit(f"Нет решения для {len(pending)} строк: {sorted(pending)[:5]}")
    if "reviewed" in res:
        pending = [i for i in required if res.at[i, "reviewed"] not in ("1", "1.0", "true")]
        if pending:
            sys.exit(f"Не подтверждена сверка {len(pending)} строк: {sorted(pending)[:5]}")
    return res


def report_file(name: str, tag: str, suffix: str) -> Path:
    return stage_dir(ROOT / "reports" / "agreement", tag) / f"{name}_{suffix}.csv"


def sms(tag: str) -> pd.DataFrame:
    items = pd.read_csv(report_file("sms", tag, "items"), dtype=str).fillna("")
    need = set(pd.read_csv(report_file("sms", tag, "disagreements"), dtype=str).id)
    res = read_resolution("sms", tag, "id", need)
    if set(res.index) - set(items.id):
        sys.exit("В решениях SMS есть ID вне текущего набора")
    flags = res.get("exclude", pd.Series("", index=res.index))
    if not flags.isin(["", "0", "1"]).all():
        sys.exit("Поле exclude принимает 0 или 1")
    excluded = flags == "1"
    if (excluded & res.note.str.strip().eq("")).any():
        sys.exit("Исключённые SMS требуют причины в note")
    included = res[~excluded]
    bad = included[~included.gold_label.isin(["ham", "spam"])]
    if len(bad):
        sys.exit(f"не решено {len(bad)} расхождений (gold_label пуст): {list(bad.index[:5])}")
    bad = included[(included.gold_label == "spam") & ~included.gold_subtype.isin(SMS_SUBTYPES)]
    if len(bad):
        sys.exit(f"spam без gold_subtype: {list(bad.index[:5])}")
    rows = []
    for r in items.itertuples():
        if r.id in excluded.index and excluded.at[r.id]:
            continue
        if r.id in res.index:
            g = res.loc[r.id]
            same = r.label_A == r.label_B and r.subtype_A == r.subtype_B
            rows.append((r.id, g.gold_label, g.gold_subtype if g.gold_label == "spam" else "",
                         "agreed" if same and (g.gold_label, g.gold_subtype) == (r.label_A, r.subtype_A) else "resolved", g.note))
        else:
            rows.append((r.id, r.label_A, r.subtype_A if r.label_A == "spam" else "", "agreed", ""))
    gold = pd.DataFrame(rows, columns=["id", "label", "subtype", "resolution", "note"])
    meta = items[["id", "text", "label_src", "stratum", "source"]]
    return gold.merge(meta, on="id", how="left")


def cars(tag: str) -> pd.DataFrame:
    items = pd.read_csv(report_file("cars", tag, "items"))
    need = set(pd.read_csv(report_file("cars", tag, "disagreements"), dtype=str).pair_id)
    res = read_resolution("cars", tag, "pair_id", need)
    key = items.set_index("pair_id")
    if set(res.index) - set(key.index) or any(
        (row.id, row.status) != (key.at[i, "id"], key.at[i, "status"]) for i, row in res.iterrows()
    ):
        sys.exit("Решения Cars не относятся к текущему отчёту")
    undecided = [k for k in res.index if res.at[k, "keep"] not in ("0", "1")]
    if undecided:
        sys.exit(f"не решено {len(undecided)} рамок (keep пуст или недопустим): {undecided[:5]}")
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
    return pd.DataFrame(rows, columns=["image_id", "x_min", "y_min", "x_max", "y_max", *ATTRS, "resolution", "pair_id"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["sms", "cars"])
    ap.add_argument("--tag", choices=STAGES, default="pilot")
    a = ap.parse_args()
    gold = sms(a.tag) if a.task == "sms" else cars(a.tag)
    out = ROOT / "data" / "annotations" / f"{a.task}_gold_{a.tag}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    gold.to_csv(out, index=False, encoding="utf-8")
    print(f"{out}: {len(gold)} строк; решено на сверке: {(gold.resolution == 'resolved').sum()}")
