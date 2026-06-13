# INC-0109: Frontend App Browser Memory Leak
**Service:** frontend-app

## Symptoms
- Users reporting the web app freezes after 30 minutes of use.
- Browser tab memory usage exceeds 2GB.

## Root Cause
A charting library was retaining event listeners on DOM elements that were destroyed during React re-renders, causing a detached DOM node memory leak.

## Resolution Steps
1. Updated the charting library component to properly unbind event listeners in the `useEffect` cleanup function.
2. Added automated memory leak tests using Puppeteer.
