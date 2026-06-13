# INC-0104: Notification Service High CPU on XML Parsing
**Service:** notification-service

## Symptoms
- CPU utilization spiked to 95%.
- Message queue backlog increasing.
- Delays in sending SMS notifications.

## Root Cause
A partner started sending extremely large (50MB) XML payloads for bulk notifications. The DOM parser loaded the entire XML into memory, causing high CPU and garbage collection pauses.

## Resolution Steps
1. Switched from a DOM parser to a streaming SAX parser.
2. Implemented a maximum payload size limit of 5MB at the API gateway.
