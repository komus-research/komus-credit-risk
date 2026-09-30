# QUALITY UX V1 — Native AXION

Статус: **UX / VISUAL LOCK — ACCEPTED / READY_FOR_IMPLEMENTATION**

Дата фиксации: **2026-09-30**

## 1. Цель экрана

Шаг 4 верхнеуровневого native flow:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`.

Экран не является ещё одной обязательной формой ручных настроек. Его основная роль — **контрольная точка перед дорогим full experiment**:

1. показать, что именно будет использовано;
2. автоматически проверить техническую готовность exact configuration;
3. дать один понятный action — **«Начать обучение»**;
4. после запуска на этом же шаге показать реальный progress;
5. после успешного завершения открыть `Результат`.

Stepper сохраняет название **«Проверка качества»**. Заголовок pre-run состояния: **«Проверка перед запуском»**.

## 2. Источник истины

Visual reference:

`docs/design/screens/new-analysis/05_quality_v1.png`

Functional/backend truth:

- `PreparedDatasetContext`;
- текущие `selected_feature_ids`;
- выбранный Algorithm draft;
- backend-owned model configuration resolver;
- backend-owned supported evaluation protocol;
- `ExperimentPlanningService`;
- `ExperimentApplicationService`;
- `ModelConfigurationSmokeTestService`;
- фактические progress events experiment runner.

Frontend не придумывает protocol/folds/seed, smoke status, readiness или quality metrics.

## 3. Что показывается до запуска

### 3.1. Сводка «Что будет использовано»

Read-only runtime summary:

- **Данные** — фактическое имя dataset + размер популяции/строк, если backend это предоставляет;
- **Признаки** — фактическое количество выбранных predictors;
- **Алгоритм** — фактический `display_name_ru` выбранной модели;
- **Настройки алгоритма** — `Рекомендуемые` или `Расширенные`.

Действие **«Изменить»** допустимо для Признаков, Алгоритма и Настроек алгоритма.

У карточки **«Данные»** action «Изменить» на Quality V1 отсутствует. Смена source не является локальной правкой Quality и требует нового прохождения upstream preparation flow.

Никаких demo values из PNG не хардкодить.

## 4. Автоматический preflight

Основной пользовательский термин: **«Проверка перед запуском»**.

Технический термин `smoke` не нужен в основном UI.

После появления валидного Algorithm draft AXION автоматически готовит/валидирует experiment request и выполняет matching technical preflight. Отдельной primary-кнопки **«Проверить настройки»** нет.

Backend foundation уже существует: `ModelConfigurationSmokeTestService`.

Принятая smoke policy:

- deterministic;
- stratified;
- bounded;
- `max_rows = 128`;
- выполняется только на разрешённой evaluation population;
- rows закрытого final test не используются;
- real `factory.create()`;
- real bounded `fit()`;
- real `predict_positive_proba()`;
- проверка формы predictions, finite values и диапазона probability `[0, 1]`.

Это **не** quality evaluation и не заменяет OOF.

## 5. Smoke gate

Matching `SmokeStatus.PASS` обязателен перед **каждым** full experiment — и для Recommended, и для Advanced.

Matching identity backend-owned. Frontend не определяет stale вручную.

Существующий PASS перестаёт авторизовывать full run, когда изменяется relevant canonical identity, включая:

- dataset/context identity;
- feature registry / selected ordered features;
- model plugin contract;
- resolved model configuration;
- seed;
- smoke policy identity.

После relevant change UI возвращается в pending/preflight state и получает новое backend evidence.

## 6. Пользовательская сводка preflight

Accepted success presentation:

- ✓ **Данные готовы** — `Подтверждённый набор данных доступен для запуска.`
- ✓ **Выбранные признаки корректны** — `Выбранный набор признаков доступен алгоритму.`
- ✓ **Алгоритм доступен** — `Алгоритм и необходимые компоненты доступны.`
- ✓ **Настройки совместимы** — `Конфигурация успешно проверена.`
- ✓ **Пробное обучение выполнено** — `Модель успешно обучилась на небольшой контрольной выборке.`
- ✓ **Пробный прогноз получен** — `Прогнозы получены в корректном формате.`

Затем крупный success block: **«Готово к запуску»**.

Текст:

`Предварительная проверка подтверждает техническую готовность конфигурации.`

`Качество модели будет рассчитано во время полноценной проверки.`

`После обучения AXION автоматически рассчитает метрики качества.`

Эти шесть строк — пользовательская **сводка успешного backend preflight**. Они не являются шестью независимыми progress events, если backend не предоставляет такие отдельные события.

До `PASS` нельзя фейково подсвечивать отдельные пункты как уже завершённые.

Pending state: **«Выполняем предварительную проверку…»**

FAIL state показывает безопасное русское объяснение и понятное следующее действие. Raw exception/traceback/backend internals в основном UI не показывать.

## 7. Главный action

После matching preflight PASS и валидного experiment plan: **«Начать обучение»**.

Это единственная primary CTA pre-run состояния.

Не использовать `Проверить настройки`, `Начать обучение и проверку качества` или вторую конкурирующую primary action.

Если readiness отсутствует, кнопка disabled.

## 8. Дополнительные настройки

Блок **«Дополнительные настройки»** по умолчанию collapsed.

Подпись: **«Рекомендуемые параметры уже выбраны автоматически.»**

Backend-authoritative параметры Quality:

- evaluation protocol;
- folds;
- seed.

Обычный пользователь не обязан менять их.

Default values и ограничения приходят от backend supported protocol; frontend не хардкодит `3`, `42` или диапазоны как собственную scientific truth.

Если изменение параметра меняет experiment identity/readiness, existing plan/preflight инвалидируется по backend semantics.

Native Quality V1 не должен просить пользователя вручную вводить `artifact_id` для comparison. Сравнение подключается только после появления trusted native result/history selection contract.

## 9. Технические сведения

Отдельный collapsed block **«Технические сведения»** может показывать для воспроизводимости:

- protocol id/version, evaluation level, folds, seed;
- prepared context identity в безопасном виде;
- model/configuration identities;
- smoke policy/version/status/identity;
- plan validation status.

Не показывать secrets, raw exceptions и giant raw JSON.

## 10. Что Quality pre-run НЕ показывает

До full run нет Gini, ROC-AUC, PR-AUC, Precision, Recall, F1, TP/TN/FP/FN, confusion matrix, fold quality, threshold/business decision, SHAP, LLM explanation или «лучшей модели».

Technical preflight `PASS` означает только: **«конфигурация технически готова к full experiment»**.

Он не означает: **«модель качественная»**.

## 11. Full experiment

Нажатие **«Начать обучение»** запускает существующий full experiment path с matching smoke gate.

Проверка качества остаётся OOF evaluation по принятому protocol.

Final test не используется для выбора модели/признаков/параметров/threshold и остаётся под существующими research guards.

## 12. Progress UX

После старта не создавать отдельный новый top-level экран. Тот же шаг 4 переходит из pre-run state в progress state.

Показывать только реальные backend progress events, например:

- подготовка запуска;
- fold started/completed;
- aggregate metrics;
- persistence;
- completed.

Допустимый человекочитаемый вид `Часть 1 из N` — только если номера/total реально пришли из progress event.

Запрещены fake percentage, придуманный ETA и искусственный progress по таймеру.

## 13. Завершение

После успешного full experiment:

- Quality step становится completed;
- experiment artifact является source of truth результата;
- пользователь получает действие **«Перейти к результатам»** или безопасный переход на `#/analysis/result` после сохранения accepted state.

На шаге 4 не требуется дублировать полный Result dashboard.

## 14. Navigation / invalidation

`Назад к алгоритму` сохраняет Quality inputs.

Реальное изменение Algorithm scientific draft инвалидирует Quality readiness/result according to session/application contract.

Presentation-only изменения, которые не меняют scientific configuration, не должны инвалидировать completed Algorithm/Quality state.

Возврат к Features и реальное изменение selected features инвалидирует downstream plan/preflight/full-run readiness, но не меняет permissions FeatureRegistry.

Stale `PreparedDatasetContext` fail-closed возвращает пользователя в upstream Data recovery flow и очищает downstream scientific state.

## 15. Visual lock

Использовать `docs/design/screens/new-analysis/05_quality_v1.png`.

Инварианты: общий AXION Sidebar из Home V2; Graphite / Emerald; тот же wizard header; summary сверху; central automatic preflight; крупный success block; collapsed `Дополнительные настройки`; collapsed `Технические сведения`; footer `Назад к алгоритму` + `Начать обучение`.

Visual reference задаёт composition и hierarchy. Runtime values и states всегда берутся из backend contracts, а не из demo text PNG.

## 16. Acceptance для будущей реализации

Native Quality V1 считается готовым, когда доказано:

1. direct route без completed Algorithm fail-closed;
2. runtime summary не содержит fake data;
3. supported protocol backend-owned;
4. experiment plan валидируется автоматически;
5. matching smoke запускается автоматически;
6. full run без matching PASS невозможен;
7. smoke PASS не называется quality verdict;
8. `Начать обучение` — одна primary CTA;
9. full experiment использует accepted OOF path;
10. progress показывает только реальные events;
11. Result открывается только после successful persisted experiment;
12. relevant upstream change инвалидирует stale downstream readiness;
13. no final-test misuse;
14. frontend build/tests/diff-check PASS.
