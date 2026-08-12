# ADR-002 — One pipeline, two render modes

**Status:** Accepted

`hybrid_hook` and `full_video_ai` differ at media policy/resolution, not by separate timelines or composers. Both converge on normalized silent MP4 scene clips and one final compositor.
