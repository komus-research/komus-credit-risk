# Model Research Coverage & Exclusion Register V1

## Purpose

Реестр отделяет quality evidence, compute/hardware exclusions и candidates, не открытые после stopping rule. Ключевое правило: **«не запускали» != «модель плохая»**.

## Status taxonomy

`TESTED_FULL_PROTOCOL`, `TECHNICALLY_VALIDATED_BUT_NOT_FULL_OOF`, `STOPPED_BY_COMPUTE_COST`, `REJECTED_BY_HARDWARE_CONSTRAINT`, `NOT_OPENED_AFTER_STOPPING_RULE`, `SCREENED_COMPUTE_RISK`. Без полного accepted KOMUS OOF quality остаётся `UNKNOWN`.

## Tested coverage

Stage 1: XGBoost (Gini 0.803990), CatBoost (0.803780), LightGBM (0.803363). Stage 6 TabM standalone (0.781310, `inferior`); Stage 7 TabM stacking (0.804260, `no_material_benefit`); Stage 8 FT-Transformer (0.801528, `no_material_benefit`); Stage 11 RealMLP (0.793325, `inferior`). Saved `GBDT_mean` comparator: **0.8063993952**. Stage 9 rank complementarity и Stage 10 oracle/residual reserve — coverage diagnostics, не отдельные classifiers.

## Compute / hardware exclusions

- Google TabFM: `STOPPED_BY_COMPUTE_COST`, quality `UNKNOWN`; technical SAFE-RUN и real inference прошли, full OOF не выполнен из-за compute cost.
- TabPFN-3 large-context: historical `TABPFN3_STAGE14_REJECTED_BY_CPU_CONSTRAINT`, registry `REJECTED_BY_HARDWARE_CONSTRAINT`, quality `UNKNOWN`; process lesson — `LATE_COMPUTE_FEASIBILITY_GATE`.
- xRFM V1: historical `STOPPED_BY_COMPUTE_COST / HARDWARE_CONSTRAINT`, registry `REJECTED_BY_HARDWARE_CONSTRAINT`, quality `UNKNOWN`; environment PASS, implementation ACCEPT, guard остановил до fit на 6 cores / 15.34 GiB при contract 8 cores / 32 GiB. Process lesson — `HARDWARE_CONTRACT_ORDERING_FAILURE`.

## Modern approaches not run

Defence-oriented shortlist: TabICLv2, TabDPT/TabDPT-Turbo (оба `SCREENED_COMPUTE_RISK`); TabR, ModernNCA, SAINT, NODE, TabTransformer (все `NOT_OPENED_AFTER_STOPPING_RULE`). У каждого quality unknown, full OOF false, KOMUS Gini/decision отсутствуют и final test false. Canonical primary sources приведены в CSV registry; они не являются KOMUS quality evidence.

## Future gate

`FEASIBILITY_BEFORE_EXPERIMENT_LOCK` обязателен. До нового Experiment Lock проверяются novelty, actual hardware, primary-source mechanics, full-protocol feasibility и отсутствие скрытого изменения hypothesis. При unresolved feasibility используется `SCREENED_COMPUTE_RISK`; minimal pre-lock probe допустим только для получения compute evidence.
