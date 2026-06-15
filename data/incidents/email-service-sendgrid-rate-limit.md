# INC-0112: Email Service SendGrid Rate Limit
**Service:** email-service
**Severity:** P2
**Date:** 2025-01-14

## Symptoms
- `email-service` began throwing `HTTP 429 Too Many Requests` when calling the SendGrid API.
- Customer password reset emails and order confirmation emails were silently dropped.
- The `email-service` dead letter queue (DLQ) spiked to over 10,000 messages within 15 minutes.
- User complaints about missing sign-up emails increased on support channels.

## Root Cause
A new marketing campaign sent out 500,000 promotional emails at once. The marketing service used the same shared SendGrid API key as the transactional `email-service`. The massive volume of marketing emails hit the SendGrid account-level rate limit (10,000 requests/second), causing all subsequent requests, including critical transactional emails, to be rejected with a 429 status code.

## Resolution Steps
1. Paused the marketing campaign to stop the flood of promotional emails.
2. Re-processed the DLQ to send the dropped password reset and order confirmation emails.
3. Created a separate SendGrid API key with its own isolated rate limits for the marketing service.
4. Implemented an exponential backoff retry mechanism in `email-service` for 429 responses.
