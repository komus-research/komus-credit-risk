# Каноническая карта проекта AXION

> Этот документ — единственный источник ответа на два вопроса: **где проект находится сейчас** и **что делаем следующим**.
> Архитектурные, исследовательские и UX-документы сохраняют свои решения и доказательства, но не могут самостоятельно менять текущий NEXT.

Продуктовый код текущего этапа проверен относительно ветки `design/home-v2-algorithm-v2`, commit `8f4dfdb5eb271f12e6f6a76022a4c0687f7dddbd`.

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
| Главная | Вход в AXION и начало анализа | Native Home реализован и принят; в sidebar остаётся presentation debt: hardcoded `Андреев П. С. / Аналитик` без принятого auth/profile contract | React → FastAPI/session | **ГОТОВО** | Debt не блокирует основной flow; убрать fake profile отдельной UI-правкой |
| Данные | Загрузка, роли столбцов, подтверждение подготовки | Native Data и подтверждение реализованы и приняты | React → FastAPI → preparation | **ГОТОВО** | Ничего для текущего пути |
| Признаки | Выбор разрешённых признаков | Native Features реализован и принят | React → FastAPI → application/core | **ГОТОВО** | Ничего для текущего пути |
| Алгоритм | Выбор алгоритма и его настроек | Native Algorithm реализован и принят | React → FastAPI → application/core | **ГОТОВО** | Ничего для текущего пути |
| Проверка перед обучением | Проверка конфигурации и smoke перед полным запуском | Native Quality preflight реализован и принят; после PASS доступен явный запуск полного обучения | React → FastAPI → ExperimentApplicationService | **ГОТОВО** | Ничего для текущего пути |
| Полное обучение | Запуск полного OOF-эксперимента с реальным прогрессом и сохранением результата | Native Quality запускает существующий `ExperimentApplicationService.run_experiment()`, публикует реальные progress events и сохраняет `ExperimentArtifact` в canonical `.axion-artifacts`; дорогой полный OOF на реальном большом dataset в рамках wiring-этапа не запускался | React → FastAPI → application/core | **ГОТОВО** | Ничего для текущего пути |
| Результат | Метрики, OOF-результат, объяснения и интерпретация сохранённого эксперимента | Native React Result Overview, Threshold Explorer и Objects приняты; Objects читает server-side OOF list через `OOFResultService.objects()` с current artifact/current threshold из trusted session; Object Detail / SHAP / Interpreter в native React ещё не подключены | React → FastAPI → application/core | **ЧАСТИЧНО** | Следующий этап — native Object Detail |
| История | Каталог завершённых экспериментов и открытие точного сохранённого результата | AnalysisHistory backend принят; native React History отсутствует | application/core; compatibility Streamlit catalog существует | **ЧАСТИЧНО** | После native Result подключить History к тому же canonical artifact source |
| Модели | Работа с сохранёнными версиями моделей | Product / Visual Lock принят; ModelVersion и saved-model inference backend/application компоненты существуют, но native React Models UI и полный trusted browse/persistence path не завершены | application/core + accepted UX/visual locks; native UI отсутствует | **ЧАСТИЧНО** | Только после Result и History |
| Настройки | Настройки продукта | Product / Architecture / Visual Lock принят; SET-BE1 / SET-BE2 и native React Settings UI ещё не реализованы | accepted UX/architecture docs; runtime implementation pending | **НЕ НАЧАТО** | Только после более приоритетных этапов |

## Текущая точка проекта

**Native AXION подтверждён через полный Quality → OOF run → persisted `ExperimentArtifact` → React Result Overview → Threshold Explorer → Objects. Следующий незавершённый продуктовый участок — карточка отдельного OOF-объекта в React.**

## Следующий этап

**Native Objects → Object Detail через public `OOFResultService.object_detail()`; после этого — Local Explanation/SHAP отдельным controlled stage.**
## Что уже существует и не должно переписываться с нуля

- Принятый исследовательский pipeline и ограничения по данным.
- `ExperimentApplicationService` и существующий путь полного эксперимента.
- ExperimentArtifact V3 и проверяемая persistence-семантика.
- `OOFResultService`.
- `OOFExplanationService` и fold-specific OOF evidence.
- Global OOF SHAP.
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

На последней целевой проверке native backend-тестов было **45 passed, 1 warning**, а `npm run build` завершался успешно. При этом собственных React UI-тестов в `frontend/` не было обнаружено; это отдельный пробел проверки, а не основание считать принятые этапы несуществующими.

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
