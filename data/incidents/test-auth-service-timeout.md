# INC-0068: Auth Service Login Failures due to 3rd-Party Rate Limits

**Affected Service:** user-auth-service
**Severity:** P2
**Date:** 2026-07-21
**Duration:** 15 minutes (09:00 – 09:15 UTC)
**Author:** Identity Team

---

## Symptoms

- Users reported seeing "Login service unavailable" when trying to sign in.
- `user-auth-service` logs showed continuous HTTP 429 Too Many Requests errors from the external OAuth provider (Auth0).
- Login success rate dropped from 99.8% to 12%.
- Existing sessions were unaffected, but no new tokens could be issued.

## Root Cause

A marketing campaign launched at 09:00 UTC caused an unexpected 10x spike in login attempts. The `user-auth-service` forwards all authentication requests directly to Auth0 without any local rate limiting or throttling. This caused the Auth0 tenant to hit its hard limit of 1000 requests per minute, triggering HTTP 429 responses. 
Because the application code didn't implement exponential backoff on these requests, the retries further compounded the issue.

## Resolution Steps

1. **Immediate mitigation:** The infrastructure team applied a temporary IP-based rate limit at the API Gateway level to shed traffic and allow the Auth0 quota to reset. (t+5 min)
2. **Configuration update:** Auth0 support was contacted to temporarily double the rate limit quota for the tenant to handle the marketing campaign traffic. (t+12 min)
3. **Recovery:** The 429 errors subsided and the login success rate climbed back to 99.8%. (t+15 min)

## Prevention

- Implement an exponential backoff and jitter strategy for all external API calls in `user-auth-service`.
- Introduce an application-level circuit breaker to fail fast when Auth0 rate limits are breached, displaying a friendly message to the user rather than hanging.
- Coordinate with marketing to ensure engineering is aware of campaigns that may cause traffic spikes.
