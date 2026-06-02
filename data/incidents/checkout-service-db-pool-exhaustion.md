# INC-0041: Checkout Service 500s from DB Connection Pool Exhaustion

**Affected Service:** checkout-service  
**Severity:** P1  
**Date:** 2024-11-14  
**Duration:** 47 minutes (14:23 – 15:10 UTC)  
**Author:** Platform Engineering

---

## Symptoms

- `checkout-service` began returning HTTP 500 errors to 68% of requests at 14:23 UTC.
- Error message in logs: `HikariPool-1 - Connection is not available, request timed out after 30000ms`.
- Latency on `POST /orders` spiked from p99=120ms to p99=28s within 3 minutes.
- Downstream `payment-service` reported elevated error rates due to missing order confirmations.
- Alerting fired on: `checkout_http_5xx_rate > 5%` and `checkout_db_pool_wait_ms > 5000`.

## Root Cause

A Black Friday promotional campaign launched at 14:20 UTC, increasing order throughput by 4.2x (baseline: ~800 req/min → peak: ~3,360 req/min).

The HikariCP connection pool for the `orders` PostgreSQL database was configured with `maximumPoolSize=20`, which was sized for 1,200 req/min. Each order creation held a connection for ~85ms on average, meaning the pool could theoretically sustain ~235 req/s. The spike far exceeded this ceiling.

Connections queued up, exhausted the 30-second timeout, and threads began throwing `SQLTransientConnectionException`, which the service mapped to a generic 500.

A secondary factor: a long-running analytics query from the reporting service was holding 3 connections for >10 minutes (a missing index caused a full table scan on `orders`). This reduced effective pool capacity from 20 to 17 during the incident.

## Resolution Steps

1. **Immediate mitigation (t+8 min):** Restarted `reporting-service` to kill the long-running analytics connections, freeing 3 pool slots. Error rate dropped to ~40%.
2. **Short-term fix (t+19 min):** Applied a live config change via Kubernetes ConfigMap to increase `HIKARI_MAX_POOL_SIZE` from 20 to 60 and rolled the deployment. Error rate dropped to <1%.
3. **RDS scaling (t+31 min):** Scaled the PostgreSQL RDS instance from `db.r6g.large` (2 vCPU) to `db.r6g.xlarge` (4 vCPU) to handle the additional connections without CPU saturation.
4. **Validate:** Confirmed `checkout_db_pool_wait_ms` returned to <5ms and error rate to <0.1% by 15:10 UTC.

## Prevention

- Add a missing index on `orders.created_at` for the reporting query (ticket: ENG-2204).
- Pre-scale DB pool size 2 hours before known traffic events using the launch calendar.
- Implement a read-replica for analytics queries to isolate OLAP traffic from OLTP.
- Set `connectionTimeout` to 3s (not 30s) and surface a proper 503 + retry-after header to callers instead of a misleading 500.
