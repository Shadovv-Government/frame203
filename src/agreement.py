"""Согласие двух аннотаторов по выгрузкам Label Studio (Export -> JSON) — codebook v1.2, раздел 9.

Текст:       python src/agreement.py sms  --a A.json --b B.json
Изображения: python src/agreement.py cars --a A.json --b B.json

Результаты: reports/agreement/<задача>_items.csv (по объектам), <задача>_metrics.csv (сводка),
<задача>_disagreements.csv (что разбирать на сверке).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import cohen_kappa_score

from annotation_sets import ROOT, STAGES, expected_ids, stage_dir
OUT = ROOT / "reports" / "agreement"
STAGE = "pilot"
SEED = 42
ATTRS = ["occluded", "truncated", "group_of", "depiction", "inside"]
IOU_MATCH = 0.5


# ---------------- общие функции ----------------
def load_tasks(path: Path) -> list[dict]:
    tasks = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for t in tasks:
        anns = [a for a in t.get("annotations", []) if not a.get("was_cancelled")]
        if not anns:
            continue
        a = max(anns, key=lambda a: a.get("updated_at") or a.get("created_at") or "")  # последняя редакция
        out.append({"id": t["data"]["id"], "data": t["data"], "result": a.get("result", []),
                    "lead_time": float(a.get("lead_time") or np.nan)})
    return out


def validate_pair(task: str, stage: str, a_path: Path, b_path: Path) -> None:
    if a_path.resolve() == b_path.resolve() or a_path.read_bytes() == b_path.read_bytes():
        raise ValueError("Для A и B нужны две разные независимые выгрузки")
    expected = expected_ids(task, stage)
    field = "text" if task == "sms" else "image"
    payloads = []
    for path in (a_path, b_path):
        tasks = load_tasks(path)
        counts = Counter(t["id"] for t in tasks)
        if set(counts) != expected or any(n != 1 for n in counts.values()):
            raise ValueError(f"{path.name}: набор ID не соответствует {stage}; запустите check_exports.py")
        payloads.append({t["id"]: t["data"][field] for t in tasks})
    if payloads[0] != payloads[1]:
        raise ValueError("У A и B различаются тексты или ссылки на изображения для одинаковых ID")


def choice(result: list[dict], name: str) -> str:
    for r in result:
        if r.get("from_name") == name and r.get("type") == "choices":
            return r["value"]["choices"][0]
    return ""


def text_field(result: list[dict], name: str) -> str:
    for r in result:
        if r.get("from_name") == name and r.get("type") == "textarea":
            return " ".join(r["value"].get("text", []))
    return ""


def kappa_ci(a, b, n_boot: int = 2000) -> tuple[float, float, float]:
    a, b = np.asarray(a), np.asarray(b)
    k = cohen_kappa_score(a, b)
    rng = np.random.default_rng(SEED)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, len(a), len(a))
        if len(set(a[i]) | set(b[i])) > 1:
            boots.append(cohen_kappa_score(a[i], b[i]))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return k, lo, hi


def krippendorff_alpha_nominal(a, b) -> float:
    """α Криппендорфа для двух аннотаторов без пропусков, номинальная шкала."""
    cats = sorted(set(a) | set(b))
    idx = {c: i for i, c in enumerate(cats)}
    o = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        o[idx[x], idx[y]] += 1
        o[idx[y], idx[x]] += 1
    n_c = o.sum(axis=1)
    n = n_c.sum()
    d_o = (n - np.trace(o)) / n
    d_e = (n * n - (n_c ** 2).sum()) / (n * (n - 1))
    return 1 - d_o / d_e if d_e else 1.0


def save(name: str, items: pd.DataFrame, metrics: dict, disagreements: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items.to_csv(OUT / f"{name}_items.csv", index=False, encoding="utf-8")
    pd.Series(metrics, name="значение").to_csv(OUT / f"{name}_metrics.csv", encoding="utf-8")
    disagreements.to_csv(OUT / f"{name}_disagreements.csv", index=False, encoding="utf-8")
    print(pd.Series(metrics).to_string())
    print(f"\nфайлы: {OUT}/{name}_*.csv; расхождений к разбору: {len(disagreements)}")


def write_template(name: str, res: pd.DataFrame) -> None:
    """labeling/resolution/<задача>_resolution.csv — не перезаписывается, если сверка уже начата."""
    path = stage_dir(ROOT / "labeling" / "resolution", STAGE) / f"{name}_resolution.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"шаблон сверки уже есть, не перезаписан: {path}")
        return
    res.to_csv(path, index=False, encoding="utf-8-sig")       # utf-8-sig — чтобы Excel открыл кириллицу
    print(f"шаблон сверки: {path} — заполнить на сверке, затем python src/build_gold.py {name} --tag {STAGE}")


# ---------------- текст ----------------
def sms(a_path: Path, b_path: Path) -> None:
    def frame(path, tag):
        rows = [{"id": t["id"], f"label_{tag}": choice(t["result"], "label"),
                 f"subtype_{tag}": choice(t["result"], "subtype"),
                 f"uncertain_{tag}": int(choice(t["result"], "uncertain") == "uncertain"),
                 f"comment_{tag}": text_field(t["result"], "comment"),
                 f"time_{tag}": t["lead_time"]} for t in load_tasks(path)]
        return pd.DataFrame(rows)

    d = frame(a_path, "A").merge(frame(b_path, "B"), on="id", how="inner")
    d = d[(d.label_A != "") & (d.label_B != "")]
    manifest = pd.read_csv(ROOT / "data/interim/sms_enrichment/sms_enrichment_manifest.csv")
    d = d.merge(manifest[["id", "text", "label_src", "label_raw", "stratum", "source"]], on="id", how="left")

    k, lo, hi = kappa_ci(d.label_A, d.label_B)
    both_spam = d[(d.label_A == "spam") & (d.label_B == "spam")]
    agree = d.label_A == d.label_B
    alpha = krippendorff_alpha_nominal(d.label_A, d.label_B)
    subtype_pa = (both_spam.subtype_A == both_spam.subtype_B).mean()
    m = {
        "объектов, размеченных обоими": len(d),
        "Percentage Agreement (метка)": round(agree.mean(), 4),
        "Cohen's kappa (метка)": round(k, 4),
        "kappa, 95 % ДИ (бутстрэп)": f"{lo:.3f}–{hi:.3f}",
        "Krippendorff alpha (метка)": round(alpha, 4),
        "PA подтипа (оба spam)": round(subtype_pa, 4) if len(both_spam) else "—",
        "доля uncertain, A / B": f"{d.uncertain_A.mean():.3f} / {d.uncertain_B.mean():.3f}",
        "медиана времени, с (A / B)": f"{d.time_A.median():.1f} / {d.time_B.median():.1f}",
        "суммарное время, мин (A / B)": f"{d.time_A.sum() / 60:.1f} / {d.time_B.sum() / 60:.1f}",
    }
    gold = d[agree]
    m["совпадение с меткой источника (где A = B)"] = round((gold.label_A == gold.label_src).mean(), 4)
    ok = (agree.mean() >= 0.90 and k >= 0.75 and alpha >= 0.80 and subtype_pa >= 0.80
          and max(d.uncertain_A.mean(), d.uncertain_B.mean()) <= 0.10)
    m["пороги codebook v1.2 (таблица 13)"] = "выполнены" if ok else "НЕ выполнены"
    dis = d[~agree | (d.subtype_A != d.subtype_B) | (d.uncertain_A + d.uncertain_B > 0)]
    save("sms", d, m, dis)
    # шаблон сверки: gold заполнен там, где метка и подтип совпали; остальное решается на сверке
    res = dis[["id", "text", "label_A", "label_B", "subtype_A", "subtype_B", "comment_A", "comment_B"]].copy()
    same = (res.label_A == res.label_B) & (res.subtype_A == res.subtype_B)
    res["gold_label"] = np.where(same, res.label_A, "")
    res["gold_subtype"] = np.where(same, res.subtype_A, "")
    res["exclude"] = ""
    res["note"] = ""
    res["reviewed"] = ""
    write_template("sms", res)


# ---------------- изображения ----------------
def boxes(task: dict) -> list[dict]:
    regions = {}
    for r in task["result"]:
        if r.get("type") == "rectanglelabels":
            v = r["value"]
            regions[r["id"]] = {"x1": v["x"] / 100, "y1": v["y"] / 100, "x2": (v["x"] + v["width"]) / 100,
                                "y2": (v["y"] + v["height"]) / 100, "attrs": set()}
    for r in task["result"]:
        if r.get("from_name") == "attrs" and r.get("id") in regions:
            regions[r["id"]]["attrs"] = set(r["value"].get("choices", []))
    return list(regions.values())


def iou(p: dict, q: dict) -> float:
    ix = max(0.0, min(p["x2"], q["x2"]) - max(p["x1"], q["x1"]))
    iy = max(0.0, min(p["y2"], q["y2"]) - max(p["y1"], q["y1"]))
    inter = ix * iy
    union = (p["x2"] - p["x1"]) * (p["y2"] - p["y1"]) + (q["x2"] - q["x1"]) * (q["y2"] - q["y1"]) - inter
    return inter / union if union > 0 else 0.0


def cars(a_path: Path, b_path: Path) -> None:
    ta = {t["id"]: t for t in load_tasks(a_path)}
    tb = {t["id"]: t for t in load_tasks(b_path)}
    pairs, per_image = [], []
    for img_id in sorted(set(ta) & set(tb)):
        ba, bb = boxes(ta[img_id]), boxes(tb[img_id])
        matched = []
        if ba and bb:
            m = np.array([[iou(p, q) for q in bb] for p in ba])
            valid = m >= IOU_MATCH
            # Сначала максимум допустимых пар, затем максимальная сумма их IoU.
            score = np.where(valid, min(m.shape) + 1 + m, 0)
            r_idx, c_idx = linear_sum_assignment(score, maximize=True)
            matched = [(i, j, m[i, j]) for i, j in zip(r_idx, c_idx) if valid[i, j]]
        mi = {i for i, _, _ in matched}
        mj = {j for _, j, _ in matched}
        for i, j, v in matched:
            pairs.append({"id": img_id, "status": "matched", "iou": v,
                          **{f"{a}_A": int(a in ba[i]["attrs"]) for a in ATTRS},
                          **{f"{a}_B": int(a in bb[j]["attrs"]) for a in ATTRS},
                          **{f"{k}_A": ba[i][k] for k in ("x1", "y1", "x2", "y2")},
                          **{f"{k}_B": bb[j][k] for k in ("x1", "y1", "x2", "y2")}})
        for i, p in enumerate(ba):
            if i not in mi:
                pairs.append({"id": img_id, "status": "only_A", **{f"{k}_A": p[k] for k in ("x1", "y1", "x2", "y2")},
                              **{f"{a}_A": int(a in p["attrs"]) for a in ATTRS}})
        for j, q in enumerate(bb):
            if j not in mj:
                pairs.append({"id": img_id, "status": "only_B", **{f"{k}_B": q[k] for k in ("x1", "y1", "x2", "y2")},
                              **{f"{a}_B": int(a in q["attrs"]) for a in ATTRS}})
        per_image.append({"id": img_id, "boxes_A": len(ba), "boxes_B": len(bb), "matched": len(matched),
                          "time_A": ta[img_id]["lead_time"], "time_B": tb[img_id]["lead_time"],
                          "uncertain_A": int(choice(ta[img_id]["result"], "uncertain") == "uncertain"),
                          "uncertain_B": int(choice(tb[img_id]["result"], "uncertain") == "uncertain")})
    attrs_and_coords = [f"{a}_{side}" for side in ("A", "B") for a in ATTRS]
    attrs_and_coords += [f"{k}_{side}" for side in ("A", "B") for k in ("x1", "y1", "x2", "y2")]
    p = pd.DataFrame(pairs, columns=["id", "status", "iou", *attrs_and_coords])
    im = pd.DataFrame(per_image)
    for col in attrs_and_coords:
        p[col] = pd.to_numeric(p[col])
    mt = p[p.status == "matched"]
    n_a, n_b, n_m = im.boxes_A.sum(), im.boxes_B.sum(), im.matched.sum()
    met = {
        "изображений, размеченных обоими": len(im),
        "рамок A / B": f"{n_a} / {n_b}",
        "сопоставлено пар (IoU ≥ 0,5)": int(n_m),
        "F1 согласия по объектам = 2·m / (nA + nB)": round(2 * n_m / (n_a + n_b), 4) if n_a + n_b else "—",
        "медианный IoU сопоставленных": round(mt.iou.median(), 4) if len(mt) else "—",
        "средний IoU сопоставленных": round(mt.iou.mean(), 4) if len(mt) else "—",
        "доля пар с IoU ≥ 0,8": round((mt.iou >= 0.8).mean(), 4) if len(mt) else "—",
        "расхождение по числу объектов, %": round(abs(n_a - n_b) / ((n_a + n_b) / 2) * 100, 2) if n_a + n_b else "—",
        "изображений с разным числом рамок": int((im.boxes_A != im.boxes_B).sum()),
        "медиана времени на изображение, с (A / B)": f"{im.time_A.median():.1f} / {im.time_B.median():.1f}",
        "время на рамку, с (A / B)": f"{im.time_A.sum() / max(n_a, 1):.1f} / {im.time_B.sum() / max(n_b, 1):.1f}",
        "доля uncertain, A / B": f"{im.uncertain_A.mean():.3f} / {im.uncertain_B.mean():.3f}",
    }
    kappas = {}
    for a in ATTRS:
        if len(mt) and (mt[f"{a}_A"].nunique() > 1 or mt[f"{a}_B"].nunique() > 1):
            kappas[a] = cohen_kappa_score(mt[f"{a}_A"], mt[f"{a}_B"])
            met[f"атрибут {a}: PA / kappa"] = f"{(mt[f'{a}_A'] == mt[f'{a}_B']).mean():.3f} / {kappas[a]:.3f}"
        elif len(mt):
            met[f"атрибут {a}: PA / kappa"] = f"{(mt[f'{a}_A'] == mt[f'{a}_B']).mean():.3f} / не определена"
    ok = (len(mt) > 0 and 2 * n_m / (n_a + n_b) >= 0.90 and mt.iou.median() >= 0.80
          and abs(n_a - n_b) / ((n_a + n_b) / 2) <= 0.05
          and all(kappas.get(a, np.nan) >= 0.60 for a in ("occluded", "truncated"))
          and max(im.uncertain_A.mean(), im.uncertain_B.mean()) <= 0.10)
    met["пороги codebook v1.2 (таблица 13)"] = "выполнены" if ok else "НЕ выполнены"
    p.insert(0, "pair_id", [f"{i}#{k}" for k, i in enumerate(p.id)])
    items = p.merge(im, on="id", how="left")
    attrs_differ = (items[[f"{a}_A" for a in ATTRS]].to_numpy()
                    != items[[f"{a}_B" for a in ATTRS]].to_numpy()).any(axis=1)
    dis = items[(items.status != "matched") | (items.iou < 0.8) | attrs_differ
                | (items.uncertain_A == 1) | (items.uncertain_B == 1)]
    save("cars", items, met, dis[p.columns])
    # шаблон сверки: keep=1 — рамка остаётся в gold, keep=0 — удаляется; для пар с низким IoU
    # можно указать, чью рамку взять (use=A|B), иначе координаты усредняются
    res = dis[["pair_id", "id", "status", "iou"]].copy()
    res["keep"] = np.where(res.status == "matched", "1", "")
    res["use"] = ""
    res["note"] = ""
    res["reviewed"] = ""
    write_template("cars", res)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["sms", "cars"])
    ap.add_argument("--a", required=True, type=Path, help="выгрузка Label Studio аннотатора A")
    ap.add_argument("--b", required=True, type=Path, help="выгрузка Label Studio аннотатора B")
    ap.add_argument("--set", choices=STAGES, default="pilot")
    args = ap.parse_args()
    STAGE = args.set
    OUT = stage_dir(OUT, STAGE)
    try:
        validate_pair(args.task, STAGE, args.a, args.b)
    except (ValueError, OSError, KeyError) as e:
        ap.error(str(e))
    sms(args.a, args.b) if args.task == "sms" else cars(args.a, args.b)
