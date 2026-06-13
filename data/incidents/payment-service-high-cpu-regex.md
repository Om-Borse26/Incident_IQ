# INC-0100: Payment Service High CPU Utilization
**Service:** payment-service

## Symptoms
- CPU utilization spiked to 99% on all payment-service pods.
- Latency increased from 50ms to 5000ms.
- Alerts fired for `HighCpuUsage`.

## Root Cause
A recent deployment introduced a complex regular expression for validating international transaction notes. The regex suffered from catastrophic backtracking when processing edge-case inputs.

## Resolution Steps
1. Reverted the regex to a simpler, non-backtracking version.
2. Added input length validation before applying regex.
3. Scaled up the pods temporarily to process the backlog.
