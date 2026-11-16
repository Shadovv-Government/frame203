# frame203

Курсовая работа «Сравнительный анализ влияния ручного и искусственного обогащения данных на качество и устойчивость обучения моделей машинного обучения».

Исполнители: Якунченков К. А., Графов Г. П.

Журнал: <https://docs.google.com/spreadsheets/d/1wn3qrEvD4HWkhzXY1EhojdtxA9DBfmoZbLYiY-jBHgU/edit?usp=sharing>

## Наборы данных

| Набор | Источник | Лицензия | Расположение |
|---|---|---|---|
| UCI SMS Spam Collection | DOI 10.24432/C5CC84 | CC BY 4.0 | `data/raw/uci/` (не включается в репозиторий) |
| Open Images V7, validation, класс Car | <https://storage.googleapis.com/openimages/web/download_v7.html> | аннотации CC BY 4.0, изображения CC BY 2.0 | `data/raw/oi/` (не включается в репозиторий) |
| NUS SMS Corpus | DOI 10.25540/WVM0-4RNX | CC BY 4.0 | `data/interim/sms_enrichment/` |
| SMS Phishing Dataset (Mishra, Soni) | DOI 10.17632/f45bkkt8pr.1 | CC BY 4.0 | `data/interim/sms_enrichment/` |
| Wikimedia Commons | ссылка на каждый файл в манифесте | CC0, Public domain, CC BY, CC BY-SA | `data/processed/images_new_v1/` |

## Структура репозитория

```
data/interim/sms_enrichment/   манифест 150 SMS, отчёты дедупликации
data/interim/car_enrichment/   кандидаты и манифест изображений
data/processed/images_new_v1/  54 изображения ручного пополнения
data/annotations/              итоговая разметка (build_gold.py)
docs/                          codebook разметки
labeling/label_studio/         конфигурации и задачи Label Studio
labeling/exports/              выгрузки Label Studio: pilot/, main/
labeling/resolution/           решения сверки (agreement.py)
labeling/screenshots/          снимки интерфейса разметки
notebooks/                     01, 04 — EDA исходных наборов; 02, 05 — ручное пополнение; 03, 06 — обучение
reports/tables/, reports/figures/, reports/agreement/
src/                           скрипты
```

Выгрузки именуются `<A|B>_<sms|cars>.json`: A — Якунченков К. А., B — Графов Г. П.

## Окружение

Python 3.12.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Label Studio устанавливается в отдельное окружение: `pip install label-studio`.

## Воспроизведение

| Этап | Команда | Результат |
|---|---|---|
| Пополнение SMS | `python src/build_sms_enrichment.py` | `data/interim/sms_enrichment/` |
| Поиск изображений | `python src/build_car_enrichment.py`, затем `python src/build_car_enrichment.py 2` | `data/interim/car_enrichment/candidates.csv` |
| Контактные листы | `python src/contact_sheet.py <начало> <конец> <файл.jpg>` | лист миниатюр кандидатов |
| Утверждение набора, задачи разметки | `python src/finalize_enrichment.py` | манифесты, `data/processed/images_new_v1/`, `labeling/label_studio/import_*.csv` |
| Проверка выгрузки | `python src/check_exports.py <sms\|cars> <выгрузка.json> --set <pilot\|main>` | отчёт об ошибках |
| Согласие аннотаторов | `python src/agreement.py <sms\|cars> --a <A.json> --b <B.json>` | `reports/agreement/`, `labeling/resolution/` |
| Итоговая разметка | `python src/build_gold.py <sms\|cars> --tag <pilot\|main>` | `data/annotations/` |

Исходные наборы размещаются в `data/raw/` в соответствии с путями в ноутбуках 01 и 04. Результат поиска изображений зависит от даты запроса; набор, использованный в работе, зафиксирован в `data/interim/car_enrichment/candidates.csv`. Seed — 42.

## Использование языковых моделей

При подготовке работы использовалась языковая модель Claude (Anthropic). Протокол взаимодействия приводится в отчёте.
