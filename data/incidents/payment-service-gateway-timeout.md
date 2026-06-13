# INC-0103: Payment Service Third-Party Gateway Timeouts
**Service:** payment-service

## Symptoms
- Transactions failing with 'Gateway Timeout'.
- Elevated error rates on external API calls.
- No high CPU or memory issues observed.

## Root Cause
The external payment gateway provider (Stripe) rate-limited our main NAT gateway IP due to a sudden spike in retry requests from a bug in the mobile app.

## Resolution Steps
1. Implemented exponential backoff with jitter on all external API calls.
2. Contacted the gateway provider to temporarily lift the rate limit.
3. Pushed a hotfix to the mobile app to stop aggressive retries.
