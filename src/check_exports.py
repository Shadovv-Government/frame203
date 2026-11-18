"""Проверка выгрузки Label Studio перед расчётом согласия (codebook v1.2, приложение Б).

Запуск:
  python src/check_exports.py sms  labeling/exports/pilot/A_sms.json  --set pilot
  python src/check_exports.py cars labeling/exports/pilot/A_cars.json --set pilot

Ошибка (ERROR) — выгрузку нужно исправить в Label Studio и выгрузить заново.
Предупреждение (WARN) — проверить глазами; может быть верным решением по codebook.
Код возврата 1, если есть хотя бы одна ошибка.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from annotation_sets import SMS_SUBTYPES, STAGES, expected_ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["sms", "cars"])
    ap.add_argument("export", type=Path)
    ap.add_argument("--set", choices=STAGES, default="pilot", help="какой набор задач размечался")
    a = ap.parse_args()

    errors, warns = [], []
    try:
        tasks = json.loads(a.export.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: файл не читается как JSON: {e}")
        return 1
    if not isinstance(tasks, list) or (tasks and "annotations" not in tasks[0]):
        print("ERROR: это не полная выгрузка Label Studio. Нужен Export -> JSON (не JSON-MIN, не CSV)")
        return 1

    try:
        expected = expected_ids(a.task, a.set)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    ids = [t.get("data", {}).get("id") for t in tasks]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    if dup:
        errors.append(f"задачи импортированы дважды: {dup[:5]} — удалите проект и импортируйте файл один раз")
    missing, extra = expected - set(ids), set(ids) - expected
    if extra:
        errors.append(f"{len(extra)} задач не из набора {a.set} (пример: {sorted(extra)[:3]}) — не тот файл импорта?")
    if missing:
        errors.append(f"{len(missing)} задач набора {a.set} нет в выгрузке (пример: {sorted(missing)[:3]})")

    annotators, times, n_done = set(), [], 0
    for t in tasks:
        tid = t["data"].get("id")
        anns = [x for x in t.get("annotations", []) if not x.get("was_cancelled")]
        if not anns:
            errors.append(f"{tid}: не размечено (нет Submit)")
            continue
        if len(anns) > 1:
            warns.append(f"{tid}: {len(anns)} аннотации — в расчёт идёт последняя; один проект = один аннотатор")
        ann = max(anns, key=lambda a: a.get("updated_at") or a.get("created_at") or "")
        n_done += 1
        cb = ann.get("completed_by")
        annotators.add(cb.get("id") if isinstance(cb, dict) else cb)
        if ann.get("lead_time"):
            times.append(float(ann["lead_time"]))
        else:
            warns.append(f"{tid}: нет lead_time (время не записалось)")
        res = ann.get("result", [])
        choice = {r["from_name"]: r["value"].get("choices", []) for r in res if r.get("type") == "choices"
                  and r.get("from_name") in ("label", "subtype", "uncertain")}
        comment = " ".join(" ".join(r["value"].get("text", [])) for r in res if r.get("type") == "textarea").strip()
        if "uncertain" in choice and not comment:
            errors.append(f"{tid}: стоит uncertain, но нет комментария (codebook, раздел 6)")
        if a.task == "sms":
            lab = (choice.get("label") or [""])[0]
            if lab not in ("ham", "spam"):
                errors.append(f"{tid}: нет метки ham/spam")
            if lab == "spam" and (choice.get("subtype") or [""])[0] not in SMS_SUBTYPES:
                errors.append(f"{tid}: spam без допустимого подтипа")
            if lab == "ham" and choice.get("subtype"):
                warns.append(f"{tid}: ham, но выбран подтип — подтип будет проигнорирован")
        else:
            boxes = [r for r in res if r.get("type") == "rectanglelabels"]
            if not boxes:
                warns.append(f"{tid}: ни одной рамки — верно, только если в кадре нет Car (например, одни такси)")
            for b in boxes:
                v = b["value"]
                if v.get("rectanglelabels") != ["Car"]:
                    errors.append(f"{tid}: рамка должна иметь единственную метку Car")
                w, h = b.get("original_width"), b.get("original_height")
                if w and h:
                    side = min(v.get("width", 0) * w, v.get("height", 0) * h) / 100
                    if side < 10:
                        target = warns if a.set == "pilot" else errors
                        target.append(f"{tid}: меньшая сторона рамки {side:.1f} px (< 10 px, codebook § 8.1)")
                else:
                    warns.append(f"{tid}: нет размера изображения для проверки порога в пикселях")
                if v.get("width", 0) <= 0.2 or v.get("height", 0) <= 0.2:
                    errors.append(f"{tid}: рамка нулевого размера (случайный клик) — удалите её")
                if v["x"] < -0.5 or v["y"] < -0.5 or v["x"] + v["width"] > 100.5 or v["y"] + v["height"] > 100.5:
                    warns.append(f"{tid}: рамка выходит за край кадра")
                if abs(v.get("rotation", 0)) > 0.5:
                    errors.append(f"{tid}: рамка повёрнута на {v['rotation']:.0f}° — рамки должны быть без поворота")

    if len(annotators) > 1:
        errors.append(f"в выгрузке несколько аннотаторов ({annotators}) — у каждого должен быть свой Label Studio")

    print(f"Файл: {a.export}")
    print(f"Задач: {len(tasks)} | размечено: {n_done} из {len(expected)} | аннотатор(ы): {annotators}")
    if times:
        s = pd.Series(times)
        print(f"Время на задачу, с: медиана {s.median():.1f}, сумма {s.sum() / 60:.1f} мин")
        if s.max() > 600:
            warns.append(f"есть задачи дольше 10 минут ({int((s > 600).sum())}) — вкладка была открыта без работы? "
                         "Это исказит трудоёмкость, отметьте в журнале")
    for w in warns:
        print("WARN :", w)
    for e in errors:
        print("ERROR:", e)
    print("ИТОГ:", "можно считать согласие" if not errors else f"исправить {len(errors)} ошибок")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
