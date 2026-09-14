# Streamlit Prototype V1 — итог

## Цель

Показать рабочий end-to-end интерфейс поверх уже принятого ML/backend foundation без изменения research semantics.

## Что реализовано

Streamlit Prototype V1 ведёт пользователя по пяти шагам: `Данные → Признаки → Модель → Эксперимент → Результат`.

Frontend получает подготовленный dataset context и application-facing services. ML-core не знает о Streamlit/SPARK; frontend не знает о конкретных моделях и конкретном списке 47 признаков. Backend boundaries включают Dataset Contract, Feature Registry, Model Registry, Experiment Config, Experiment Runner, Experiment Result, Artifact Persistence, Comparison, Application Service и Planning Service.

## Manual E2E evidence

До UX remediation вручную был пройден полный путь:

`готовый Data_final → выбор признаков → CatBoost → plan → 3-fold OOF → persisted result`.

Наблюдаемые значения ручного E2E:

- Gini: **0.8043**;
- ROC-AUC: **0.9022**;
- PR-AUC: **0.6020**;
- Precision@0.5: **0.7211**;
- Recall@0.5: **0.3649**;
- F1@0.5: **0.4846**;
- FN: **17 791**;
- FP: **3 954**;
- TN: **257 645**;
- TP: **10 224**.

Это working-sample OOF; final test не использовался. Это evidence работоспособности product chain, а не новый model-selection experiment.

## Что выявил manual UX audit

- неправильный обычный launcher;
- долгие операции без понятного progress;
- internal IDs/JSON доминировали в UI;
- comparison path был неполным.

## Что принято после remediation

- canonical launcher;
- real stage progress;
- observational listener;
- human-readable Data/Experiment/Result;
- reachable same-session comparison;
- technical details вторым уровнем.

Reviewer final verdict: **ACCEPT**.

## Ограничения

- После remediation дорогой полный KOMUS E2E заново не выполнялся.
- Developer reported lightweight suite: **91 passed**, но Reviewer независимо полный suite не воспроизводил.
- Random OOF не доказывает temporal stability.
- Final test не использовался.
- Prototype не означает production readiness.
- SPARK/model onboarding/production frontend ещё не реализованы.

## Следующий шаг

Не открывать новый model research автоматически.

Следующий product step выбирать отдельным архитектурным вопросом. Для research сохраняется уже принятое ограничение по temporal enrichment и остановка model-only поиска на текущих 47 features.
