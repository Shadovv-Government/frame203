# frame203

Курсовая работа «Сравнительный анализ влияния ручного и искусственного обогащения данных на качество и устойчивость обучения моделей машинного обучения».

Студенты: Якунченков К. А., Графов Г. П.

Журнал: <https://docs.google.com/spreadsheets/d/1wn3qrEvD4HWkhzXY1EhojdtxA9DBfmoZbLYiY-jBHgU/edit?usp=sharing>

## Наборы данных

[Материалы промежуточной сдачи](https://drive.google.com/drive/folders/1Jqkw4sQtOR8rJNyGxexAo2-O_xVQ8aFP) · [Архив данных и разметки](https://drive.google.com/file/d/1hob2zzeKdkTNSeZA5WCQ0TzLKObkU0lu/view?usp=drivesdk)

Распакуйте архив в корень репозитория. Данные, задачи Label Studio, независимые выгрузки, таблицы сверки, gold и пообъектные отчёты хранятся на Google Диске. В Git остаются код, конфигурации, ноутбуки, сводные метрики и примеры интерфейса.


| Набор | Источник | Лицензия | Расположение |
|---|---|---|---|
| UCI SMS Spam Collection | DOI 10.24432/C5CC84 | CC BY 4.0 | `data/raw/sms/` |
| Open Images V7, validation, класс Car | <https://storage.googleapis.com/openimages/web/download_v7.html> | аннотации CC BY 4.0, изображения CC BY 2.0 | `data/raw/openimages/` |
| NUS SMS Corpus | DOI 10.25540/WVM0-4RNX | CC BY 4.0 | `data/interim/sms_enrichment/` |
| SMS Phishing Dataset (Mishra, Soni) | DOI 10.17632/f45bkkt8pr.1 | CC BY 4.0 | `data/interim/sms_enrichment/` |
| Wikimedia Commons | ссылка на каждый файл в манифесте | CC0, Public domain, CC BY, CC BY-SA | `data/processed/images_new_v1/` |

## Структура проекта после распаковки

```
data/interim/sms_enrichment/   манифест 150 SMS, отчёты дедупликации
data/interim/car_enrichment/   кандидаты и манифест изображений
data/processed/images_new_v1/  54 изображения ручного пополнения
data/annotations/              согласованная разметка по этапам
docs/                          codebook разметки
labeling/label_studio/         конфигурации и задачи Label Studio
labeling/exports/              независимые выгрузки: pilot/, repeat/, main/
labeling/resolution/           решения сверки; repeat/ и main/ для следующих этапов
labeling/screenshots/          снимки интерфейса разметки
notebooks/                     01, 04 — EDA; 02, 05 — состав пополнения; 07 — анализ разметки
                               03, 06 — заготовки для обучения
reports/tables/, reports/figures/  результаты EDA
reports/agreement/             результаты согласия по этапам
frame203-review/               локальное приложение сверки
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
| Проверка выгрузки | `python src/check_exports.py <sms\|cars> <выгрузка.json> --set <pilot\|repeat\|main>` | отчёт об ошибках |
| Согласие аннотаторов | `python src/agreement.py <sms\|cars> --a <A.json> --b <B.json> --set <pilot\|repeat\|main>` | `reports/agreement/`, `labeling/resolution/` |
| Итоговая разметка | `python src/build_gold.py <sms\|cars> --tag <pilot\|repeat\|main>` | `data/annotations/` |

Архив содержит исходный UCI и таблицы Open Images для ноутбуков 01 и 04. Для повторного запуска скриптов сбора см. `DATA_README.txt` в архиве. Результат поиска изображений зависит от даты запроса; набор, использованный в работе, зафиксирован в `data/interim/car_enrichment/candidates.csv`. Seed — 42.

## Этапы ручной разметки

| Набор | `pilot` | `repeat` | `main` |
|---|---|---|---|
| SMS | 60 сообщений, пороги выполнены | — | 90 сообщений |
| Cars | 30 изображений, пороги не выполнены | 10 новых для обоих аннотаторов | 14 оставшихся из `import_images_main.csv` после повторного пилота |

Исходный список 24 изображений — `import_images_main.csv`. Для повторного пилота используется `import_images_repeat.csv` (10 изображений, представлены все пять страт; четыре кадра с плотным трафиком). Для основной разметки используется `import_images_main_remaining.csv` (14 изображений). Выгрузки хранятся в каталогах этапов; отчёты и таблицы сверки `repeat` и `main` записываются в одноимённые подкаталоги. Независимые метрики рассчитываются до сверки.

В пилотном gold: 59 SMS (одна запись исключена по § 9.2 codebook v1.2), 115 рамок на 30 изображениях. Gold пилота Cars — результат сверки; он не подтверждает выполнение порогов согласия. При сборке обучающего набора исключаются рамки `depiction`.

## Использование языковых моделей

При подготовке работы использовалась языковая модель Claude (Anthropic). Протокол взаимодействия приводится в отчёте.
