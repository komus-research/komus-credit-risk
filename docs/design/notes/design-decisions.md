# Design decisions V1

1. Брендовое направление: **AXION**.
2. Основной визуальный стиль: тёмный технологичный интерфейс с emerald / teal акцентами.
3. Главная AXION V2 — принятый visual reference общего shell/sidebar; файл `01_home_axion_v2_candidate.png` сохраняет историческое имя, но имеет статус VISUAL LOCK.
4. Основной пользовательский поток: `Данные → Признаки → Алгоритм → Проверка качества → Результат`.
5. Экраны в `docs/design/screens/` считаются рабочими утверждёнными референсами первой сборки.
6. Макеты задают композицию, визуальную иерархию и характер интерфейса; backend-контракты остаются источником истины для данных и поведения.
7. Мелкие визуальные правки допускаются после реального просмотра в приложении и подтверждения владельцем.
8. Не начинать новую UI-реализацию без проверки соответствующего design reference.
9. Не выбирать самостоятельно порядок экранов, новую визуальную концепцию или другую модель разработки без согласования с владельцем.
10. Quality V1: visual lock — `docs/design/screens/new-analysis/05_quality_v1.png`; экран является контрольной точкой перед full experiment, а не второй формой обязательных настроек.
11. Quality preflight запускается автоматически; пользовательская primary CTA после PASS — **«Начать обучение»**. Термин `smoke` остаётся техническим и не используется как quality verdict.
12. После старта шаг 4 показывает реальный progress full experiment на том же экране; fake percentages/ETA запрещены, затем открывается `Результат`.
13. Result V2: приняты visual lock `02_result_model_overview_v2.png`, `03_threshold_explorer_v1.png`, `04_result_objects_v2.png`.
14. Threshold Explorer использует OOF scores; изменение threshold не переобучает модель и меняет только derived classification/metrics.
15. Result semantic accents: FN — restrained pink/red, FP — amber, TP — cyan/teal, TN — muted neutral; target fact и threshold position остаются отдельными смыслами.
16. В Objects marker matrix фиксирована: TP=`● cyan Да`, FN=`● pink/red Да`, TN=`○ muted Нет`, FP=`○ amber Нет`.
17. Objects table — scrollable/virtualizable analytical view со sticky header; classic numbered pagination не является canonical UX.
18. Fold в Objects остаётся read-only OOF provenance с tooltip; точные Result backend/public contracts определяются отдельно Architect и не выводятся из PNG.
19. Профессиональный принцип AXION: скрывать сложность можно, удалять реально поддерживаемую аналитическую возможность — нельзя; advanced controls допустимо убирать на второй уровень UI.
20. Object Detail показывает basic OOF result сразу; Local Explanation запускается автоматически отдельным request и не блокирует основной экран.
21. Для любой модели, доступной как полноценная модель AXION, обязателен validated путь `prediction → Local Explanation → Result Interpreter`; UI не ветвится по model family.
22. External LLM не запускается автоматически: после готового Local Explanation пользователь явно вызывает «Сформировать объяснение», если policy/provider capability доступна.
23. Прежний `GBDT Mean SHAP = UNSUPPORTED` superseded Universal Model Explainability V1: целевая semantics — validated probability-space ensemble explanation с fail-closed reconstruction checks.
24. Objects screen: control «Диапазон оценки модели» обязателен — dual-handle slider 0,00–1,00 с явными min/max values; он фильтрует OOF object list через `min_score`/`max_score`, не меняя threshold или score. Если текущий visual reference его не показывает, это visual omission и control должен быть возвращён в следующей revision.
25. Object Detail V1: visual lock — `docs/design/screens/result/05_result_object_detail_v1.png`; экран показывает один OOF-объект, deterministic outcome explanation, Local Explanation READY в режиме «Кратко», role-aware LLM entry по явному действию и collapsed object/technical details.
26. Object Detail LLM V1: visual lock — `docs/design/screens/result/06_result_object_detail_llm_v1.png`; LLM READY остаётся на том же detail screen, показывает четыре блока «Краткий вывод / Что увеличило оценку / Что уменьшило оценку / Что важно учитывать», допускает «Сформировать заново» и обязан использовать только validated Local Explanation evidence текущего объекта. «Начальная оценка модели» — SHAP reference point с поясняющим tooltip, не threshold и не business risk.
