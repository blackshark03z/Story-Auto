# ADR-001 — Story Auto is a separate product

**Status:** Accepted

Story Auto is a new independent repository/runtime. YouTube Auto is a source of selectively ported primitives only. Story Auto never imports YouTube Auto modules at runtime.

Reason: avoid inheriting timeline/composer/UI/schema debt and allow media-first architecture from day one.
