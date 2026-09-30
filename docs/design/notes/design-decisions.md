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
13. Result V2: приняты visual lock `02_result_model_overview_v2.png`, `03_threshold_explorer_v1.png`, `04_result_objects_v1.png`.
14. Threshold Explorer использует OOF scores; изменение threshold не переобучает модель и меняет только derived classification/metrics.
15. Result semantic accents: FN — restrained pink/red, FP — amber, TP — cyan/teal, TN — muted neutral; target fact и threshold position остаются отдельными смыслами.
16. В Objects marker matrix фиксирована: TP=`● cyan Да`, FN=`● pink/red Да`, TN=`○ muted Нет`, FP=`○ amber Нет`.
17. Objects table — scrollable/virtualizable analytical view со sticky header; classic numbered pagination не является canonical UX.
18. Fold в Objects остаётся read-only OOF provenance с tooltip; точные Result backend/public contracts определяются отдельно Architect и не выводятся из PNG.
19. Профессиональный принцип AXION: скрывать сложность можно, удалять реально поддерживаемую аналитическую возможность — нельзя; advanced controls допустимо убирать на второй уровень UI.
