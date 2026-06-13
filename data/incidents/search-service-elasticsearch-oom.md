# INC-0107: Search Service Elasticsearch OOM
**Service:** search-service

## Symptoms
- Search queries returning 500 errors.
- Elasticsearch nodes dropping out of the cluster.
- JVM Heap usage at 100%.

## Root Cause
A user executed a massive wildcard query (`*a*b*c*`) that expanded to millions of terms, exhausting the JVM heap and crashing the node.

## Resolution Steps
1. Disabled leading wildcards in search queries.
2. Implemented a timeout of 5 seconds on all Elasticsearch queries.
3. Increased JVM heap size for data nodes.
