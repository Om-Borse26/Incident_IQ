# INC-0067-B: Redis Memory Exhaustion in Auth Service

**Service Impacted:** user-auth-service  
**Urgency:** P1  
**Incident Date:** 2025-01-19  
**Downtime:** roughly 25 minutes  
**Written By:** Identity Platform 

---

## What Happened (Symptoms)

- Around 03:41 UTC, all session-validation and login requests started failing with 500 Internal Server Error.
- The logs for `user-auth-service` were completely filled with errors stating: `MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk. Commands that may modify the data set are disabled.`
- Downstream services attempting to validate JWTs got 401 Unauthorized. This caused a massive wave of users getting logged out.
- Over 40,000 active sessions were unexpectedly terminated.
- Metrics indicated that Redis hit 100% of its 2GB memory limit.

## Why It Happened (Root Cause)

The primary Redis node for sessions (`auth-redis-prod`) ran out of memory. Because it was set to `noeviction` policy, it simply stopped accepting any new write operations (such as `SET` or `EXPIRE`) when it hit the 2GB ceiling.

This issue stemmed from a bad code deployment the night before at 23:00 UTC. A new "remember me" functionality was introduced, but the engineers forgot to set a TTL (Time to Live) on the tokens. Therefore, the tokens just sat in memory forever. Over the course of almost 5 hours, this mistake consumed around 680 MB of memory, maxing out the Redis server.

To make matters worse, because memory was entirely full, the Redis RDB background save failed during an AOF rewrite, which is what actually triggered the `MISCONF` lockdown on writes.

## How We Fixed It (Resolution)

1. **Quick fix:** We SSH'd into the Redis box, used `redis-cli`, and executed `CONFIG SET maxmemory-policy allkeys-lru`. This immediately let Redis delete old keys to make room for new ones, which brought the auth service back online. 
2. **Cleaning up:** We found the keys using the pattern `remember_me:*` and deleted about 2 million leaked keys using a non-blocking Lua script.
3. **Restoration:** By minute 23, the auth service was fully stable at a 0% error rate. 
4. **Permanent patch:** Six hours later, we pushed a hotfix to the code that properly adds an `EXPIRE 30d` to the remember-me tokens.

## Next Steps (Prevention)

- Make sure `allkeys-lru` is the standard eviction policy for all our session caching databases.
- We need alerts to fire when Redis memory hits 70% and 85%, instead of just waiting until it hits 95%.
- Update CI/CD pipelines with an integration test that checks if `SET` commands are always followed by an `EXPIRE` command.
- Create a security ticket (SEC-441) to audit the rest of the auth codebase for missing TTLs.
- Temporarily upgrade the Redis box to 4GB of RAM just to be safe while the patch settles.
