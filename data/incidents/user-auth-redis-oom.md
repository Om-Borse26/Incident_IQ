# INC-0067: User Auth Service Outage from Redis Out-of-Memory

**Affected Service:** user-auth-service  
**Severity:** P1  
**Date:** 2025-01-19  
**Duration:** 23 minutes (03:41 – 04:04 UTC)  
**Author:** Identity Platform Team

---

## Symptoms

- All login and session-validation requests began returning HTTP 500 at 03:41 UTC.
- `user-auth-service` logs flooded with: `MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk. Commands that may modify the data set are disabled.`
- Any service calling `user-auth-service` to validate JWT tokens received 401 responses, triggering a mass user logout across the platform.
- Approximately 42,000 active sessions were invalidated.
- Redis memory usage showed 99.98% of `maxmemory=2gb` at time of incident.

## Root Cause

The Redis instance serving as the session store (`auth-redis-prod`) hit its 2 GB `maxmemory` limit. The configured eviction policy was `noeviction`, meaning Redis refused all write commands (including `SET`, `EXPIRE`) once memory was full.

The memory spike was caused by a session leak in a new feature deployed at 23:00 UTC the previous day: a "remember me" token was being stored with no TTL (missing `.expire()` call in the auth service), causing tokens to accumulate indefinitely. Over ~4.7 hours, these entries grew from 0 to ~680 MB, filling the remaining headroom in Redis.

Redis's RDB persistence also failed to snapshot because the AOF rewrite was running and the instance ran out of memory mid-snapshot, triggering the `MISCONF` error that blocked all writes.

## Resolution Steps

1. **Immediate mitigation (t+4 min):** Connected to Redis via `redis-cli` and ran `CONFIG SET maxmemory-policy allkeys-lru`. This allowed Redis to start evicting least-recently-used keys, freeing memory for writes. Auth service began recovering immediately.
2. **TTL cleanup (t+11 min):** Identified the keyspace pattern (`remember_me:*`) and ran `SCAN` with `DEL` to remove ~2.1M orphaned keys (via a Lua script to avoid blocking the event loop).
3. **Full recovery (t+23 min):** Auth service error rate returned to 0%. Users prompted to log in again due to session invalidation.
4. **Code fix deployed (t+6 hours):** Patched `remember-me` token creation to include `EXPIRE 30d`; deployed to production.

## Prevention

- Change Redis eviction policy from `noeviction` to `allkeys-lru` as the permanent default for session stores.
- Add Redis memory usage alert at 70% and 85% thresholds (previously only had a 95% alert).
- Add integration test asserting that every stored key has a TTL; fail CI if any `SET` is called without a subsequent `EXPIRE`.
- Audit all Redis `SET` calls in auth codebase for missing TTL (ticket: SEC-441).
- Increase Redis instance to 4 GB as a buffer while the root-cause fix is validated.
