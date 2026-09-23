# Dola integration authorization request — unsent draft

Status: **UNSENT / PERMISSION NOT GRANTED** (2026-09-23). This draft is for the
Owner to review and send from their own account if they want automated Dola
generation in Story Auto. It contains no cookie, key, account identifier, or
private video content. Sending it is a separate Owner action.

The [published Dola Terms](https://www.dola.com/legal/terms/en), last updated
2026-09-04, raise questions about automated use, reverse engineering,
incorporation into another product, and programmatic output extraction.
This record does not make a legal determination or treat Owner approval as
Dola's permission. No official Dola video API or written exception is recorded.

## Email draft

To: feedback@dola.com
Subject: Request for authorized video-generation integration for a personal local tool

Hello Dola team,

I use Dola and am building Story Auto, a local tool for my own video projects.
I would like to request an approved way for the tool to submit an explicitly
requested short text-to-video job, check its status, and save the resulting
video to my computer. The tool would use only my account, respect published
quotas and billing, avoid account rotation, and never automatically retry an
uncertain submission.

Could you please clarify:

1. Is there an official or partner API for this workflow? If so, where can I
   find its documentation, access terms, authentication method, and pricing?
2. If no API is available, would you expressly permit this local tool to use
   my signed-in web session/cookies for the same bounded workflow, including
   programmatic retrieval of my own generated output? Please specify any
   limits or conditions in writing.
3. How can I reconcile a request whose network response was lost, so that I
   can check whether a job or charge was created without submitting it again?
4. Are there restrictions on importing a resulting clip into my own locally
   rendered video, or on using the tool for personal versus commercial work?

I will not enable an automated production integration until the permitted
route and its conditions are clear. Thank you.

## Decision after a reply

- Official API or explicit written permission: record the exact allowed scope,
  account, quotas, billing, output rights, and reconciliation mechanism before
  designing a new bounded live acceptance test. Do not assume existing cookie
  transport is covered unless the reply says so.
- Disallowed or no reply: keep Dola automated generation on HOLD. A manual
  Dola-to-local-import path is a separate product-scope decision for the Owner;
  it must not be silently substituted for cookie automation or called accepted.
- Any reply about the uncertain 2026-09-23 attempt must be reconciled against
  its sealed local journal before another Dola generation is considered.
