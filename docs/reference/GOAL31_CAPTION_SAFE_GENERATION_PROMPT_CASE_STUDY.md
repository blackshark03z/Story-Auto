# Goal31: Caption-safe generation prompt remediation

Classification: PRODUCT / SPEC-CONSISTENCY

The Ambient Story generation specification previously requested negative space
for readable subtitles while mandatory production QC rejected burned-in subtitle
or caption text. This was a deterministic specification contradiction, not
provider variance.

Current visual prompt construction preserves uncluttered visual breathing room
and explicitly prohibits editorial subtitles, captions, lower thirds, title
cards, placeholder typography, UI overlays, and editorial text. It deliberately
does not prohibit naturally occurring story objects such as signs or books.

Historical requests remain immutable. A QC replacement now derives its fresh
effective prompt from the stored visual semantic brief through the current
caption-safe compiler, records the historical and effective prompt hashes, and
stores the receipt in the replacement transaction. Replays continue to preserve
the prompt of their immediate canonical request.

Post-shipping synthesis: DESIGN ASSURANCE should cross-check the GENERATION SPEC
against the QC ACCEPTANCE SPEC for contradictory requirements before provider
execution.
