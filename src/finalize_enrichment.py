"""Утверждение собранных данных после визуальной проверки и подготовка пилотной разметки.

* изображения: решение keep / reject по каждому кандидату (визуальная проверка контактных листов
  01.11.2026, src/contact_sheet.py), причина отказа, отметка пилота;
* текст: пилот 60 сообщений — по 12 из каждой страты, seed 42;
* файлы импорта Label Studio без меток источника (слепая разметка).
"""
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
IMG_DIR = ROOT / "data" / "interim" / "car_enrichment"
SMS_DIR = ROOT / "data" / "interim" / "sms_enrichment"
LS = ROOT / "labeling" / "label_studio"
LS.mkdir(parents=True, exist_ok=True)

# ---------------- изображения ----------------
REJECT = {  # номер кандидата -> причина
    **{n: "автомобили отсутствуют" for n in (2, 3, 10, 14, 35, 39, 40, 48, 52, 54, 55, 56, 62, 63, 64, 65,
                                             66, 78, 81, 82, 84, 86, 89, 90, 91, 93, 94, 97, 98)},
    **{n: "автомобили неразличимы (световые следы, < 10 пикселей, размытие)" for n in (1, 19, 20, 41, 43, 44, 45,
                                                                                      46, 59, 87, 92)},
    **{n: "историческая уличная сцена: автомобили единичны и неразличимы в толпе" for n in (15, 67)},
    30: "та же сцена и тот же автомобиль, что в кандидате 26 (один group_id)",
    83: "спутниковый снимок облачности",
}
PILOT_IMG = [4, 6, 8, 9, 12, 13, 17, 18, 21, 22, 23, 26, 27, 32, 33, 34, 36, 38, 49, 50, 53, 60, 61, 70, 71,
             73, 80, 85, 95, 96]
STRATUM_FIX = {24: "snow_winter", 37: "unusual_view"}   # фактическое содержание кадра важнее запроса

cand = pd.read_csv(IMG_DIR / "candidates.csv")
cand["n"] = cand.id.str[-4:].astype(int)
cand["keep"] = ~cand.n.isin(REJECT)
cand["reject_reason"] = cand.n.map(REJECT).fillna("")
cand["stratum"] = cand.n.map(STRATUM_FIX).fillna(cand.stratum)
cand["pilot"] = cand.n.isin(PILOT_IMG)
cand["license_family"] = cand.license.str.extract(r"(CC0|Public domain|CC BY-SA|CC BY)", expand=False)
cand["share_alike"] = cand.license.str.contains("SA")
assert cand.loc[cand.pilot, "keep"].all()

cols = ["id", "file_name", "file_path", "stratum", "keep", "reject_reason", "pilot", "source", "title",
        "landing_url", "download_url", "author", "license", "license_url", "license_family", "share_alike",
        "access_date", "saved_w", "saved_h", "sha256", "dhash", "query"]
cand[cols].to_csv(IMG_DIR / "car_enrichment_manifest.csv", index=False, encoding="utf-8")

final_dir = ROOT / "data" / "processed" / "images_new_v1"
final_dir.mkdir(parents=True, exist_ok=True)
for r in cand[cand.keep].itertuples():
    shutil.copy2(ROOT / r.file_path, final_dir / r.file_name)

def write_tasks(df: pd.DataFrame, name: str) -> None:
    """Файл импорта Label Studio (Upload Files -> List of tasks): только id и содержимое, без меток источника."""
    df.to_csv(LS / f"import_{name}.csv", index=False, encoding="utf-8", lineterminator="\n")


images = cand.assign(image=cand.download_url.str.split("?").str[0])      # прямая ссылка Wikimedia без параметров
write_tasks(images[cand.pilot][["id", "image"]], "images_pilot")
write_tasks(images[cand.keep & ~cand.pilot][["id", "image"]], "images_main")

# ---------------- текст ----------------
sms = pd.read_csv(SMS_DIR / "sms_enrichment_manifest.csv")
pilot_ids = (sms.groupby("stratum", group_keys=False)
             .apply(lambda g: g.sample(12, random_state=SEED))["id"])
sms["pilot"] = sms.id.isin(pilot_ids)
sms.to_csv(SMS_DIR / "sms_enrichment_manifest.csv", index=False, encoding="utf-8")

order = sms.sample(frac=1, random_state=SEED)       # один и тот же порядок у обоих аннотаторов
for name, part in (("pilot", order[order.pilot]), ("main", order[~order.pilot])):
    write_tasks(part[["id", "text"]], f"sms_{name}")

print("изображений: кандидатов", len(cand), "| принято", int(cand.keep.sum()), "| пилот", int(cand.pilot.sum()))
print(cand[cand.keep].groupby("stratum").size().to_string())
print(cand[cand.keep].license_family.value_counts().to_string())
print("SMS: пилот", int(sms.pilot.sum()), sms[sms.pilot].label_src.value_counts().to_dict())
