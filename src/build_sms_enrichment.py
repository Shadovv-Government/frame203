"""Сбор реальных SMS для ручного обогащения UCI SMS Spam Collection.

Источники (CC BY 4.0): NUS SMS Corpus (ham), Mishra & Soni SMS Phishing Dataset (ham / spam / smishing).
Шаги: чтение -> нормализация -> дедупликация против UCI и между источниками (точная, шаблонная,
косинусная близость TF-IDF символьных 3-5-грамм >= 0.80) -> стратифицированная выборка с seed ->
обезличивание личных данных в ham -> манифест с источником, лицензией, датой обращения.

Запуск из корня репозитория:  python src/build_sms_enrichment.py
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "interim" / "sms_enrichment"
OUT.mkdir(parents=True, exist_ok=True)

SEED = 42
ACCESS_DATE = "2026-11-01"
NEAR_DUP_COS = 0.80          # порог косинусной близости для «почти дубля»
QUOTA = {                    # страта -> (класс, источник, число сообщений)
    "ham_personal_sg": ("ham", "NUS", 20),
    "ham_personal_other": ("ham", "NUS", 20),
    "ham_mishra": ("ham", "Mishra", 35),
    "spam_promo": ("spam", "Mishra", 35),
    "spam_smishing": ("spam", "Mishra", 40),
}
SOURCES = {
    "NUS": dict(
        url="https://scholarbank.nus.edu.sg/handle/10635/137343",
        file_url="https://github.com/kite1988/nus-sms-corpus/raw/master/smsCorpus_en_xml_2015.03.09_all.zip",
        license="CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
        author="Chen T., Kan M.-Y. (2013), DOI 10.25540/WVM0-4RNX",
    ),
    "Mishra": dict(
        url="https://data.mendeley.com/datasets/f45bkkt8pr/1",
        file_url="https://data.mendeley.com/public-files/datasets/f45bkkt8pr/files/edb361de-918d-469f-9106-e84823830665/file_downloaded",
        license="CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)",
        author="Mishra S., Soni D. (2022), DOI 10.17632/f45bkkt8pr.1",
    ),
}

URL_RE = re.compile(r"(https?://\S+|www\.\S+|\b[a-z0-9-]+\.(?:com|net|org|io|ly|co|uk|me|info|biz|xyz|do|gl)(?:/\S*)?)", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s\-()]{6,}\d)(?!\w)")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm_template(t: str) -> str:
    """Та же нормализация, что в 01_sms_eda (раздел 5): регистр, ссылки, телефоны, числа, пунктуация."""
    t = t.lower()
    t = URL_RE.sub(" <url> ", t)
    t = PHONE_RE.sub(" <phone> ", t)
    t = NUM_RE.sub(" <num> ", t)
    t = re.sub(r"[^a-z<>\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clean(t: str) -> str:
    t = t.replace("�", "'").replace("ï¿½", "'")
    return re.sub(r"\s+", " ", t).strip()


def anonymise(t: str) -> str:
    """Личные контакты в ham заменяются суррогатами того же типа (codebook, раздел 6)."""
    t = EMAIL_RE.sub("user@example.com", t)
    return PHONE_RE.sub("07700 900123", t)   # номер из диапазона Ofcom для вымышленных номеров


# ---------- исходный набор ----------
uci_path = RAW / "uci" / "SMSSpamCollection"
uci = pd.read_csv(uci_path, sep="\t", header=None, names=["label", "text"], quoting=3, dtype=str)

# ---------- NUS ----------
nus_path = RAW / "nus" / ACCESS_DATE / "smsCorpus_en_2015.03.09_all.xml"
rows = []
for m in ET.parse(nus_path).getroot().iter("message"):
    txt = m.findtext("text") or ""
    up = m.find("source/userProfile")
    rows.append({
        "source_id": "nus_" + m.get("id"),
        "text": clean(txt),
        "country": (up.findtext("country") if up is not None else "unknown") or "unknown",
        "user_id": (up.findtext("userID") if up is not None else "") or "",
        "collected": (m.find("collectionMethod").get("time") if m.find("collectionMethod") is not None else ""),
    })
nus = pd.DataFrame(rows)
nus["label_src"] = "ham"
nus["label_raw"] = "ham"          # корпус личной переписки, меток в источнике нет
nus["source"] = "NUS"

# ---------- Mishra & Soni ----------
mi_path = RAW / "mishra" / ACCESS_DATE / "Dataset_5971.csv"
mi = pd.read_csv(mi_path, encoding="utf-8", encoding_errors="replace")
mi = mi.rename(columns={"LABEL": "label_raw", "TEXT": "text"})
mi["text"] = mi["text"].astype(str).map(clean)
mi["label_raw"] = mi["label_raw"].str.lower()
mi["label_src"] = mi["label_raw"].map({"ham": "ham", "spam": "spam", "smishing": "spam"})
mi["source_id"] = "mishra_" + mi.index.astype(str)
mi["source"] = "Mishra"
mi["country"] = ""
mi["user_id"] = ""

cand = pd.concat([nus, mi], ignore_index=True)
cand = cand[cand.text.str.len() >= 15].copy()        # однословные реплики не дают информации
cand["norm"] = cand.text.map(norm_template)
uci["norm"] = uci.text.map(norm_template)

report = {"NUS, сообщений в корпусе": len(nus), "Mishra, сообщений в корпусе": len(mi)}

# 1) точное и шаблонное совпадение с UCI
uci_exact = set(uci.text.str.lower().str.strip())
uci_norm = set(uci.norm)
cand["dup_uci_exact"] = cand.text.str.lower().str.strip().isin(uci_exact)
cand["dup_uci_template"] = cand.norm.isin(uci_norm)

# 2) почти-дубли: косинус TF-IDF символьных n-грамм к ближайшему сообщению UCI
vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True)
X_uci = vec.fit_transform(uci.norm)
X_c = vec.transform(cand.norm)
nn = NearestNeighbors(n_neighbors=1, metric="cosine").fit(X_uci)
dist, _ = nn.kneighbors(X_c)
cand["max_cos_uci"] = 1 - dist[:, 0]
cand["dup_uci_near"] = cand.max_cos_uci >= NEAR_DUP_COS

# 3) дубли внутри кандидатов (между источниками)
cand["dup_internal"] = cand.duplicated("norm", keep="first")

ok = cand[~(cand.dup_uci_exact | cand.dup_uci_template | cand.dup_uci_near | cand.dup_internal)].copy()
for src in ("NUS", "Mishra"):
    c = cand[cand.source == src]
    report[f"{src}: точных совпадений с UCI"] = int(c.dup_uci_exact.sum())
    report[f"{src}: шаблонных совпадений с UCI"] = int((c.dup_uci_template & ~c.dup_uci_exact).sum())
    report[f"{src}: почти-дублей (cos >= {NEAR_DUP_COS})"] = int((c.dup_uci_near & ~c.dup_uci_template).sum())
    report[f"{src}: прошло фильтр"] = int((ok.source == src).sum())

# ---------- страты ----------
ok["stratum"] = None
nus_ok = ok.source == "NUS"
ok.loc[nus_ok & (ok.country.isin(["SG", "Singapore"])), "stratum"] = "ham_personal_sg"
ok.loc[nus_ok & ~(ok.country.isin(["SG", "Singapore", "unknown"])), "stratum"] = "ham_personal_other"
ok.loc[(ok.source == "Mishra") & (ok.label_src == "ham"), "stratum"] = "ham_mishra"
ok.loc[(ok.source == "Mishra") & (ok.label_raw == "spam"), "stratum"] = "spam_promo"
ok.loc[(ok.source == "Mishra") & (ok.label_raw == "smishing"), "stratum"] = "spam_smishing"

# NUS: не более 2 сообщений одного автора, чтобы выборка не повторяла одного человека.
# Внутри выборки: жадный отбор с запретом пар cos >= DIVERSITY_COS — иначе страта заполняется
# вариантами одного шаблона («Sorry, I'll call later..hv some work..» и т. п.).
DIVERSITY_COS = 0.60
picked, picked_vecs = [], []
for st, (lab, src, n) in QUOTA.items():
    pool = ok[ok.stratum == st].sample(frac=1, random_state=SEED)
    if src == "NUS":
        pool = pool.groupby("user_id", sort=False).head(2)
    take_idx = []
    for idx in pool.index:
        v = vec.transform([pool.at[idx, "norm"]])
        if any((v @ w.T).toarray()[0, 0] >= DIVERSITY_COS for w in picked_vecs):
            continue
        picked_vecs.append(v)
        take_idx.append(idx)
        if len(take_idx) == n:
            break
    take = pool.loc[take_idx]
    report[f"страта {st}: доступно / взято"] = f"{int((ok.stratum == st).sum())} / {len(take)}"
    picked.append(take)
sel = pd.concat(picked).sample(frac=1, random_state=SEED).reset_index(drop=True)

# ---------- обезличивание и манифест ----------
sel["text_original_hash"] = sel.text.map(lambda t: hashlib.sha256(t.encode()).hexdigest()[:16])
is_ham = sel.label_src == "ham"
before = sel.text.copy()
sel.loc[is_ham, "text"] = sel.loc[is_ham, "text"].map(anonymise)
sel["anonymised"] = sel.text != before

sel.insert(0, "id", [f"sms_new_{i:04d}" for i in range(1, len(sel) + 1)])
sel["url"] = sel.source.map(lambda s: SOURCES[s]["url"])
sel["license"] = sel.source.map(lambda s: SOURCES[s]["license"])
sel["author"] = sel.source.map(lambda s: SOURCES[s]["author"])
sel["access_date"] = ACCESS_DATE
sel["raw_file_sha256"] = sel.source.map({"NUS": sha256(nus_path), "Mishra": sha256(mi_path)})
cols = ["id", "text", "label_src", "label_raw", "stratum", "source", "source_id", "country",
        "url", "license", "author", "access_date", "raw_file_sha256", "max_cos_uci", "anonymised",
        "text_original_hash"]
sel[cols].round({"max_cos_uci": 3}).to_csv(OUT / "sms_enrichment_manifest.csv", index=False, encoding="utf-8")

cand_stats = cand.groupby("source")[["dup_uci_exact", "dup_uci_template", "dup_uci_near", "dup_internal"]].sum()
cand_stats.to_csv(OUT / "sms_dedup_report.csv", encoding="utf-8")
pd.Series(report).to_csv(OUT / "sms_enrichment_report.csv", header=["значение"], encoding="utf-8")
print(pd.Series(report).to_string())
print(sel.groupby(["label_src", "stratum"]).size())
