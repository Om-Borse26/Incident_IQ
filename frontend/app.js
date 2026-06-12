// Dynamically detect API base URL based on environment
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8080' 
    : 'https://incidentiq-production-b6f3.up.railway.app';
// DOM Elements
const form = document.getElementById('incident-form');
const input = document.getElementById('query-input');
const btn = document.getElementById('analyze-btn');

const resultsContainer = document.getElementById('results-container');
const loadingState = document.getElementById('loading-spinner');
const contentState = document.getElementById('result-content');
const errorState = document.getElementById('error-message');
const errorText = document.getElementById('error-text');

// Content DOM
const confFill = document.getElementById('confidence-fill');
const confVal = document.getElementById('confidence-val');
const statusTag = document.getElementById('status-tag');
const answerText = document.getElementById('answer-text');
const reasoningText = document.getElementById('reasoning-text');
const fixesList = document.getElementById('fixes-list');
const sourcesTags = document.getElementById('sources-tags');
const approvalBox = document.getElementById('approval-box');

// Upload DOM
const openUploadBtn = document.getElementById('open-upload-btn');
const closeUploadBtn = document.getElementById('close-upload-btn');
const uploadModal = document.getElementById('upload-modal');
const uploadForm = document.getElementById('upload-form');
const uploadFile = document.getElementById('upload-file');
const uploadBtn = document.getElementById('upload-btn');
const uploadStatus = document.getElementById('upload-status');

// Tab Switching Logic
const tabBtns = document.querySelectorAll('.tab-btn');
const tabPanes = document.querySelectorAll('.tab-pane');

tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active class from all
        tabBtns.forEach(b => b.classList.remove('active'));
        tabPanes.forEach(p => p.classList.remove('active'));
        
        // Add active class to clicked
        btn.classList.add('active');
        const tabId = btn.getAttribute('data-tab');
        document.getElementById(tabId).classList.add('active');
        
        // Reset status
        uploadStatus.classList.add('hidden');
    });
});

// Upload Event Listeners
openUploadBtn.addEventListener('click', () => {
    uploadModal.classList.remove('hidden');
    uploadStatus.classList.add('hidden');
    uploadForm.reset();
    document.getElementById('manual-form').reset();
});

closeUploadBtn.addEventListener('click', () => {
    uploadModal.classList.add('hidden');
});

// Helper for ingestion API call
async function submitIngestion(formData, submitBtn, originalText) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Validating & Ingesting...';
    uploadStatus.classList.add('hidden');

    try {
        const response = await fetch(`${API_BASE_URL}/incident/ingest`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            uploadStatus.textContent = `✅ Success: ${data.message}`;
            uploadStatus.style.color = 'var(--success)';
            uploadStatus.classList.remove('hidden');
            setTimeout(() => { uploadModal.classList.add('hidden'); }, 2000);
        } else {
            uploadStatus.textContent = `❌ Failed: ${data.detail || 'Unknown error'}`;
            uploadStatus.style.color = 'var(--red)';
            uploadStatus.classList.remove('hidden');
        }
    } catch (err) {
        uploadStatus.textContent = `❌ Network Error: Could not connect to backend.`;
        uploadStatus.style.color = 'var(--red)';
        uploadStatus.classList.remove('hidden');
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
}

// File Upload Submit
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = uploadFile.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    await submitIngestion(formData, uploadBtn, 'Upload & Validate');
});

// Manual Form Submit
document.getElementById('manual-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('manual-title').value.trim();
    const service = document.getElementById('manual-service').value.trim();
    const symptoms = document.getElementById('manual-symptoms').value.trim();
    const fix = document.getElementById('manual-fix').value.trim();

    // Format as Markdown
    const markdownContent = `# ${title}
**Affected Service:** ${service}

## Symptoms
${symptoms}

## Fix / Resolution
${fix}
`;

    // Create a Blob file
    const safeTitle = title.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const blob = new Blob([markdownContent], { type: 'text/markdown' });
    const file = new File([blob], `${safeTitle}.md`, { type: 'text/markdown' });

    const formData = new FormData();
    formData.append('file', file);
    
    const manualBtn = document.getElementById('manual-btn');
    await submitIngestion(formData, manualBtn, 'Submit & Validate');
});

let currentSessionId = null;
let loadingInterval = null;

const loadingStages = [
    "🔍 Retrieving historical incidents...",
    "🛠️ Running live system diagnostics...",
    "🧠 AI generating root cause...",
    "🛡️ Verifying security rules..."
];

function startLoading() {
    resultsContainer.classList.remove('hidden');
    loadingState.classList.remove('hidden');
    contentState.classList.add('hidden');
    errorState.classList.add('hidden');
    btn.disabled = true;

    const loaderText = loadingState.querySelector('p');
    loaderText.textContent = loadingStages[0];
    let stage = 0;
    loadingInterval = setInterval(() => {
        stage = (stage + 1) % loadingStages.length;
        loaderText.textContent = loadingStages[stage];
    }, 2500); // Change text every 2.5 seconds
}

function stopLoading() {
    clearInterval(loadingInterval);
    loadingState.classList.add('hidden');
    btn.disabled = false;
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    startLoading();

    try {
        // Build the request body. On follow-up turns, include the session_id
        // so the backend knows this is part of an ongoing conversation.
        const requestBody = { query: query };
        if (currentSessionId) {
            requestBody.session_id = currentSessionId;
        }

        const response = await fetch(`${API_BASE_URL}/incident/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        const data = await response.json();
        renderResult(data);

        // Clear the input after successful submission for follow-up
        input.value = '';
        input.placeholder = 'Ask a follow-up question...';

    } catch (err) {
        console.error(err);
        stopLoading();
        errorState.classList.remove('hidden');
        errorText.textContent = err.message || "Failed to analyze incident.";
    }
});

function renderResult(data) {
    stopLoading();
    contentState.classList.remove('hidden');
    
    currentSessionId = data.session_id;

    // Clear old banners
    const oldBanner = document.getElementById('postmortem-banner');
    if (oldBanner) oldBanner.remove();

    // Show success banner if a postmortem was generated
    if (data.generated_postmortem_path && !data.generated_postmortem_path.startsWith('Error')) {
        const filename = data.generated_postmortem_path.split(/[/\\]/).pop();
        const banner = document.createElement('div');
        banner.id = 'postmortem-banner';
        banner.style.background = 'rgba(16, 185, 129, 0.1)';
        banner.style.color = 'var(--success)';
        banner.style.padding = '1rem';
        banner.style.borderRadius = '8px';
        banner.style.marginBottom = '1.5rem';
        banner.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        banner.innerHTML = `<strong>Success:</strong> Postmortem <code>${filename}</code> automatically generated and ingested into the Knowledge Base!`;
        contentState.insertBefore(banner, contentState.firstChild);
    }

    // Confidence
    const confPerc = Math.round((data.confidence || 0) * 100);
    confFill.style.width = `${confPerc}%`;
    confVal.textContent = `${confPerc}%`;
    
    // Status Tag
    statusTag.textContent = (data.status || 'unknown').replace('_', ' ').toUpperCase();
    if (data.status === 'pending_approval') {
        statusTag.style.background = 'rgba(245, 158, 11, 0.2)';
        statusTag.style.color = 'var(--warning)';
    } else {
        statusTag.style.background = 'rgba(16, 185, 129, 0.2)';
        statusTag.style.color = 'var(--success)';
    }

    // Markdown Answer
    answerText.innerHTML = marked.parse(data.answer || "No specific answer provided.");

    // Reasoning
    reasoningText.textContent = data.reasoning || "No reasoning traces available.";

    // Fixes
    fixesList.innerHTML = '';
    if (data.suggested_fixes && data.suggested_fixes.length > 0) {
        data.suggested_fixes.forEach(fix => {
            const li = document.createElement('li');
            li.innerHTML = marked.parseInline(fix);
            fixesList.appendChild(li);
        });
    } else {
        fixesList.innerHTML = '<li>None identified</li>';
    }

    // Sources
    sourcesTags.innerHTML = '';
    if (data.sources && data.sources.length > 0) {
        data.sources.forEach(src => {
            const a = document.createElement('a');
            a.className = 'source-tag';
            a.textContent = src;
            // The source usually looks like "INC-0041: ... (filename.ext)" or just "filename.ext"
            // Let's try to extract the filename
            let filename = src;
            const match = src.match(/\(([^)]+\.(?:md|txt|docx|pdf))\)$/i) || src.match(/^([^ ]+\.(?:md|txt|docx|pdf))$/i);
            if (match && match[1]) {
                filename = match[1];
            } else if (src.includes('.')) {
                // Fallback for just raw filenames
                filename = src;
            } else {
                filename = null;
            }

            if (filename) {
                a.href = `${API_BASE_URL}/document/${filename}`;
                a.download = filename;
                a.target = '_blank';
                a.title = 'Click to download raw postmortem';
                a.style.textDecoration = 'none';
                a.style.cursor = 'pointer';
            } else {
                a.style.cursor = 'default';
            }
            sourcesTags.appendChild(a);
        });
    } else {
        sourcesTags.innerHTML = '<span class="source-tag">No sources used</span>';
    }

    // Human Approval Flow
    if (data.status === 'pending_approval') {
        approvalBox.classList.remove('hidden');
    } else {
        approvalBox.classList.add('hidden');
    }
}

// Approval Handlers
document.getElementById('approve-btn').addEventListener('click', () => resumeGraph('approve'));
document.getElementById('reject-btn').addEventListener('click', () => resumeGraph('reject'));

async function resumeGraph(action) {
    if (!currentSessionId) return;

    approvalBox.classList.add('hidden');
    startLoading();
    
    try {
        const response = await fetch(`${API_BASE_URL}/incident/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                query: input.value.trim(),
                session_id: currentSessionId,
                resume_action: action
            })
        });

        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        const data = await response.json();
        renderResult(data);

    } catch (err) {
        console.error(err);
        loadingState.classList.add('hidden');
        errorState.classList.remove('hidden');
        errorText.textContent = "Failed to resume graph execution.";
    }
}
