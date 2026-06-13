# INC-0101: Payment Service Memory Leak and OOM
**Service:** payment-service

## Symptoms
- Pods are continuously crashing with OutOfMemory (OOM) errors.
- Gradual memory increase over 4 hours before crash.
- High number of open database connections.

## Root Cause
The transaction logger module was opening a new database connection for every transaction but failing to close it if the transaction failed validation, leading to connection exhaustion and memory leaks.

## Resolution Steps
1. Implemented a robust connection pool (HikariCP).
2. Wrapped database calls in `try-with-resources` to ensure connections are always closed.
3. Restarted all pods to clear memory.
