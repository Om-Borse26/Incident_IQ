# INC-0106: User Profile Service High Latency
**Service:** user-profile-service

## Symptoms
- Latency spiked to 2000ms.
- Redis cache hit rate dropped from 99% to 40%.
- Increased load on the primary database.

## Root Cause
A new feature cached large user history blobs without a TTL, causing Redis to reach its `maxmemory` limit and aggressively evict frequently used profile keys (allkeys-lru).

## Resolution Steps
1. Added a strict 1-hour TTL to user history blobs.
2. Scaled Redis cluster memory from 2GB to 4GB.
3. Flushed the cache to clear stale data.
