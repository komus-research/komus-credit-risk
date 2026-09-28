# Pre-presentation ModelVersion V2 fixture

This frozen CatBoost ModelVersion V2 was generated from detached source commit
`cf0af5143c29a58afb67fa7c858ce15a8ed4c54a`, before the Parameter Presentation
implementation commit `da2828030f2f3b6c71f3c03e836ddef9f1c6c781`.

The fixture uses the existing `ModelVersionTests` synthetic dataset setup,
resolves the accepted CatBoost Advanced configuration with
`/estimator_params/depth = 6`, fits the trusted CatBoost factory, and saves
through that pre-change commit's `ModelVersionStore.save()` implementation.
The fixture was copied from the resulting persisted V2 directory without
rewriting metadata or regenerating its manifest using current code.

- ModelVersion ID: `2662c2c69ce8a9740582e75bb9bf0a04079d9dfb920779fbbff375a0bf939815`
- Configuration record ID: `84b5eacfa236f53faa61956069e277da4508c6ced4b9de3c8682c7a527c8195f`
- Files: `manifest.json`, `metadata.json`, `native/model.cbm`
