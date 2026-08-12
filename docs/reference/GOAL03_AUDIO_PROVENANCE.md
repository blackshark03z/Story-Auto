# Goal 03 Audio Provenance

The Story Auto audio adapters were independently implemented using the extraction
audit's source snapshot `d0c86c8e0258b7c2f3d59469e2b00a951025207e` as reference.

- ElevenLabs: deterministic source-preserving chunk planning, classified
  post-dispatch ambiguity, bounded key rotation, and offset alignment merging.
- Typecast: character timestamps mapped to deterministic sentence spans.
- Credentials: Story Auto reads provider-specific environment variables only;
  values are never written to project artifacts, checkpoints, or diagnostics.

There are no `yt_auto` or YouTube Auto runtime imports in this product.
