# INC-0108: Payment Service Kafka Consumer Lag
**Service:** payment-service

## Symptoms
- Receipts are being sent 2 hours late.
- Kafka consumer lag for topic `payment-completed` exceeded 100,000.
- CPU and memory are normal.

## Root Cause
A single malformed message in partition 3 caused the consumer to throw a `DeserializationException` in a continuous loop, blocking progress for the entire partition.

## Resolution Steps
1. Configured the consumer to log and skip un-deserializable messages instead of crashing.
2. Manually advanced the consumer offset for partition 3 to bypass the poison pill.
