# INC-0094: Notification Service Queue Backlog from Dead-Letter Queue Misconfiguration

**Affected Service:** notification-service  
**Severity:** P2  
**Date:** 2025-03-11  
**Duration:** 2 hours 51 minutes (10:33 – 13:24 UTC)  
**Author:** Messaging Infrastructure

---

## Symptoms

- At 10:33 UTC, users stopped receiving order confirmation emails and push notifications.
- `notification-service` logs showed zero errors — the service appeared healthy.
- SQS queue depth for `notification-jobs-prod` began climbing at ~1,800 messages/minute.
- By 11:00 UTC the queue depth was 48,000 messages; by 13:00 UTC it was 218,000.
- Dashboards showed `notification_messages_consumed` metric flat at 0 for the affected period.
- All notification-service pods showed CPU < 5% and memory nominal — no signs of a crash.

## Root Cause

A deployment at 10:28 UTC introduced a new `EmailTemplateService` dependency via constructor injection. The dependency's bean initialisation failed silently: a missing Handlebars template file (`order_confirmation_v3.hbs`) caused the `ApplicationContext` to partially start — all beans unrelated to `EmailTemplateService` initialized correctly, including the health check endpoint.

The SQS consumer listener (`@SqsListener`) uses Spring's `SimpleMessageListenerContainer`, which starts only after full `ApplicationContext` refresh. Because the refresh never completed (no exception was thrown — the missing template caused a lazy-initialisation path), the listener never started. Messages accumulated in the queue unconsumed.

The service returned 200 on `/actuator/health` because the health check bean had already initialized before the failure point, masking the broken state entirely.

The dead-letter queue (DLQ) was not triggered because messages were never consumed, not consumed-and-failed — they simply sat in the main queue.

## Resolution Steps

1. **Root cause identified (t+41 min):** Noticed `notification_messages_consumed=0` despite healthy pods. SSH'd into a pod and checked `ApplicationContext` logs — found `Caused by: FileNotFoundException: order_confirmation_v3.hbs not found`.
2. **Immediate mitigation (t+58 min):** Rolled back the deployment to the previous image tag. Consumer listeners started within 30 seconds of rollback; queue depth began draining.
3. **Queue drain (t+58 min – t+171 min):** Scaled `notification-service` from 3 to 12 pods to drain the 218,000-message backlog. Drain rate: ~2,200 messages/minute. Backlog cleared by 13:24 UTC.
4. **Template file restored (same day):** Added missing `order_confirmation_v3.hbs` to the resource bundle and re-deployed successfully at 15:00 UTC.

## Prevention

- Add startup probe (not just liveness probe) that verifies `ApplicationContext` is fully refreshed and all listeners are active before marking the pod ready.
- Add an integration test that starts the Spring ApplicationContext in a test container and asserts the SQS listener is registered.
- Create a CloudWatch alarm on `notification_messages_consumed = 0 for 5 minutes when queue_depth > 100` to catch silent consumer failures earlier (estimated MTTD reduction: 41 min → <8 min).
- Review all `@Lazy` and partially-initialized beans for silent failure modes; enforce fail-fast startup with `spring.main.lazy-initialization=false`.
