# Goal 11 Flow image postprocessing evidence

This evidence uses 24 existing real Google Flow images from the accepted Goal 08
runtime corpus. No Flow generation or other provider call was made. The set was
deduplicated by decoded pixel hash and diversity-sampled, with the available
1280x720 image included explicitly alongside 23 1376x768 images.

Artifacts:

- `flow-image-postprocess-full-contact-sheet.jpg` — raw/clean pairs at normal
  full-frame viewing size.
- `flow-image-postprocess-crops-contact-sheet.jpg` — raw/clean bottom-right
  crops enlarged four times.
- `visual-evidence-manifest.json` — source paths and hashes, derivative hashes,
  dimensions, processor/profile versions, and mask hashes for all 24 samples.

The corpus includes bright and dark surfaces, flat painted walls, wood grain,
flooring, fabric/upholstery, high-frequency textures, and multiple object/edge
crossings through the repair region. Visual review found the sparkle absent in
all cleaned samples, dimensions preserved, no rectangular repair blocks, no
distracting normal-view scar, and no materially damaged scene structure. At
four-times crop, the expected small local interpolation is visible on some
crossing edges, which is why the existing bottom-right safe-area prompt policy
remains in force.

Visual result: PASS
