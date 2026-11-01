# AXION — Demo Home V1

## Purpose

A **read-only** filled Home page for screenshots and presentations.
The real Home page and all analysis, modelling, reporting and persistence flows are unchanged.

## Open

Start the existing Vite frontend as usual (for example, `npm run dev -- --host 127.0.0.1` in `frontend`).

- **Demo home:** http://127.0.0.1:5173/?demo=1#/home
- **Live home:** http://127.0.0.1:5173/#/home

The demo Home page works **without a backend**. No ML pipeline is started and no fake projects/models are written into application storage.

Use the **«Рабочая версия»** button to leave the demo. Sidebar links to other sections also leave demo mode; the «Новый анализ» sidebar entry safely opens the ordinary Home rather than starting an analysis from the demo. The three Quick Start cards and sample project/model rows are visual examples, not interactive entries.

## Fixture

`frontend/src/pages/demoHomeFixture.ts` contains all fictional values and typed project/model rows. Dates, process progress, metrics, statuses and identifiers are **examples**. A visible label and footer explain this.

Data shown: 12 projects, 8 saved models, 3 in progress, 7 completed; one CatBoost training example (Retail 2026, Fold 3/5, 60%); one categorical-data alert; four sample projects and three sample saved models.

- Demo ROC-AUC and Gini are mathematically consistent (Gini = 2 × ROC-AUC − 1).
- Demo model metrics are **not** attributed to real AXION evaluations.
- No fake API responses, no writes to a real database, and no changes in `.axion-artifacts`.

## Implementation

- `frontend/src/pages/HomePageDemo.tsx`: separate read-only view
- `frontend/src/pages/demoHomeFixture.ts`: typed demo fixture
- `frontend/src/pages/demoHome.css`: scoped styling that reuses existing dashboard components
- `frontend/src/App.tsx`: explicit query-param switch; prevents live session/settings requests while on demo Home

The default `HomePage.tsx` was not modified.

## Design references

1. Earlier filled home screen (content only);
2. Current empty React Home (approved layout and visual system);
3. Current Result Model (model/metric context only);
4. Current Threshold Exploration screen (context only).

No images from the reference screenshots are hardcoded into the app.

## Acceptance

- Run `npm run build` in `frontend`.
- Open the demo URL and verify all cards/tables, label, and static progress.
- Open the live URL and verify Home still consumes actual backend API.
- Clicking «Рабочая версия» should remove the demo parameter.
- No project/model in the demo should open a real record or start training.
- See full-page image: `docs/demo/axion-demo-home-v1.png`.

## Publishing limitation

This branch is solely a **portfolio demo**. Do not merge or deploy as a production change without the owner's approval and review.
