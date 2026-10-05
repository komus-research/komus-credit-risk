# Каноническая карта проекта AXION

> Этот документ — единственный источник ответа на два вопроса: **где проект находится сейчас** и **что делаем следующим**.
> Архитектурные, исследовательские и UX-документы сохраняют свои решения и доказательства, но не могут самостоятельно менять текущий NEXT.

Актуальное состояние проверено на ветке `design/home-v2-algorithm-v2`, HEAD `8f431e778c6adc632d8e281fbeec248752b99151`. Working tree содержит принятые/текущие незакоммиченные изменения; unrelated work не сбрасывать.

## Как читать эту карту

Статусы:
- **ГОТОВО** — этап существует в каноническом product path и принят как рабочий.
- **ЧАСТИЧНО** — часть backend/core или compatibility-реализации существует, но product path не завершён.
- **НЕ НАЧАТО** — продуктовый этап ещё не реализован.
- **ТРЕБУЕТ ПРОВЕРКИ** — нельзя честно назначить статус без отдельного доказательства.

Готовность Streamlit-экрана не делает соответствующий этап готовым в AXION.

## Единственный продуктовый путь

```text
React + TypeScript + Vite
        ↓
      FastAPI
        ↓
 application/core
```

**Streamlit — frozen compatibility frontend.** Новые продуктовые функции AXION не реализуются в Streamlit без отдельного явного решения.
## Карта этапов

| Этап | Что получает пользователь | Реальное состояние | Где | Статус | Что блокирует / следующий шаг |
|---|---|---|---|---|---|
| Главная | Вход в AXION и начало анализа | Native Home реализован и принят; Sidebar Final V1 visual lock принят (`docs/design/components/sidebar/01_sidebar_final_v1.png`), но profile/auth card из демонстрационного PNG явно исключена из contract | React → FastAPI/session | **ГОТОВО** | При visual implementation сохранить motif/IA, не переносить fake avatar/name/role/profile; нижняя зона — только неинтерактивный brand treatment |
| Данные | Загрузка, роли столбцов, подтверждение подготовки | Native Data реализован; DATA-WARN-R1 + Data Warnings V2 приняты. Confirmation V2 visual lock принят (`02_data_confirmation_v2.png`), runtime visual polish ещё не выполнен | React → FastAPI → preparation | **ГОТОВО** | Visual polish по accepted locks после текущего blocker; semantics не переоткрывать |
| Признаки | Выбор разрешённых признаков | Native Features реализован и принят | React → FastAPI → application/core | **ГОТОВО** | Ничего для текущего пути |
| Алгоритм | Выбор алгоритма и его настроек | Native Algorithm реализован и принят | React → FastAPI → application/core | **ГОТОВО** | Ничего для текущего пути |
| Проверка перед обучением | Проверка конфигурации и smoke перед полным запуском | Native Quality preflight реализован и принят; Quality V2 visual lock + Long Operations V1 приняты, но ещё не полностью внедрены в runtime | React → FastAPI → ExperimentApplicationService | **ГОТОВО** | Visual polish после blocker; scientific/preflight semantics не менять |
| Полное обучение | Запуск полного OOF-эксперимента с реальным прогрессом и сохранением результата | Native Quality запускает существующий `ExperimentApplicationService.run_experiment()`, публикует реальные progress events и сохраняет `ExperimentArtifact` в canonical `.axion-artifacts`; live XGBoost run на `Data_final.xlsb` (`362018` строк, 3 folds) успешно завершил OOF training и создал persisted Result | React → FastAPI → application/core | **ГОТОВО** | Ничего для training path; UX progress polish идёт отдельно по Long Operations V1 |
| Результат | Метрики, OOF-результат, объяснения и интерпретация сохранённого эксперимента | Native React Result Overview, Threshold Explorer, Objects, Object Detail и Local Explanation/SHAP приняты. На real XGBoost artifact `362018 × 49`, 3 folds Global OOF Explanation долго считается и завершается `409`; основной Result остаётся доступен. Result Interpreter V2 UX/architecture lock принят, native integration ещё не реализована | React → FastAPI → application/core | **ЧАСТИЧНО** | Immediate blocker: **Global OOF Explanation Reliability / Performance V1**; после fix вернуться к RI-BE → RI-UI → RI-EXPORT |
| История | Каталог завершённых экспериментов и открытие точного сохранённого результата | AnalysisHistory backend принят; native React History отсутствует | application/core; compatibility Streamlit catalog существует | **ЧАСТИЧНО** | После native Result подключить History к тому же canonical artifact source |
| Модели | Работа с сохранёнными версиями моделей | Product / Visual Lock принят; ModelVersion и saved-model inference backend/application компоненты существуют, но native React Models UI и полный trusted browse/persistence path не завершены | application/core + accepted UX/visual locks; native UI отсутствует | **ЧАСТИЧНО** | Только после Result и History |
| Настройки | Настройки продукта | Product / Architecture / Visual Lock принят; SET-BE1 / SET-BE2 и native React Settings UI ещё не реализованы | accepted UX/architecture docs; runtime implementation pending | **НЕ НАЧАТО** | Только после более приоритетных этапов |

## Текущая точка проекта

**Native AXION подтверждён через Quality → OOF run → persisted `ExperimentArtifact` → Result Overview → Threshold Explorer → Objects → Object Detail → Local Explanation/SHAP. Local SHAP принят. Текущий blocker — Global OOF Explanation на большом XGBoost artifact: replay fold models полностью совпал с persisted OOF scores (`max abs diff = 0.0` во всех folds), а generic global path подтверждённо делает one-row SHAP/evidence на каждую OOF-строку.**

## Следующий этап

**IMMEDIATE NEXT:** Architect → implementation → Reviewer для **Global OOF Explanation Reliability / Performance V1**. Scientific invariant не меняется: exact row-weighted `mean(abs(local OOF SHAP))` по всей OOF population; sampling/built-in gain/final-model fallback запрещены. После закрытия blocker продолжается **RI-BE → RI-UI → RI-EXPORT** по `docs/workstreams/generic_dataset_onboarding_v1/RESULT_INTERPRETER_V2_LOCK.md`.
## Что уже существует и не должно переписываться с нуля

- Принятый исследовательский pipeline и ограничения по данным.
- `ExperimentApplicationService` и существующий путь полного эксперимента.
- ExperimentArtifact V3 и проверяемая persistence-семантика.
- `OOFResultService`.
- `OOFExplanationService` и fold-specific OOF evidence.
- Global OOF SHAP scientific semantics; large-XGBoost execution path сейчас требует reliability/performance corrective.
- Result Interpreter как интерпретатор результата, а не кредитный предиктор.
- `AnalysisHistoryService` и принятые semantics History.
- Принятые native Home / Data / Features / Algorithm / Quality preflight / full training / Result Overview / Threshold Explorer / Objects.

Новый React UI должен использовать эти application/core-контракты через FastAPI, а не создавать второй ML-пайплайн.

## Зафиксированные архитектурные решения

### Единое хранилище результатов native AXION

Native composition создаёт один application-owned `ExperimentArtifactStore` в `<repository root>/.axion-artifacts`. Тот же store используется `ExperimentApplicationService`, `OOFResultService`, `OOFExplanationService` и `AnalysisHistoryService`.

`.streamlit-artifacts` остаётся compatibility-only storage. Roots не смешиваются, automatic migration / dual-read / выбор «latest artifact» между ними отсутствуют.
## Что НЕ является доказательством готовности

- Наличие аналогичного экрана в Streamlit.
- Принятый backend без подключённого native end-to-end пути.
- Успешный frontend build без проверки поведения.
- Старый документ со словом NEXT.
- Stale output notebook или старый дорогой run.
- Существование файла артефакта без проверки identity/manifest/contract.
- Random CV/OOF как доказательство временной стабильности.

На последней целевой проверке native Result/Quality backend-тестов было **46 passed, 1 warning**, а `npm run build` завершался успешно. При этом собственных React UI-тестов в `frontend/` не было обнаружено; это отдельный пробел проверки, а не основание считать принятые этапы несуществующими.

## Исторические и compatibility-реализации

Streamlit-код и принятые Streamlit Result/History этапы сохраняются как compatibility/reference evidence. Они не удаляются ради «чистоты истории», но не определяют готовность native AXION и не задают следующий продуктовый этап.

Ошибочная попытка продолжить новый Result UI в Streamlit была остановлена после review и не должна возобновляться как product work.

## Правила обновления карты

1. Перед изменением карты проверить branch, HEAD, status/diff и фактические затронутые файлы.
2. Статус меняется только по доказательству: код + требуемая проверка + принятый review.
3. Backend/core, compatibility UI и native product UI всегда различаются явно.
4. Только этот документ определяет текущую точку и следующий продуктовый этап.
5. Другие документы могут ссылаться на эту карту, но их исторические NEXT не имеют приоритета.
6. Новый product UI идёт только через React/FastAPI. Изменения Streamlit требуют явной compatibility-задачи.
7. После каждого принятого продуктового этапа обновляется эта карта и фиксируется commit, относительно которого она проверена.
8. Если доказательства конфликтуют, ставится **ТРЕБУЕТ ПРОВЕРКИ**, а не предполагаемый статус.

## Инварианты исследования, которые карта не отменяет

- Target: `DefMark`; identifier: `INN`.
- `Q_B1_norm` и `Q_B2_norm` — только diagnostic/reference, не predictors рабочей модели.
- Final test — только финальная проверка, не выбор модели, признаков, threshold или research direction.
- Нет надёжной row-level даты наблюдения: random CV/OOF не доказывает temporal stability.
- LLM используется только как Result Interpreter и не является кредитным предиктором.
