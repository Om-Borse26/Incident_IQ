# INC-0105: Inventory Service Database Deadlocks
**Service:** inventory-service

## Symptoms
- Service completely unresponsive.
- Database showing hundreds of active locks.
- Order creation failing.

## Root Cause
Concurrent updates to the same inventory SKU rows caused database deadlocks. The application did not have retry logic for `DeadlockFound` exceptions.

## Resolution Steps
1. Sorted items by SKU ID before acquiring locks to prevent circular waits.
2. Added application-level retry logic for transient database exceptions.
