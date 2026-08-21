# Goal 35 — Windows project-lock liveness safety

## Product / Platform / Recovery case study

- Confirmed defect: `BLOCK_SOURCE_DEFECT_WINDOWS_PROJECT_LOCK_LIVENESS_PROBE_IS_UNSAFE_AND_FAILS_STALE_RECOVERY`.
- Symptom: a stale project lock blocked Trial A production before the provider boundary.
- Root cause: the lock code assumed POSIX `os.kill(pid, 0)` liveness semantics on Windows.

The observed production lock referenced nonexistent PID `21136`.  On Windows,
the POSIX-style liveness call raised `WinError 87` (`ERROR_INVALID_PARAMETER`),
so the stale lock recovery path failed before it could decide whether takeover
was safe.  Python's Windows `os.kill` semantics are also unsafe for probing:
non-console-control signals can terminate the target process rather than
performing a harmless existence check.

Goal 35 replaces that Windows path with read-only Win32 process-query APIs.
`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` and `GetExitCodeProcess`
identify a definitely dead owner; every acquired handle is closed.  Access
denied and every unknown probe failure are conservatively treated as alive.
The corrected invariant is: **platform-specific liveness probes must be
non-destructive and platform-native; unknown liveness is not dead.**

The existing lock policy is unchanged.  Normal stale-lock takeover requires
the same hostname, an age at or beyond `stale_after_seconds`, and an owner
proved dead.  A live owner, a fresh dead-owner lock, a foreign-host lock, and
an indeterminate Windows probe remain authoritative and block acquisition.

The missing regression had covered only a negative PID.  Goal 35 adds the
positive nonexistent PID `21136` reproduction in an isolated temporary
runtime: the Windows probe reports dead, `_stale()` reports true, and normal
`ProjectLock.acquire()` recovers the isolated lock.  It never touches the
actual Trial A lock.

## Revision 2 R3 delta

The first revision covered exceptions and unknown probe paths, but omitted one
distinct branch: successful `OpenProcess` followed by a failed
`GetExitCodeProcess`.  The native wrapper represents that failed exit-code
query as `None`; revision 1 compared it with `STILL_ACTIVE`, accidentally
classifying the indeterminate result as dead.  Revision 2 treats `None` as
alive, closes the already-opened handle, and proves that even an old same-host
lock is not stolen while owner liveness is indeterminate.

Bounded workflow lesson: R3 for small deterministic fixes should prioritize
invariant-complete branch coverage and delta review, without multiplying
lifecycle ceremony after the bounded defect is understood.

Trial A safety was preserved: `req_4b8dba2869afe1e12a52` remained PENDING with
zero attempts and zero provider submissions.  No Flow or provider action was
taken.

Post-shipping Build OS synthesis only: “platform-specific side-effect
primitives require semantic verification; API name similarity across operating
systems is not behavioral equivalence.”
