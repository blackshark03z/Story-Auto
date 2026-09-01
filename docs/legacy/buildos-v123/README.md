# Build OS v1.23 legacy provenance

`authority.json` and `policy.json` are historical Story Auto Build OS v1.23
binding and policy evidence. They are retained byte-for-byte for provenance;
they are not current execution authority.

No `.buildos` lifecycle state was migrated during the Simplified Build OS
transition. `.buildos/control`, receipts, generations, and Git common-directory
continuity records remain untouched provenance.

Simplified Build OS does not consume either legacy authority file. Normal Story
Auto development remains native Git, editor, and test work unless an explicitly
requested consequential boundary calls for a guardrail.
