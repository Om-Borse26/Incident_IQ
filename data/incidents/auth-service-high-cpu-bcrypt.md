# INC-0102: Auth Service High CPU and Timeouts
**Service:** auth-service

## Symptoms
- CPU utilization at 100%.
- Login requests timing out after 30 seconds.
- Intermittent 502 Bad Gateway errors.

## Root Cause
A security patch mistakenly increased the bcrypt work factor from 10 to 14, causing password hashing to take significantly longer and exhaust CPU resources.

## Resolution Steps
1. Reverted the bcrypt work factor back to 10.
2. Invalidated active sessions to force a smooth re-login curve.
