import os

docs = [
    {
        "filename": "payment-service-high-cpu-regex.md",
        "title": "INC-0100: Payment Service High CPU Utilization",
        "service": "payment-service",
        "symptoms": "- CPU utilization spiked to 99% on all payment-service pods.\n- Latency increased from 50ms to 5000ms.\n- Alerts fired for `HighCpuUsage`.",
        "cause": "A recent deployment introduced a complex regular expression for validating international transaction notes. The regex suffered from catastrophic backtracking when processing edge-case inputs.",
        "fix": "1. Reverted the regex to a simpler, non-backtracking version.\n2. Added input length validation before applying regex.\n3. Scaled up the pods temporarily to process the backlog."
    },
    {
        "filename": "payment-service-memory-leak-db.md",
        "title": "INC-0101: Payment Service Memory Leak and OOM",
        "service": "payment-service",
        "symptoms": "- Pods are continuously crashing with OutOfMemory (OOM) errors.\n- Gradual memory increase over 4 hours before crash.\n- High number of open database connections.",
        "cause": "The transaction logger module was opening a new database connection for every transaction but failing to close it if the transaction failed validation, leading to connection exhaustion and memory leaks.",
        "fix": "1. Implemented a robust connection pool (HikariCP).\n2. Wrapped database calls in `try-with-resources` to ensure connections are always closed.\n3. Restarted all pods to clear memory."
    },
    {
        "filename": "auth-service-high-cpu-bcrypt.md",
        "title": "INC-0102: Auth Service High CPU and Timeouts",
        "service": "auth-service",
        "symptoms": "- CPU utilization at 100%.\n- Login requests timing out after 30 seconds.\n- Intermittent 502 Bad Gateway errors.",
        "cause": "A security patch mistakenly increased the bcrypt work factor from 10 to 14, causing password hashing to take significantly longer and exhaust CPU resources.",
        "fix": "1. Reverted the bcrypt work factor back to 10.\n2. Invalidated active sessions to force a smooth re-login curve."
    },
    {
        "filename": "payment-service-gateway-timeout.md",
        "title": "INC-0103: Payment Service Third-Party Gateway Timeouts",
        "service": "payment-service",
        "symptoms": "- Transactions failing with 'Gateway Timeout'.\n- Elevated error rates on external API calls.\n- No high CPU or memory issues observed.",
        "cause": "The external payment gateway provider (Stripe) rate-limited our main NAT gateway IP due to a sudden spike in retry requests from a bug in the mobile app.",
        "fix": "1. Implemented exponential backoff with jitter on all external API calls.\n2. Contacted the gateway provider to temporarily lift the rate limit.\n3. Pushed a hotfix to the mobile app to stop aggressive retries."
    },
    {
        "filename": "notification-service-high-cpu-xml.md",
        "title": "INC-0104: Notification Service High CPU on XML Parsing",
        "service": "notification-service",
        "symptoms": "- CPU utilization spiked to 95%.\n- Message queue backlog increasing.\n- Delays in sending SMS notifications.",
        "cause": "A partner started sending extremely large (50MB) XML payloads for bulk notifications. The DOM parser loaded the entire XML into memory, causing high CPU and garbage collection pauses.",
        "fix": "1. Switched from a DOM parser to a streaming SAX parser.\n2. Implemented a maximum payload size limit of 5MB at the API gateway."
    },
    {
        "filename": "inventory-service-db-lock.md",
        "title": "INC-0105: Inventory Service Database Deadlocks",
        "service": "inventory-service",
        "symptoms": "- Service completely unresponsive.\n- Database showing hundreds of active locks.\n- Order creation failing.",
        "cause": "Concurrent updates to the same inventory SKU rows caused database deadlocks. The application did not have retry logic for `DeadlockFound` exceptions.",
        "fix": "1. Sorted items by SKU ID before acquiring locks to prevent circular waits.\n2. Added application-level retry logic for transient database exceptions."
    },
    {
        "filename": "user-profile-service-redis-eviction.md",
        "title": "INC-0106: User Profile Service High Latency",
        "service": "user-profile-service",
        "symptoms": "- Latency spiked to 2000ms.\n- Redis cache hit rate dropped from 99% to 40%.\n- Increased load on the primary database.",
        "cause": "A new feature cached large user history blobs without a TTL, causing Redis to reach its `maxmemory` limit and aggressively evict frequently used profile keys (allkeys-lru).",
        "fix": "1. Added a strict 1-hour TTL to user history blobs.\n2. Scaled Redis cluster memory from 2GB to 4GB.\n3. Flushed the cache to clear stale data."
    },
    {
        "filename": "search-service-elasticsearch-oom.md",
        "title": "INC-0107: Search Service Elasticsearch OOM",
        "service": "search-service",
        "symptoms": "- Search queries returning 500 errors.\n- Elasticsearch nodes dropping out of the cluster.\n- JVM Heap usage at 100%.",
        "cause": "A user executed a massive wildcard query (`*a*b*c*`) that expanded to millions of terms, exhausting the JVM heap and crashing the node.",
        "fix": "1. Disabled leading wildcards in search queries.\n2. Implemented a timeout of 5 seconds on all Elasticsearch queries.\n3. Increased JVM heap size for data nodes."
    },
    {
        "filename": "payment-service-kafka-lag.md",
        "title": "INC-0108: Payment Service Kafka Consumer Lag",
        "service": "payment-service",
        "symptoms": "- Receipts are being sent 2 hours late.\n- Kafka consumer lag for topic `payment-completed` exceeded 100,000.\n- CPU and memory are normal.",
        "cause": "A single malformed message in partition 3 caused the consumer to throw a `DeserializationException` in a continuous loop, blocking progress for the entire partition.",
        "fix": "1. Configured the consumer to log and skip un-deserializable messages instead of crashing.\n2. Manually advanced the consumer offset for partition 3 to bypass the poison pill."
    },
    {
        "filename": "frontend-app-memory-leak.md",
        "title": "INC-0109: Frontend App Browser Memory Leak",
        "service": "frontend-app",
        "symptoms": "- Users reporting the web app freezes after 30 minutes of use.\n- Browser tab memory usage exceeds 2GB.",
        "cause": "A charting library was retaining event listeners on DOM elements that were destroyed during React re-renders, causing a detached DOM node memory leak.",
        "fix": "1. Updated the charting library component to properly unbind event listeners in the `useEffect` cleanup function.\n2. Added automated memory leak tests using Puppeteer."
    }
]

os.makedirs("data/incidents", exist_ok=True)

for doc in docs:
    filepath = os.path.join("data/incidents", doc["filename"])
    content = f"""# {doc['title']}
**Service:** {doc['service']}

## Symptoms
{doc['symptoms']}

## Root Cause
{doc['cause']}

## Resolution Steps
{doc['fix']}
"""
    with open(filepath, "w") as f:
        f.write(content)

print(f"Successfully generated {len(docs)} incident documents.")
