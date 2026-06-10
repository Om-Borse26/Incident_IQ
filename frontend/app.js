// Connect to the Live Railway URL
const API_BASE_URL = 'https://incidentiq-production-b6f3.up.railway.app';

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

let currentSessionId = null;

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    // Reset UI
    resultsContainer.classList.remove('hidden');
    loadingState.classList.remove('hidden');
    contentState.classList.add('hidden');
    errorState.classList.add('hidden');
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/incident/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query })
        });

        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        const data = await response.json();
        renderResult(data);

    } catch (err) {
        console.error(err);
        loadingState.classList.add('hidden');
        errorState.classList.remove('hidden');
        errorText.textContent = err.message || "Failed to analyze incident.";
    } finally {
        btn.disabled = false;
    }
});

function renderResult(data) {
    loadingState.classList.add('hidden');
    contentState.classList.remove('hidden');
    
    currentSessionId = data.session_id;

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
            li.textContent = fix;
            fixesList.appendChild(li);
        });
    } else {
        fixesList.innerHTML = '<li>None identified</li>';
    }

    // Sources
    sourcesTags.innerHTML = '';
    if (data.sources && data.sources.length > 0) {
        data.sources.forEach(src => {
            const span = document.createElement('span');
            span.className = 'source-tag';
            span.textContent = src;
            sourcesTags.appendChild(span);
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
    loadingState.classList.remove('hidden');
    contentState.classList.add('hidden');
    
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
