# Connect Algorithm UX V1 — Product / Visual Lock

Status: **ACCEPTED PRODUCT / VISUAL LOCK — BACKEND IMPLEMENTATION PENDING**

Primary visual reference:
`docs/design/screens/algorithm/01_connect_algorithm_v1.png`.

## 1. Что именно подключается

Экран подключает **алгоритм / trusted ModelPlugin**, а не уже обученную модель.

Canonical distinction:

```text
Algorithm / ModelPlugin
→ можно выбрать и обучать многократно

Training run
→ создаёт отдельную обученную ModelVersion
```

Один подключённый алгоритм может позже иметь сколько угодно обученных ModelVersion на разных датасетах, наборах признаков и конфигурациях.

Поэтому на экране подключения алгоритма не показываются:
- dataset;
- количество признаков конкретного обучения;
- OOF/quality metrics;
- дата обучения;
- SHAP конкретного объекта;
- identity конкретной ModelVersion.

## 2. Две точки входа — один flow

Один и тот же Connect Algorithm flow должен быть доступен из двух мест:

1. `Новый анализ → Алгоритм → Подключить алгоритм`.
2. `Модели → Подключить алгоритм`.

Это не две реализации.

После успешного подключения:
- из `Новый анализ` пользователь возвращается в текущий шаг «Алгоритм», а новый algorithm/plugin становится доступен в catalog для выбора;
- из `Модели` пользователь возвращается во вкладку «Модели», где новый алгоритм становится доступен в общем model-platform catalog.

После отмены возврат идёт в ту же точку входа без изменения текущего analysis/model state.

## 3. Название в AXION и техническая identity

Пользователь может задать editable display alias:

**«Название в AXION»**

Например:

`Экспериментальный SuperBoost`

Это только пользовательское отображаемое имя подключённого алгоритма.

Отдельно read-only показываются trusted package facts:
- Алгоритм: `SuperBoost`;
- ID: `superboost`;
- версия;
- категория;
- краткое описание.

Display alias:
- не меняет `model_id`;
- не меняет plugin/provider identity;
- не является именем обученной ModelVersion;
- не влияет на воспроизводимость экспериментов.
## 4. Проверка возможностей

До подключения trusted package проверяется fail-closed по обязательным capabilities:

- обучение;
- настройка параметров;
- сохранение;
- загрузка;
- прогнозирование;
- Local Explanation / SHAP;
- совместимость validated explanation с Result Interpreter.

Полноценный алгоритм основного AXION flow не подключается как AVAILABLE, если обязательная capability отсутствует или её trusted provider/identity validation не проходит.

Строка **«Понятное объяснение»** означает именно совместимость validated explanation с Result Interpreter contract.

Она не означает:
- что внешний LLM provider сейчас включён;
- что был выполнен внешний LLM call;
- что конкретная ModelVersion уже существует.

В runtime copy допустим статус **«Совместимо»** вместо демонстрационного **«Готово»** из PNG, если это точнее отражает capability semantics.

## 5. Безопасность подключения

V1 product direction не разрешает:
- arbitrary `.py` execution;
- произвольный pickle/code upload;
- dynamic import пользовательских классов из браузера;
- установку непроверенных packages из UI.

Подключение допустимо только через reviewed/trusted AXION plugin/package contract и зарегистрированные trusted providers.

Точный backend package/install contract ещё не реализован и не выводится из PNG.

## 6. Visual lock

Visual reference фиксирует:
- AXION shell;
- header «Подключить алгоритм»;
- package summary;
- editable «Название в AXION»;
- read-only algorithm identity;
- capability checklist;
- success block «Алгоритм готов к подключению»;
- CTA «Подключить алгоритм»;
- info block «Что дальше?»;
- collapsed «Технические сведения».

Demo values `superboost_axion_v1.zip`, `SuperBoost`, version `1.0` не являются runtime truth и не хардкодятся.

## 7. Что происходит после подключения

Подключение algorithm/plugin само по себе:
- не запускает training;
- не выбирает dataset;
- не выбирает features;
- не создаёт ModelVersion;
- не запускает SHAP/LLM для объекта.

После подключения алгоритм становится доступен в catalog.

Дальше пользователь может выбрать его на шаге «Алгоритм», настроить поддерживаемые параметры и запустить обычный AXION training flow.

Каждое завершённое сохранённое обучение создаёт отдельную ModelVersion со своей dataset/feature/config/provenance identity.

## 8. Implementation boundary

Visual/product lock принят заранее.

Backend/UI implementation Connect Algorithm V1 — отдельный будущий stage.

До его реализации:
- текущий Native Algorithm V2 остаётся source of truth для существующих встроенных algorithms;
- нельзя симулировать подключение hardcode-ом;
- нельзя превращать mockup в permission на untrusted executable upload;
- фактические capabilities берутся только из trusted model-platform contracts.
