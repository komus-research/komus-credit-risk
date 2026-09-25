# Журнал решений

## Статус

Этот файл хранит важные продуктовые, исследовательские и архитектурные решения и отвечает на вопрос **почему проект устроен именно так**.

Актуальные правила находятся в `BUSINESS_RULES.md`, `PRODUCT_SPEC.md` и `ARCHITECTURE.md`. При расхождении журнал решений не имеет над ними приоритета.

---

## 2026-08-18

### D-001 — Основной репозиторий `komus-credit-risk`

Текущий рабочий repository: `komus-research/komus-credit-risk`; рабочая ветка: `main`; локальная папка: `D:\Projects\komus-work`.

Историческая ссылка на personal repository более не является source of truth. `AIUniverstorage/commus` является repository Института / integration point, но не ежедневным research source of truth.

Причина: исследование должно иметь собственную воспроизводимую историю кода и решений, независимую от Colab-файлов, прошлых чатов и интеграционных копий.

### D-002 — Основная среда VS Code + Git + GitHub + local venv + Jupyter

Новый этап ведётся локально в VS Code с Git/GitHub и Jupyter.

Colab остаётся дополнительной средой, но не source of truth текущего кода.

Причина: проект переходит от большого research notebook к модульному ML-приложению и будущему backend.

### D-003 — Historical baseline №06 замораживается

Notebook

`06_Сравнение_моделей_на_датасете_заказчика_v5_3_3_AI_анализ_одна_кнопка.ipynb`

фиксируется как historical baseline v1 с SHA-256:

`cd51d78c82f386b61d1380529b710e4c0d9eaf1c148b58523b2f2741dc0a1523`

Его результаты не переписываются задним числом после появления новых бизнес-ответов.

Причина: необходимо сохранить честную историю того, что реально было исследовано и защищено.

### D-004 — `Data_final.xlsb` не хранится в Git

Dataset идентифицируется SHA-256:

`fc742be66d238c529daba52ccc755f774f836b7d052ed062cdf0b345080e7930`

Сам файл в GitHub не помещается.

Причина: это клиентские данные и тяжёлый бинарный артефакт; воспроизводимость обеспечивается метаданными и локальным/разрешённым хранилищем.

### D-005 — `Q_B1_norm` и `Q_B2_norm` запрещены в финальной рабочей модели

`Q_B1_norm` = ИФР СПАРК.

`Q_B2_norm` = ИДО СПАРК.

Оба были доступны до дефолта, но заказчик запретил использовать их в финальной рабочей модели. Они остаются только reference/диагностическими признаками.

Следствие: старые кандидаты notebook №06, содержащие эти признаки, не считаются актуальными production-кандидатами.

### D-006 — Диагностический Gini ≈ 0.807 не объявляется новым baseline

Историческая абляция без `Q_B1_norm` и `Q_B2_norm` дала Gini ≈ 0.8070.

Это не считается новым рабочим baseline, потому что эксперимент был частью старой схемы и не переоптимизировал сравнение моделей на новом допустимом feature set.

Нужен отдельный контролируемый baseline-эксперимент.

### D-007 — Новый baseline начинается с CatBoost, XGBoost и LightGBM

После удаления обоих запрещённых индексов нельзя предполагать, что прежний лидер сохранится.

Первый новый experiment сравнивает CatBoost, XGBoost и LightGBM на одинаковом feature set/split/folds/seed.

На первом проходе не добавляются Optuna, новые признаки, class weights и threshold optimization.

Причина: один исследовательский вопрос должен проверяться одним контролируемым изменением.

### D-008 — Final test не участвует в выборе

Final test используется только для финальной проверки заранее зафиксированного решения.

Он не используется для выбора модели, признаков, гиперпараметров, weights, threshold или feature engineering.

Причина: иначе final test перестаёт быть независимой финальной проверкой.

### D-009 — CPU является first-class критерием

Для моделей измеряются CPU training/inference time и по мере готовности RAM/model size.

Ориентиры заказчика: обучение ≤ 8 часов, прогноз одной компании ≤ 2 минут.

Причина: заказчик прямо просит проработать CPU-режим, а отсутствие GPU не должно блокировать базовый продукт.

### D-010 — Explainability является first-class компонентом

Объяснимость проектируется вместе с model/evaluation contract, а не добавляется декоративно после завершения ML.

Для DS-моделей приоритет — global + local SHAP и понятные risk/protective factors.

Причина: интерпретируемость является одним из ключевых требований заказчика и будущей СПР.

### D-011 — SHAP/importance не трактуются как причинность

Explanation описывает вклад признака в поведение модели, а не причинный механизм дефолта.

Причина: feature importance, SHAP и permutation importance являются ассоциативными/модельными объяснениями.

### D-012 — LLM используется как Result Interpreter, а не predictor

LLM располагается после ML/evaluation/explainability и интерпретирует структурированные результаты.

LLM не принимает кредитное решение, не изменяет метрики и не заменяет SHAP.

Причина: удачный LLM-блок notebook №06 уже показал ценность именно как аналитический интерпретатор.

### D-013 — LLM-провайдер не связывается с ML-core

Будущий `ResultInterpreter` должен поддерживать заменяемые реализации: внешний provider или local model.

ML-core не зависит от OpenAI/Yandex/Qwen/Llama-specific API.

Причина: политика заказчика по внешнему LLM API и конкретной локальной модели ещё не утверждена.

### D-014 — Стоимость FN/FP является настраиваемой runtime business policy

`C_FN` и `C_FP` не являются гиперпараметрами модели и не зашиваются в код.

Frontend должен позволять:

1. ввести реальные стоимости FN и FP; или
2. задать только относительное соотношение `C_FN : C_FP`.

Причина: бизнес пока не утвердил точные цены ошибок, а threshold нужно уметь пересчитывать без retraining.

### D-015 — Исторический `5×FN + FP` остаётся только research example

Функция стоимости из notebook №06 не считается бизнес-правилом.

Причина: она не была согласована заказчиком.

### D-016 — Manual review capacity является отдельной настраиваемой policy

Будущий интерфейс должен позволять задавать:

- maximum review volume;
- period;
- minutes per company;
- при необходимости доступные человеко-часы.

Текущий ориентир заказчика — около 30 минут на один ИНН, но лимит компаний не фиксируется.

Причина: 100 000 клиентов при ручной проверке создают огромную операционную нагрузку; threshold должен оцениваться не только по Recall/Precision.

### D-017 — Business policy отделяется от model training

Probability model обучается отдельно. Threshold, cost ratio и manual review capacity применяются к вероятностям после обучения.

Следствие: один `ExperimentResult` можно анализировать под разными business scenarios без retraining.

### D-018 — Recall ≈ 69% не является проблемой, которую нужно исправлять любой ценой

Заказчик подтвердил, что Recall порядка 69% является рабочим уровнем.

Причина: более высокий Recall простым снижением threshold резко увеличивает FP; резерв качества заказчик хочет искать через новые факторы и подходы.

### D-019 — Random split stability не называется temporal stability

В `Data_final.xlsb` отсутствует достоверная row-level дата наблюдения.

Поэтому CV/OOF/bootstrap/seed stability не доказывают перенос качества на будущий период.

Причина: temporal holdout нельзя корректно восстановить из текущего файла.

### D-020 — Для будущего data pipeline базовая дата оценки — 1 июня следующего года

Заказчик указал 1 июня года, следующего за отчётным, как базовую дату формирования оценки; в будущем возможна поквартальная настройка.

Это правило относится к будущему воспроизводимому data pipeline и не создаёт отсутствующую дату в старом `Data_final` задним числом.

### D-021 — Model comparison важнее рабочего UI менеджера на первом этапе

Первый frontend — research trainer для сравнения моделей, признаков, параметров и business scenarios.

Операционная карточка контрагента/менеджера — последующее развитие.

Причина: заказчик подтвердил фокус на сравнении моделей.

### D-022 — Модульная архитектура с однонаправленными границами

Основное направление:

`notebooks → ML/data core → ExperimentRunner → backend → frontend`

Notebook, backend и frontend не содержат три копии training/evaluation logic.

Причина: проект должен масштабироваться без накопления несогласованного кода.

### D-023 — Stable logic выносится из notebook постепенно

Не переписываем notebook №06 в библиотеку целиком одним большим рефакторингом.

Сначала переносится повторяемая и проверенная логика, которая нужна новому experiment path.

Причина: минимизация риска сломать working baseline и сохранение понятного research narrative.

### D-024 — Не вводить инфраструктуру раньше необходимости

Production-БД, Docker, очереди, orchestration, MLflow/DVC и другие тяжёлые компоненты не добавляются только ради «правильной архитектуры».

Каждый новый инфраструктурный компонент требует текущей задачи и критериев проверки.

### D-025 — Артефакты эксперимента являются доказательством результата

Документация описывает смысл и решения, но фактический experiment должен сохранять machine-readable metadata:

- dataset hash;
- features;
- model/params;
- split/folds/seed;
- metrics;
- runtime;
- versions;
- artifact manifest/signature.

Причина: stale notebook output и человеческая память не являются достаточной воспроизводимостью.

### D-026 — Документация разделена по ответственности

- `PROJECT_CONTEXT.md` — current state и source of truth;
- `PRODUCT_SPEC.md` — поведение продукта;
- `BUSINESS_RULES.md` — требования заказчика;
- `ARCHITECTURE.md` — технические границы;
- `ROADMAP.md` — этапы и критерии завершения;
- `DECISIONS.md` — история решений и их причины.

Причина: один огромный документ быстро становится противоречивым и неудобным для обновления.

### D-027 — Рабочий код меняется малыми reviewable шагами

Обычный workflow разработки:

1. inspect current branch/HEAD/status/diff;
2. определить небольшой scope;
3. пользователь применяет предложенный patch/изменение в локальном VS Code либо явно поручает GitHub-edit;
4. проверить actual diff;
5. выполнить targeted tests/run;
6. только затем commit/push;
7. обновить docs, если изменилось решение или current state.

Причина: пользователь хочет понимать код и работать поэтапно, а unrelated work нельзя перетирать.

### D-028 — Ассистент не меняет GitHub-код без явного запроса

Прямые GitHub writes допустимы, когда пользователь явно просит создать/изменить файлы в repository, как при первоначальной документации.

В обычной разработке предпочтителен inspect → patch → local verification → commit flow.

Причина: сохранить контроль пользователя над working tree и обучение работе с Git.

### D-029 — Новые признаки исследуются гипотезами, а не массовой загрузкой

Одна гипотеза или компактный feature block проверяются отдельным контролируемым experiment.

Причина: заказчик ожидает новые факторы, но без provenance/leakage diagnosis массовое добавление признаков не даёт защищаемого вывода.

### D-030 — Отдельно подготовить список нестандартных внешних факторов

Заказчик прямо приветствует «безумные»/неочевидные идеи факторов и просит предложения с кратким обоснованием.

Это отдельный research deliverable; внедрять все факторы в текущую модель не требуется.

### D-031 — Современные модели выбираются по актуальному первичному research

Перед экспериментом с новым современным подходом проводится web research по официальным документациям/первичным публикациям.

Причина: табличный ML-ландшафт быстро меняется, а старый ТЗ содержит примеры, но не должен диктовать бессмысленный model zoo.

### D-032 — Требование хранения 3/5 лет учитывается как future capability

Заказчик указал около 3 лет для истории данных/перемоделирования и около 5 лет для истории прогнозов.

На текущем этапе это не является основанием немедленно вводить production database.

Причина: сначала необходимо стабилизировать experiment/data contracts, затем выбирать storage по реальной нагрузке и audit requirements.

### D-033 — Несогласованность «7 внешних событий / 6 перечисленных» сохраняется как open question

Не добавлять седьмое событие по догадке.

Причина: source materials перечисляют шесть внешних событий; точный бизнес-контракт должен подтвердить заказчик.

---

## 2026-08-19

### D-034 — Основной research/development runtime — Python 3.12.2

Для нового локального этапа выбран **Python 3.12.2**. Управление окружением и зависимостями выполняется через `uv`; на момент решения локально подтверждён `uv 0.11.6`.

Решение принято после отдельного обсуждения риска между буквальным соблюдением старого требования Python 3.10 и сохранением современного ML-стека.

Причина: historical baseline №06 уже использует современные версии библиотек, в том числе XGBoost и SHAP, которые для своих сохранённых версий требуют более нового Python, чем 3.10. Проект посвящён исследованию современных ML/AI-инструментов, поэтому основную research-среду не следует заранее ограничивать устаревающим dependency stack без доказанной необходимости.

Следствие: `.venv` нового этапа создаётся на Python 3.12.2. Точные версии зависимостей должны фиксироваться lock-файлом после формирования проектного dependency set.

### D-035 — Python 3.10 сохраняется как отдельный delivery compatibility gate

Исходное ТЗ содержит требование воспроизводимости на Python 3.10. Это требование **не отменяется и не объявляется невыполнимым заранее**.

Перед поставкой проводится отдельная инженерная проверка:

1. попытаться собрать совместимое окружение Python 3.10 с зафиксированными версиями библиотек;
2. запустить критический ML/backend path без изменения бизнес- и ML-логики;
3. зафиксировать результат теста;
4. если совместимость подтверждена — подготовить отдельный совместимый lock/container;
5. если совместимость не подтверждена — предоставить заказчику воспроизводимое техническое обоснование и согласовать Python 3.12.

Причина: это лучше, чем либо искусственно заморозить исследование на старых библиотеках, либо игнорировать требование заказчика до самого конца.

Код проекта по возможности не использует Python-3.12-only возможности без необходимости, чтобы не создавать собственных препятствий совместимости.

### D-036 — Docker является планируемым механизмом поставки, но не вводится сейчас

Docker должен использоваться на позднем этапе для воспроизводимой упаковки runtime, зависимостей и способа запуска, включая offline/deployment-сценарий для передачи заказчику.

Docker не добавляется на текущем этапе до стабилизации ML-core, dependency set и backend/runtime contracts.

Причина: контейнер должен фиксировать уже проверенную систему. Раннее добавление Docker сейчас создаст дополнительную инфраструктуру, но не решит текущий исследовательский вопрос.

Будущий Docker compatibility test должен учитывать выбранный primary runtime Python 3.12 и, при необходимости заказчика, отдельный Python 3.10 compatibility image.

### D-037 — Закрытые индексы СПАРК остаются reference, а не объясняющими признаками

`Q_B1/Q_B2` — готовые внешние индексы СПАРК с нераскрытой внутренней методикой. По информации заказчика, они были доступны до дефолта и сильно коррелированы между собой — ориентир около **0.83**.

Следствие: их нельзя автоматически объявлять temporal leakage, но их нельзя использовать в финальной рабочей модели. Сильная взаимная корреляция объясняет, почему удаление одного индекса может оставлять качество почти неизменным: второй удерживает похожий сигнал.

Причина: проект должен восстановить качество через прозрачные и защищаемые факторы, а не через чужую закрытую оценку риска.

### D-038 — Customer-reported Gini ≈ 0.92 без индексов — ориентир, не критерий приёмки

Заказчик сообщает, что его рабочая модель достигает порядка **0.92 Gini без `Q_B1/Q_B2`** за счёт проработанных прозрачных факторов.

Этот уровень не является нашим проверенным artifact и не используется как доказанный benchmark или обязательный acceptance threshold.

Следствие: новый baseline сначала честно измеряет фактический уровень после удаления обоих индексов. Historical ablation ≈ 0.807 остаётся ориентиром стартовой зоны, после чего качество улучшается контролируемыми feature/model experiments.

### D-039 — ПДЗ `15% → 10%` фиксируется как бизнес-цель, но не превращается в выдуманную cost function

Заказчик описал бизнес-цель как снижение просроченной дебиторской задолженности примерно с **15% до 10%**; денежный масштаб — сотни миллионов.

При этом подтверждённой функции, связывающей FN/FP/Recall/Gini/threshold с изменением ПДЗ, пока нет.

Следствие: цель ПДЗ сохраняется как business KPI/context. Исследователь не имеет права самостоятельно выводить из неё `C_FN`, `C_FP` или «оптимальный» threshold без отдельного бизнес-контракта.

### D-040 — Масштаб ручной проверки является самостоятельным аргументом автоматизации

Ориентир заказчика — около **30 минут на один ИНН**. Для 100 000 компаний один полный проход составляет примерно **50 000 человеко-часов**, а пересмотр нужен хотя бы примерно раз в квартал.

Следствие: future business policy должна учитывать review capacity/human-hours. При этом нельзя автоматически считать, что каждый FP обязательно превращается в ручную проверку, пока процесс не утверждён заказчиком.

Причина: модель нужна не только ради метрики, но и ради масштабируемой замены процесса, который невозможно регулярно выполнять вручную.

### D-041 — Пользовательская часть проекта ведётся на русском языке

Весь пользовательский интерфейс, подписи графиков и таблиц, сообщения, отчёты и исследовательский Markdown оформляются на русском языке.

Python backend может использовать стандартный английский technical naming для функций, классов, переменных, API и внутренних сущностей.

Комментарии и docstrings к функциям пишутся на русском языке.

Стандартные названия моделей, библиотек и технологий сохраняются без искусственного перевода.

Причина: система должна быть понятна русскоязычному пользователю и заказчику, не нарушая при этом нормальные инженерные соглашения внутреннего кода.

### D-042 — Stage 1 V2 принят как новый воспроизводимый baseline без закрытых индексов

После полного исключения `Q_B1_norm` и `Q_B2_norm` до модельного сравнения получен воспроизводимый OOF/CV baseline примерно **Gini 0.804**.

Результаты V2:

- XGBoost: Gini 0.8040;
- CatBoost: Gini 0.8038;
- LightGBM: Gini 0.8034.

Различия между моделями малы относительно межфолдового разброса. Поэтому Stage 1 не устанавливает абсолютного победителя среди трёх бустингов.

Final test не использовался для выбора модели. Optuna, веса классов, калибровка и подбор threshold также не использовались.

Следствие: все следующие улучшения сравниваются с этим baseline на контролируемом протоколе, а не с historical результатом около 0.92 или старой абляцией около 0.807.

### D-043 — Исследовательские файлы версионируются только через V1, V2, V3 и далее

При развитии одного исследовательского notebook или другого значимого рабочего артефакта версии именуются последовательно: `V1`, `V2`, `V3` и далее.

Названия вроде «исправленный», «новый», «финальный», «финальный 2» не используются как схема версионирования.

Причина: последовательные номера сохраняют историю развития исследования, позволяют видеть число итераций и уменьшают риск перепутать актуальные и предыдущие варианты.

### D-044 — Исследовательские summary-артефакты хранятся в Git

Для воспроизводимости проекта небольшие агрегированные summary-файлы экспериментов хранятся в Git.

В summary не должны попадать:
- исходные клиентские данные;
- идентификаторы организаций;
- построчные выгрузки;
- чувствительные производственные данные.

В Git хранятся:
- исследовательские notebooks;
- документация проекта;
- агрегированные результаты экспериментов;
- метаданные воспроизводимости.

Большие временные артефакты экспериментов остаются локальными или исключаются через `.gitignore`.

Причина: сохранить историю исследования и возможность проверить выводы без перегрузки репозитория большими файлами.

---

## 2026-08-24

### D-045 — Stage 5 V1 принят с классом `material_missing_signal`

Stage 5 V1 закрыт со статусом `completed_accepted`. В рамках зафиксированного OOF-протокола текущие 47 разрешённых признаков частично воспроизводят общий `Q_B2` signal, но не воспроизводят существенную часть сигнала, полезную именно для Stage 3 blind spot.

Повторный ML-run для formal closure не требуется: решение опирается на уже сохранённые notebook outputs и machine-readable артефакты. Final test не использовался.

Следствие уточнено решениями Stages 6–11: data research остаётся открытым, но model-only architecture search на неизменных 47 признаках прекращён до появления valid reopen condition.

---

## 2026-09-01

### D-046 — Остановить model-only search на текущих 47 признаках после Stage 11

Принято решение:

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`

Evidence chain:

- Stage 6 TabM standalone — inferior (OOF Gini **0.781310**);
- Stage 7 TabM stacking — `no_material_benefit`, GBDT_mean **0.806399**;
- Stage 8 FT-Transformer — `no_material_benefit`;
- Stage 9 rank complementarity — FT rescue **9/805** против **0/805** у GBDT_mean, ниже material threshold;
- Stage 10 oracle/residual reserve — **15/805**, Δ **+1.863 п.п.**, effective union capacity **37.446%**, `limited_residual_model_reserve`;
- Stage 11 RealMLP — Gini **0.793325** против **0.806399**, Δ **-0.013074**, проигрыш **3/3** folds, `inferior`.

Решение означает только то, что дальнейший model-only architecture search на текущем feature set имеет низкий ожидаемый information gain. Совокупность evidence сильнее поддерживает information/feature limitation, чем недостаток проверенных architectures.

Решение не означает завершение проекта, доказанный математический потолок Gini или невозможность будущей более сильной модели. Оно также не снимает ограничение random CV: temporal stability не доказана.

Следующий этап — Research Synthesis Stage 1–11 с итоговой таблицей, evidence/figures, FACT / INTERPRETATION / LIMITATION, закрытыми и blocked questions, reopen conditions и материалами для презентации/защиты.

Data research остаётся открытым: СПАРК-пилот, новые признаки, связи, динамика и другие валидные источники информации могут открыть model research повторно. Reopen conditions: новый валидный feature source; row-level temporal anchor; сильный независимый противоречащий результат; новый business operating point; либо новая научная гипотеза, реально меняющая решение. Новый model shortlist ради количества не создаётся.

### D-047 — Stage 12 V1 принят как Research Synthesis Stages 1–11

Stage 12 V1 имеет статус `completed_accepted`. Он завершает и принимает текущую
model-research chain Stages 1–12 на 47 разрешённых признаках без `Q_B1_norm` /
`Q_B2_norm`.

Synthesis подтверждает baseline без закрытых индексов, common blind spot **805** и
Stage 5 `material_missing_signal`. TabM, stacking, FT-Transformer, complementarity,
oracle/residual reserve и RealMLP не дали evidence, что ещё одна architecture на том
же feature contract решает основное ограничение.

Следствие: `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется; ожидаемый
information gain дальнейшего model-only architecture search на тех же 47 признаках
низок.

Это решение не означает завершение проекта, доказанный математический потолок Gini,
temporal stability или невозможность будущего улучшения. Data research остаётся
следующим приоритетом: новые валидные признаки, СПАРК-пилот, динамика, связи,
row-level temporal anchor при его появлении и presentation / defence evidence.

Reopen conditions сохраняются: новый валидный feature source; row-level temporal
anchor; сильный независимый противоречащий результат; новый business operating point;
либо новая научная гипотеза, реально меняющая решение.

---

## 2026-09-04

### D-048 — Stage 13 TabFM full OOF остановлен по compute cost

Locked technical pipeline Stage 13 V1 валидирован: runtime/dataset guards, exact checkpoint SHA, model load, real inference preflight и single-call/chunked equivalence passed. Однако full 3-fold OOF на текущей CPU-среде не запускается, поскольку наблюдаемая стоимость вычислений непропорциональна ожидаемому information gain.

Статус: `STOPPED_BY_COMPUTE_COST`.

Это не quality verdict TabFM: полного OOF нет, TabFM OOF metrics не заявляются, final test не использовался. `RUN_FULL_OOF=False` сохраняется.

### D-049 — Model research не переоткрывается как model zoo

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` остаётся базовым решением для обычного architecture search на неизменных 47 разрешённых признаках. Stage 13 не отменяет и не переписывает это решение.

Причина: technical feasibility одного locked TabFM path не является evidence quality gain и не создаёт основания для автоматического запуска близких TFM.

### D-050 — Разрешён один narrow reopen: TabPFN-3 large-context hypothesis

На тот момент был разрешён ровно один narrow controlled experiment: проверить, даёт ли pretrained large-context TabPFN-3 дополнительное OOF-качество относительно accepted `GBDT_mean` на тех же 47 разрешённых признаках KOMUS.

Причина: это была новая scientific hypothesis о large-context foundation-model mechanism, а не очередная architecture и не reopening model zoo. Stage 14 V1 был разрешён к отдельному Architect Experiment Lock до любой implementation.

### D-051 — TabPFN-3 Stage 14 отклонён до запуска по CPU constraint

Статус: `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`.

TabPFN-3 не продолжается как active Stage 14 и не запускается. Честный locked large-context experiment требовал GPU/H100, что несовместимо с hard CPU-only compute constraint основного KOMUS research path. GPU fallback не разрешён; subsampling или уменьшение context изменили бы hypothesis.

TabPFN-3 не запускался, полный OOF не выполнялся, quality остаётся `UNKNOWN`. Это не `inferior`, не `no_material_benefit` и не evidence quality относительно `GBDT_mean`; final test не использовался. Historical pre-run implementation artifacts — `notebooks/14_Сравнение_TabPFN3_с_GBDT_baseline_V1.ipynb` и `requirements-tabpfn3-v1.txt` — существовали, но experiment не был запущен; они не являются active Stage 14 implementation.

GPU-only experiment не может стать следующим основным Stage без отдельного нового решения пользователя.

### D-052 — Разрешён один narrow CPU-only reopen: xRFM V1

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется как базовое решение для ordinary model search. Разрешён только один narrow controlled reopen: Stage 14 V1 `xRFM CPU_ONLY_RESEARCH_EXPERIMENT`, Architect status `XRFM_V1_LOCKED` / `READY_FOR_TECHNICAL_COORDINATOR`.

Проверяется новая hypothesis family: iterative kernel / metric feature learning + supervised recursive localization на том же locked data/fold/comparator contract. Frozen implementation lock: `xrfm==0.4.5`; CPU `device='cpu'`; 8 threads; `split_method='linear'`; `n_trees=1`; `max_leaf_size=8192`; leaf RFM iterations=3; no HPO; smoke → full Fold-1 feasibility → compute gate; full OOF только после отдельного manual review; ceiling 12 CPU wall-clock hours. `STOPPED_BY_COMPUTE_COST` — operational outcome, не quality verdict.

Сохраняются `Data_final.xlsb`, его SHA, 289614 working rows, `DefMark`, исключение `INN`, exact accepted 47 features, запрет `Q_B1_norm`/`Q_B2_norm` как predictors, exact 3 folds seed 42, saved `GBDT_mean` Gini 0.8063993952 и закрытый final test. При xRFM `no_material_benefit`/`inferior` default direction — data / feature / blind-spot research, не новая модель.

### D-053 — Stage 14 xRFM V1 остановлен по hardware constraint

Статус: `STOPPED_BY_COMPUTE_COST / HARDWARE_CONSTRAINT`. Environment setup прошёл, pre-run implementation принят. Hardware guard остановил Smoke до `model.fit()` на AMD Ryzen 5 5500U: 6 физических cores / 12 logical processors и 15.34 GiB physical RAM не соответствуют accepted contract 8 physical cores / 32 GiB RAM; 16 GiB available RAM перед feasibility физически недостижимы. Training, `predict_proba`, feasibility и OOF не выполнялись; quality `UNKNOWN`, final test не использовался. Frozen xRFM V1 не ослабляется и новый CPU-safe xRFM experiment не открывается. D-052 остаётся историческим разрешением narrow reopen; active default снова `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES`, следующий путь — data / feature / blind-spot research.

### D-054 — Model Research Coverage и обязательный FEASIBILITY_BEFORE_EXPERIMENT_LOCK

Model zoo не является целью: full-protocol tested evidence, compute/hardware exclusions и not-opened candidates фиксируются раздельно; отсутствие run не является отрицательным quality evidence. Lessons TabPFN-3 и xRFM требуют future gate `FEASIBILITY_BEFORE_EXPERIMENT_LOCK` до implementation: novelty, actual CPU-only hardware (сейчас 6C / ~16 GiB), primary-source mechanics, честная full-protocol feasibility и expected information gain. `CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется; mathematical ceiling не заявляется.

### D-055 — Transition from model search to blind-spot diagnostics

Принято решение не открывать новые model experiments без новой проверяемой
гипотезы, которая меняет основания для решения. Вместо дальнейшего перебора
architectures начинается диагностика **805** общих ошибок моделей с
использованием сохранённых OOF и error artifacts.

Основание: на текущих 47 признаках разные проверенные семейства моделей показали
сходные ограничения, поэтому дальнейший model search имеет низкий ожидаемый
информационный эффект. Решение не утверждает математический потолок качества и
не исключает будущую пользу модели при новой гипотезе.

---

## 2026-09-07

### D-056 — Stage 16 трактуется как descriptive blind-spot diagnostics

Stage 16 подтвердил common blind spot из 805 дефолтов, наблюдаемый профиль группы и отсутствие объяснения через missingness.

Результаты PCA / nearest-neighbor / KMeans не являются доказательством информационной недостаточности или причинной структуры группы.

Silhouette для `k=2..6` не показал сильного cluster separation, но строгая устойчивость кластеров отдельно не проверялась.

Корректная интерпретация: Stage 16 мотивирует information-gap hypothesis, но не доказывает её.

### D-057 — Stage 17 закрывает historical enrichment текущего датасета

Статус:

`CURRENT_DATASET_TEMPORAL_ENRICHMENT_BLOCKED`

Подтверждено отсутствие восстанавливаемой row-level `observation_date` / `decision_date` и temporal-схемы `DefMark` для текущего `Data_final.xlsb`.

Поэтому современные внешние snapshots нельзя присоединять к историческим строкам по `INN` и считать историческими predictors.

Новые внешние feature hypotheses существуют, но их predictive value на текущем historical dataset не проверяется.

`CORE_MODEL_RESEARCH_STOPPED_CURRENT_47_FEATURES` сохраняется.

Следующий новый data-research объект должен иметь корректную row-level временную структуру.

Stage 17 не утверждает:

- математический потолок качества;
- недостаточность всех 47 признаков;
- причинную природу blind spot;
- гарантированный gain от новых источников.

---

## 2026-09-07

### D-058 — Stage 18 принят: FP/FN рассматриваются как отдельный operating layer

Статус:

`FP_FN_OPERATING_MAP_COMPLETE`

Reviewer verdict: `ACCEPT`.

Принято разделение трёх механизмов:

1. **Operating threshold** — управляет общим Recall / Precision / FN / FP trade-off.
2. **Boundary review zone** — кандидат на дополнительную проверку, поскольку около threshold ошибки концентрируются в 4+ раза сильнее среднего.
3. **Common blind spot** — отдельная проблема, не решаемая практически одним снижением threshold.

`Moderate` 15% используется только как reference к бизнес-ориентиру Recall около 69% и не является оптимальным threshold.

Правило `rank_spread >= 0.25` не принимается как practical FN review signal на текущем evidence.

Размер review zone не выбирается до появления business cost / workload constraints.

Следующий research priority:
универсальный controlled pipeline проверки нового признака.

Это соответствует финальной рамке проекта:
не model zoo, а воспроизводимый процесс проверки новых ML/ИИ-подходов и новых факторов.

---

## 2026-09-08

### D-059 — Stage 19 принят как единый протокол проверки нового признака

Статус: `NEW_FEATURE_PROTOCOL_READY`.

Вердикт Reviewer: `ACCEPT`.

До ML-проверки нового признака обязательны происхождение и временная корректность.
Затем допускается ровно одно контролируемое изменение при неизменном контракте baseline и
одинаковой рабочей CV/OOF-проверке. Final test не используется для выбора признака.

Критерий принятия должен быть определён до просмотра результата. Если evidence
недостаточно или критерий заранее не определён, решение фиксируется как
`НЕДОСТАТОЧНО ОСНОВАНИЙ ДЛЯ РЕШЕНИЯ`.

Статус `НЕ ДОПУЩЕН К ЭКСПЕРИМЕНТУ` не является вердиктом о качестве предиктора.
Текущий historical `Data_final.xlsb` по-прежнему нельзя обогащать современными
snapshots без временного якоря.

Универсальные ΔGini threshold, cost function, optimal threshold и predictive gain
конкретного нового признака не устанавливались.

---

## 2026-09-21

### D-061 — Dataset Preparation V1 требует явного human confirmation

Factual inspection и DatasetPreparationProposal не задают runtime semantics. Перед materialization специалист подтверждает target, positive class, identifier и usage status каждой physical column.

### D-062 — Arbitrary dataset V1 использует full OOF без protected final test

Политика `FULL_OOF_NO_PROTECTED_FINAL_TEST` материализует все строки с `partition_role="full"` и `final_test_locked=False`; automatic holdout/final/temporal split не создаётся.

### D-063 — Generic preparation не содержит name-based policy для Q_B1/Q_B2

`Q_B1_norm` и `Q_B2_norm` не являются глобально запрещёнными именами. Технически совместимая колонка может быть явно подтверждена как MODEL_ALLOWED в arbitrary dataset.

### D-064 — Historical Data_final profile остаётся frozen

Historical baseline сохраняет 47 MODEL_ALLOWED, `INN` как identifier, `DefMark` как target, `Q_B1_norm`/`Q_B2_norm` как BLOCKED, accepted Stage 3 working population и `final_test_locked=True`. Это профиль baseline, а не generic policy.

### D-065 — Final materialization validation выполняется по actual loaded dataframe

Snapshot служит источником physical/provenance identity, но semantic и predictor validation выполняются по dataframe, реально возвращаемому в PreparedDatasetContext. Fingerprint и source SHA fail closed защищают от stale source.

### D-066 — DatasetPreparationManifest является deterministic provenance artifact

Manifest фиксирует confirmation, delta и runtime identities. Его nested delta values immutable; filesystem path, session и timestamp не входят в scientific identity.

## 2026-09-21 — Generic Dataset UX / History

### D-067 — Product UI является generic-first

Основной пользовательский flow начинается с загрузки файла и не предлагает отдельный основной режим «Исторический набор данных».

Historical `Data_final` остаётся frozen compatibility profile внутри системы.

После `PreparedDatasetContext` downstream flow общий для любого dataset.

### D-068 — Dataset onboarding строится как последовательный мастер

Принята структура:

`Файл → Цель → Идентификатор → Признаки → Оценка → Проверка`.

На экране активен один смысловой этап. Завершённые этапы сворачиваются в компактное summary.

Внутренние enum/backend terms не выводятся в основном пользовательском UI.

Причина: техническая реализация Dataset Preparation UI получила Reviewer `ACCEPT`, но ручная продуктовая приёмка показала, что текущая инженерная форма перегружена и непонятна пользователю.

### D-069 — Analyzer предлагает target, но не определяет смысл задачи

Target proposal является только предложением системы.

Пользователь явно отвечает:

**«Что модель должна предсказывать?»**

Затем отдельно выбирает positive event из фактических значений target.

Top candidate Analyzer нельзя автоматически превращать в semantic `CONFIRMED` target.

### D-070 — Dataset History / Persistence V1 должен узнавать exact dataset по содержимому

Это нормативное решение для будущего `Dataset History / Persistence V1`, а не описание уже реализованной capability.

Переименование или копирование идентичного файла не должно создавать новую dataset identity.

После реализации, при доказанном exact content identity и совместимых relevant rules/contracts, система должна позволять восстановить confirmed preparation и history experiments без обязательного повторного expensive inspection.

Эта capability пока не реализована. В основном UI она должна отображаться как работа с сохранённым знакомым набором, а не через hash/cache terminology.

### D-071 — История отделена от актуальности проверки

Если dataset известен, но relevant inspection/preparation rules изменились, старая история и результаты сохраняются, однако старый inspection не выдаётся за актуальный.

Similarity разных dataset не является exact identity.

Будущий перенос настроек между похожими dataset допускается только как `PROPOSAL / DRAFT`, а не как `CONFIRMED`.

Persistence backend пока не зафиксирован. Решение не требует production DB.

## 2026-09-25 — Integration V1

### D-072 — ExperimentArtifact и ModelVersion являются разными сущностями

Успешный experiment не считается сохранённой deployable моделью. ModelVersion создаётся отдельным explicit final-fit действием и фиксирует trusted model spec, feature order, dataset/config/code identity и native model artifact.

Причина: selection evidence и fitted runtime model имеют разный жизненный цикл и не должны смешиваться.

### D-073 — Generic inference не содержит hardcoded identifier/target semantics

Inference нового targetless файла использует contract сохранённого ModelVersion. Identifier берётся из DatasetContract, required features проверяются и упорядочиваются по model metadata, duplicate identifier values допустимы и различаются через row identity/source position. Canonical output — probability.

Причина: один inference path должен работать для arbitrary confirmed dataset, а не только для historical INN/DefMark profile.

### D-074 — Local explanation подключается как capability, а не как условие inference

Local SHAP V1 принят для CatBoost через ту же loaded model и те же validated feature values, что использовались для prediction. Additivity проверяется в raw margin. Для моделей без принятого local explainer inference остаётся доступным, а explanation возвращает explicit unsupported.

Причина: новая модель должна подключаться отдельным explainer adapter/capability без переписывания inference/UI core.

### D-075 — Result Interpreter является model-independent post-processing boundary

Result Interpreter получает только structured LocalExplanationEvidence, не пересчитывает probability/SHAP, не выбирает threshold и не принимает кредитное решение. Semantic request защищён deterministic request_hash, который проверяется до любого доступа к provider client.

Причина: LLM должна объяснять уже рассчитанный результат, а не становиться частью predictor path.

### D-076 — OpenAI является сменным provider adapter

OpenAI adapter реализует общий ResultInterpreterClient; model name задаётся конфигурацией, API key не хранится в repository, Responses API вызывается с store=False. store=False не трактуется как Zero Data Retention.

Реальные client identifiers/feature values не отправляются во внешний LLM API без отдельного подтверждённого data-sharing/redaction policy.

### D-077 — Расширение системы выполняется через contracts/adapters/capabilities, без hardcode

Новые модели, explainers, interpreter providers и dataset semantics подключаются локально через общие интерфейсы, registry/config/metadata и capability checks. Frontend/application core не должны разрастаться ветвлениями по конкретным model_id, provider, INN, DefMark, feature names, paths или threshold.

Исключение допустимо только как явно зафиксированное временное V1 capability limitation, не как архитектурное правило.

Причина: система должна позволять добавлять или заменять компоненты без переписывания уже принятой цепочки.

### D-078 — Stage III-C разделён на локальный C1 и внешний C2

Принятое разбиение:

- **III-C1 / LOCAL MODEL USE FLOW**: Result → explicit save ModelVersion → targetless file → PredictionBatch → selected row → LocalExplanationEvidence;
- **III-C2 / EXTERNAL INTERPRETATION FLOW**: LocalExplanationEvidence → external-data policy/redaction → ResultInterpreter → provider adapter → explanation.

III-C1 должен получить Reviewer ACCEPT до начала III-C2.

Причина: C1 проверяет model lineage/inference/same-model explainability локально; C2 отдельно вводит внешний provider и data-sharing risk.

### D-079 — III-C не добавляет новый верхнеуровневый экран Streamlit

Верхнеуровневый flow остаётся:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

На `Результат` добавляется последовательный блок **«Применить модель к новым данным»**.

Причина: это минимальный defense-ready UX без рефакторинга принятого experiment wizard.

### D-080 — Streamlit работает через IntegrationWorkflowService и capability contract

Frontend не обращается напрямую к stores/native predictors/explainers/provider clients. Тонкий application facade оркестрирует accepted services и возвращает typed results/capabilities.

Capability states V1: `AVAILABLE`, `WAITING_FOR_INPUT`, `UNSUPPORTED`, `DISABLED`, `MISCONFIGURED`.

Неподдерживаемая capability справа не инвалидирует уже рассчитанный результат слева.

### D-081 — External LLM default policy отключена; defense-ready режим REDACTED_V1

По умолчанию `EXTERNAL_DATA_POLICY=DISABLED`; без configured policy provider не вызывается.

В `REDACTED_V1` внешний provider не получает identifier value, raw feature values и row identity. Full raw external sharing до защиты не реализуется.

Один checkbox пользователя не заменяет организационное data-sharing permission. `store=False` также не является таким разрешением.

### D-082 — Universal Pipeline UX V1 принят после manual III-C1 E2E

Пользовательский flow фиксируется как:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

Generic UI не содержит специальных правил по именам `Q_B1_norm`, `Q_B2_norm`, `INN`, `DefMark`; исторические ограничения `Data_final` остаются только внутри frozen compatibility profile.

Выбранный при обучении feature set является контрактом сохранённой ModelVersion для последующего inference: target на новых данных не требуется, дополнительные колонки допустимы, но все признаки модели должны присутствовать.

Manual III-C1 E2E подтверждён; найденный UTF-8 BOM defect закрыт отдельным corrective fix.

### D-083 — III-C2a фиксирует отдельную outbound policy boundary

Stage III-C2 разделён на:

- **III-C2a / External Data Boundary**;
- **III-C2b / Runtime + Streamlit Integration**.

III-C2a получил Reviewer `ACCEPT`.

Принято:

- полный `ResultInterpreterRequest` остаётся internal и не редактируется;
- `request_hash` проверяется до outbound projection;
- `REDACTED_V1` строится только positive allowlist-ом;
- внешний provider не получает identifier, row identity, raw feature values и internal provenance;
- sanitized payload имеет deterministic hash;
- `ProviderDispatchReceipt` связывает source request hash, policy id/version и exact provider payload hash;
- `PolicyBoundResultInterpreterClient` передаёт underlying provider только sanitized dispatch payload;
- существующий Stage III-A direct internal client contract не переписывается;
- capability `result_interpretation` до III-C2b остаётся `DISABLED / STAGE_III_C2_NOT_ENABLED`.

Принятый implementation commit: `ebb4c7d0`.

Следующий defense-critical stage — III-C2b: runtime configuration, provider composition, capability и continuation существующего Result UI.
