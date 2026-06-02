# INC-0082: API Gateway Mass 502 Errors from Upstream Health Check Misconfiguration

**Affected Service:** api-gateway, product-catalog-service  
**Severity:** P2  
**Date:** 2025-02-27  
**Duration:** 34 minutes (16:12 – 16:46 UTC)  
**Author:** Platform Infrastructure

---

## Symptoms

- API gateway began returning HTTP 502 Bad Gateway to ~35% of requests at 16:12 UTC.
- Affected endpoints: `/api/v1/products/*`, `/api/v1/search/*` — all routes backed by `product-catalog-service`.
- `user-auth-service`, `checkout-service`, and `payment-service` routes unaffected.
- Gateway access logs showed upstream target group returning `connection refused` on port 8080.
- `product-catalog-service` pods were running and healthy per Kubernetes pod status.

## Root Cause

A routine Terraform apply at 16:09 UTC updated the ALB target group health check path from `/actuator/health` to `/health` as part of a platform-wide standardization. However, `product-catalog-service` had not yet migrated its health endpoint to `/health` — it still only exposed `/actuator/health`.

The ALB's health check interval was 30 seconds with a threshold of 2 consecutive failures. Within 60 seconds of the Terraform apply, all three `product-catalog-service` targets were marked **unhealthy** and deregistered from the target group. The gateway had no healthy upstream to route to, producing 502s.

The service itself was completely healthy — Kubernetes probes used `exec` commands (not HTTP) so the service continued running normally, unaware of the ALB health check failure.

## Resolution Steps

1. **Immediate mitigation (t+9 min):** Identified the misconfigured health check path via `aws elbv2 describe-target-health`. Applied a targeted Terraform override to revert the health check path back to `/actuator/health` for `product-catalog-service` only.
2. **Targets re-registered (t+22 min):** After two consecutive successful health checks (60s), targets re-registered; 502 rate dropped to 0%.
3. **Full recovery (t+34 min):** Confirmed sustained 0% error rate across all `/api/v1/products/*` endpoints.
4. **Follow-up:** `product-catalog-service` added `/health` endpoint mapping to `/actuator/health` (a simple alias) to support the new standard.

## Prevention

- Add a pre-flight check to the Terraform CI pipeline that validates ALB health check paths against running service endpoint inventory before applying.
- Enforce the `/health` standard in the service template repository; block new service scaffolding that doesn't include it.
- Create a canary health-check test in the smoke-test suite that verifies ALB target group health after every infrastructure deployment.
- Add a 5-minute grace period after Terraform applies before any automated load-balancer draining.
