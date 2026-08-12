# Migrations

V1 starts greenfield. Artifact schemas are versioned from the first implementation.

Migration principles:

- never reinterpret old bytes silently;
- validate source schema before migration;
- migration is explicit and deterministic;
- preserve original artifact or a verifiable backup before destructive rewrite;
- generated asset hashes/provenance remain stable across metadata migrations;
- major incompatible contract changes create a new schema version and migration path.

No migration code exists at the design baseline.
