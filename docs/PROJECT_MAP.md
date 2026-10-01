# Каноническая карта проекта AXION

> Этот документ — единственный источник ответа на два вопроса: **где проект находится сейчас** и **что делаем следующим**.
> Архитектурные, исследовательские и UX-документы сохраняют свои решения и доказательства, но не могут самостоятельно менять текущий NEXT.

Проверено относительно ветки `design/home-v2-algorithm-v2`, commit `2cd94ae1b7a6412f13f2c4f6271e773f55aaf4d4`.
Состояние рабочей копии на момент проверки: чистое, HEAD совпадает с отслеживаемой веткой origin.

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
| Проверка перед обучением | Проверка конфигурации и smoke перед полным запуском | Native Quality preflight реализован; полный запуск намеренно не подключён | React → FastAPI → ExperimentApplicationService | **ГОТОВО** | Следующий этап — подключить полный эксперимент |
| Полное обучение | Запуск полного OOF-эксперимента с реальным прогрессом и сохранением результата | ExperimentApplicationService и экспериментальное ядро существуют; native end-to-end запуск не подключён | application/core; native wiring частичный | **ЧАСТИЧНО** | Сначала решить ownership artifact store; затем Quality → run → persisted artifact |
| Результат | Метрики, OOF-результат, объяснения и интерпретация сохранённого эксперимента | Result V2 / OOF / SHAP / Interpreter backend/core существуют; native React route/UI отсутствуют | application/core; compatibility UI существует | **ЧАСТИЧНО** | Нужен сохранённый native artifact и FastAPI → React Result |
| История | Каталог завершённых экспериментов и открытие точного сохранённого результата | AnalysisHistory backend принят; native React History отсутствует | application/core; compatibility Streamlit catalog существует | **ЧАСТИЧНО** | После native Result подключить History к тому же canonical artifact source |
| Модели | Работа с сохранёнными версиями моделей | Product / Visual Lock принят; ModelVersion и saved-model inference backend/application компоненты существуют, но native React Models UI и полный trusted browse/persistence path не завершены | application/core + accepted UX/visual locks; native UI отсутствует | **ЧАСТИЧНО** | Только после Result и History |
| Настройки | Настройки продукта | Product / Architecture / Visual Lock принят; SET-BE1 / SET-BE2 и native React Settings UI ещё не реализованы | accepted UX/architecture docs; runtime implementation pending | **НЕ НАЧАТО** | Только после более приоритетных этапов |

## Текущая точка проекта

**Native AXION подтверждён до экрана «Проверка перед обучением»; следующий незавершённый продуктовый участок — полный эксперимент и сохранение его артефакта.**

## Следующий этап

**Проверка перед обучением → полный OOF-эксперимент → реальный progress → сохранённый ExperimentArtifact → переход к native Result.**
## Что уже существует и не должно переписываться с нуля

- Принятый исследовательский pipeline и ограничения по данным.
- `ExperimentApplicationService` и существующий путь полного эксперимента.
- ExperimentArtifact V3 и проверяемая persistence-семантика.
- `OOFResultService`.
- `OOFExplanationService` и fold-specific OOF evidence.
- Global OOF SHAP.
- Result Interpreter как интерпретатор результата, а не кредитный предиктор.
- `AnalysisHistoryService` и принятые semantics History.
- Принятые native Home / Data / Features / Algorithm / Quality preflight.

Новый React UI должен использовать эти application/core-контракты через FastAPI, а не создавать второй ML-пайплайн.

## Открытые архитектурные вопросы

### Ownership ExperimentArtifactStore — блокер перед полным обучением

Сейчас подтверждены разные composition roots:
- `app/native_runtime.py` создаёт `ExperimentArtifactStore(Path(".native-quality-artifacts"))`;
- compatibility runtime в `app/bootstrap.py` по умолчанию использует `.streamlit-artifacts`.

**Канонический владелец ещё не выбран.** Нельзя автоматически объявлять один root правильным только по имени.

До подключения полного обучения нужно доказать:
1. кто записывает и читает каждый root;
2. какие реальные артефакты уже находятся в каждом root;
3. какие Result/History/Explanation-контракты зависят от каждого store;
4. какой один application-owned source должен использовать native run, Result и History;
5. нужны ли старым артефактам compatibility-only чтение или отдельная миграция.

Запрещено молча смешивать roots, выбирать «latest artifact» из разных roots или мигрировать данные без отдельного решения и проверки.
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
