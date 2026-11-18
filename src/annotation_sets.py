"""Наборы задач и пути артефактов ручной разметки."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("pilot", "repeat", "main")
SMS_SUBTYPES = {"smishing", "fraud", "prize", "premium", "promo"}


def stage_dir(base: Path, stage: str) -> Path:
    return base if stage == "pilot" else base / stage


def expected_ids(task: str, stage: str) -> set[str]:
    kind = "sms" if task == "sms" else "images"
    ls = ROOT / "labeling" / "label_studio"

    def read_ids(name: str) -> set[str]:
        path = ls / f"import_{kind}_{name}.csv"
        if not path.is_file():
            raise ValueError(f"Нет списка задач: {path.name}")
        ids = pd.read_csv(path, dtype=str).id
        if ids.empty or ids.isna().any() or ids.duplicated().any():
            raise ValueError(f"Пустые или повторяющиеся ID: {path.name}")
        return set(ids)

    if stage == "repeat" and task != "cars":
        raise ValueError("Повторный пилот предусмотрен только для Cars")
    if task == "cars" and stage in ("repeat", "main"):
        repeat = read_ids("repeat")
        main = read_ids("main")
        if len(repeat) != 10 or not repeat <= main or repeat & read_ids("pilot"):
            raise ValueError("Повторный пилот: ровно 10 ID из import_images_main.csv вне первого пилота")
        remaining = read_ids("main_remaining")
        if remaining != main - repeat:
            raise ValueError("import_images_main_remaining.csv должен содержать ровно оставшиеся ID")
        return repeat if stage == "repeat" else remaining
    return read_ids(stage)
