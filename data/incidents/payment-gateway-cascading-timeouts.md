# INC-0055: Payment Gateway Cascading Timeout Failures

**Affected Service:** payment-service, order-service  
**Severity:** P1  
**Date:** 2024-12-03  
**Duration:** 1 hour 12 minutes (09:05 – 10:17 UTC)  
**Author:** Payments Engineering

---

## Symptoms

- `payment-service` began throwing `ReadTimeoutError` on calls to the external Stripe gateway at 09:05 UTC.
- `order-service`, which calls `payment-service` synchronously, accumulated blocked threads waiting for payment confirmation.
- `order-service` thread pool exhausted within 6 minutes, causing all endpoints (including non-payment ones like `GET /orders/{id}`) to return 503.
- End users saw checkout failures and "Something went wrong" on the order status page.
- Stripe status page showed a degradation event on their EU-West region starting at 08:58 UTC.

## Root Cause

Stripe experienced a partial outage in `eu-west-1` affecting payment intent creation. Their API was accepting requests but responding in 55–90 seconds instead of the normal <2 seconds.

`payment-service` had a hardcoded `timeout=60s` on the Stripe HTTP client. This meant each in-flight payment attempt held an active thread for up to 60 seconds before failing.

At peak checkout volume (~150 req/min), this produced ~150 stuck threads within one minute. The `order-service` Tomcat thread pool (default 200 threads) was exhausted completely, taking down all order functionality — far beyond just payments.

The cascading failure was caused by two missing safeguards:
1. No **circuit breaker** on the Stripe client — once the timeout pattern was established, the system kept sending requests into the degraded upstream.
2. No **bulkhead** separating payment threads from order-read threads — a payment failure starved the entire `order-service`.

## Resolution Steps

1. **Immediate mitigation (t+14 min):** Reduced Stripe HTTP timeout from 60s to 5s via environment variable override and redeployed `payment-service`. This freed threads quickly as requests failed fast.
2. **Bulkhead mitigation (t+28 min):** Separated payment processing into a dedicated `CompletableFuture` thread pool (50 threads) isolated from the main request threads.
3. **Stripe recovered (t+72 min):** Stripe resolved their outage at 10:10 UTC; `payment-service` error rate returned to baseline.
4. **Post-incident:** Enabled fallback to `eu-central-1` Stripe endpoint for payment intents.

## Prevention

- Implement Resilience4j `CircuitBreaker` on all external payment gateway calls; open after 5 consecutive timeouts in 30s.
- Add a `Bulkhead` annotation limiting concurrent payment calls to 30, queued to 10, with a fallback that returns `PAYMENT_PENDING` and retries async.
- Reduce all external HTTP client timeouts to `connectTimeout=2s`, `readTimeout=10s`.
- Subscribe to Stripe status page webhooks and automatically enable a graceful degradation mode (queue payments for async retry) when degradation is detected.
