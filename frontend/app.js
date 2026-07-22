// Dynamically detect API base URL based on environment
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8080' 
    : 'https://65-0-174-137.sslip.io';

// Configure Marked to use Highlight.js
if (typeof marked !== 'undefined' && typeof hljs !== 'undefined') {
    marked.setOptions({
        highlight: function (code, lang) {
            const language = hljs.getLanguage(lang) ? lang : 'plaintext';
            return hljs.highlight(code, { language }).value;
        },
        langPrefix: 'hljs language-'
    });
}

// Global Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
    // '/' to focus chat input
    if (e.key === '/' && document.activeElement !== input && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
        e.preventDefault();
        input.focus();
    }
});

// State
let currentSessionId = crypto.randomUUID();
let loadingInterval = null;
let token = localStorage.getItem('incidentiq_token');
let username = localStorage.getItem('incidentiq_user') || 'User';

// Auth DOM
const loginModal = document.getElementById('login-modal');
const layoutWrapper = document.querySelector('.layout-wrapper');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const authStatus = document.getElementById('auth-status');
const userDisplay = document.getElementById('user-display');
const logoutBtn = document.getElementById('logout-btn');

// Chat & Layout DOM
const form = document.getElementById('incident-form');
const input = document.getElementById('query-input');
const btn = document.getElementById('analyze-btn');
const chatMessages = document.getElementById('chat-messages');
const historyList = document.getElementById('history-list');
const newChatBtn = document.getElementById('new-chat-btn');
const loadingState = document.getElementById('loading-spinner');

// Auth Setup
function checkAuth() {
    if (!token) {
        loginModal.classList.remove('hidden');
        layoutWrapper.classList.add('hidden');
    } else {
        loginModal.classList.add('hidden');
        layoutWrapper.classList.remove('hidden');
        userDisplay.textContent = username;
        loadSidebarHistory();
    }
}

// Tab Switching (Login/Register and Upload)
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const tabsContainer = e.target.closest('.tabs');
        tabsContainer.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        
        const tabId = e.target.getAttribute('data-tab');
        const panesContainer = e.target.closest('.modal-card');
        panesContainer.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');
        
        if (authStatus) authStatus.classList.add('hidden');
    });
});

// Auth API Calls
async function handleAuth(url, body) {
    try {
        const res = await fetch(`${API_BASE_URL}${url}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.message || "Authentication failed");
        return data;
    } catch (err) {
        authStatus.textContent = err.message;
        authStatus.style.color = 'var(--red)';
        authStatus.classList.remove('hidden');
        throw err;
    }
}

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('login-username').value;
    const p = document.getElementById('login-password').value;
    const data = await handleAuth('/auth/login', { username: u, password: p });
    if (data.token) {
        token = data.token;
        username = data.username;
        localStorage.setItem('incidentiq_token', token);
        localStorage.setItem('incidentiq_user', username);
        checkAuth();
    }
});

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('reg-username').value;
    const p = document.getElementById('reg-password').value;
    await handleAuth('/auth/register', { username: u, password: p });
    authStatus.textContent = "Registration successful! Please login.";
    authStatus.style.color = 'var(--success)';
    authStatus.classList.remove('hidden');
    document.querySelector('[data-tab="login-tab"]').click();
});

logoutBtn.addEventListener('click', async () => {
    if (token) {
        await fetch(`${API_BASE_URL}/auth/logout`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        }).catch(console.error);
    }
    token = null;
    localStorage.removeItem('incidentiq_token');
    localStorage.removeItem('incidentiq_user');
    currentSessionId = crypto.randomUUID();
    clearChat();
    checkAuth();
});

// Sidebar History
async function loadSidebarHistory() {
    try {
        const res = await fetch(`${API_BASE_URL}/incident/history`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.status === 401) return logoutBtn.click(); // Token expired
        const threads = await res.json();
        
        historyList.innerHTML = '';
        if (Array.isArray(threads)) {
            threads.forEach(t => {
                const li = document.createElement('li');
                
                const titleSpan = document.createElement('span');
                titleSpan.textContent = t.title;
                titleSpan.style.flex = "1";
                titleSpan.style.overflow = "hidden";
                titleSpan.style.textOverflow = "ellipsis";
                titleSpan.style.whiteSpace = "nowrap";
                
                const deleteBtn = document.createElement('span');
                deleteBtn.innerHTML = '🗑️';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.style.fontSize = '12px';
                deleteBtn.style.marginLeft = '8px';
                deleteBtn.style.opacity = '0.6';
                
                deleteBtn.addEventListener('mouseover', () => deleteBtn.style.opacity = '1');
                deleteBtn.addEventListener('mouseout', () => deleteBtn.style.opacity = '0.6');
                
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation(); // Prevent li click
                    if (confirm('Are you sure you want to delete this chat thread?')) {
                        try {
                            await fetch(`${API_BASE_URL}/auth/history/${t.thread_id}`, {
                                method: 'DELETE',
                                headers: { 'Authorization': `Bearer ${token}` }
                            });
                            if (currentSessionId === t.thread_id) {
                                document.getElementById('new-incident-btn').click();
                            }
                            loadSidebarHistory();
                        } catch (err) {
                            console.error('Failed to delete thread', err);
                        }
                    }
                });

                li.appendChild(titleSpan);
                li.appendChild(deleteBtn);
                li.style.display = 'flex';
                li.style.justifyContent = 'space-between';
                li.style.alignItems = 'center';
                
                if (t.thread_id === currentSessionId) li.classList.add('active');
                li.addEventListener('click', () => loadThread(t.thread_id));
                historyList.appendChild(li);
            });
        }
    } catch (e) {
        console.error("Failed to load history", e);
    }
}

function clearChat() {
    chatMessages.innerHTML = `
        <div class="empty-state-container" id="empty-state">
            <div class="empty-state-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            </div>
            <h2>How can I help you today?</h2>
            <p class="empty-state-subtitle">I am IncidentIQ, your autonomous AI Reliability Engineer. Choose an option below or describe your issue.</p>
            
            <div class="suggestion-grid">
                <div class="suggestion-card" data-query="checkout-service is throwing HTTP 500 errors and CPU is spiking. Can you diagnose?">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                    <h4>Diagnose Live Issue</h4>
                    <p>e.g., checkout-service HTTP 500s</p>
                </div>
                <div class="suggestion-card" data-query="What caused the database connection timeout incident last week?">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    <h4>Search Past Incidents</h4>
                    <p>Query the postmortem database</p>
                </div>
                <div class="suggestion-card" data-query="What is your architecture and how do you resolve incidents?">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>
                    <h4>Learn about IncidentIQ</h4>
                    <p>Ask how the AI agent works</p>
                </div>
            </div>
        </div>
    `;

    // Bind suggestion cards
    document.querySelectorAll('.suggestion-card').forEach(card => {
        card.addEventListener('click', () => {
            input.value = card.getAttribute('data-query');
            btn.click(); // Auto submit
        });
    });
}

newChatBtn.addEventListener('click', () => {
    currentSessionId = crypto.randomUUID();
    clearChat();
    loadSidebarHistory();
});

async function loadThread(threadId) {
    currentSessionId = threadId;
    loadSidebarHistory(); // Update active state
    
    // Show loader
    chatMessages.innerHTML = '';
    loadingState.classList.remove('hidden');
    
    try {
        const res = await fetch(`${API_BASE_URL}/incident/history/${threadId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await res.json();
        
        loadingState.classList.add('hidden');
        if (data.messages && data.messages.length > 0) {
            data.messages.forEach(msg => {
                if (msg.role === 'user') {
                    appendUserMessage(msg.content);
                } else {
                    // For historical AI messages, we just render the raw markdown for simplicity
                    // since the full structured UI JSON state might not be fully retrievable from just string history.
                    // But in a real app, we'd persist the JSON response too.
                    appendSimpleAIMessage(msg.content);
                }
            });
        } else {
            clearChat();
        }
        chatMessages.scrollTo(0, chatMessages.scrollHeight);
    } catch (e) {
        loadingState.classList.add('hidden');
        appendSimpleAIMessage("Failed to load thread history.");
    }
}

// UI Helpers
function appendUserMessage(text) {
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.remove();

    const div = document.createElement('div');
    div.className = 'message user-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
        </div>
        <div class="message-content">${text}</div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTo(0, chatMessages.scrollHeight);
}

function appendSimpleAIMessage(text) {
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <div class="message-content markdown-body">${marked.parse(text)}</div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTo(0, chatMessages.scrollHeight);
}

function createAIResponseCard() {
    const template = document.getElementById('ai-response-template').content.cloneNode(true);
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `
        <div class="message-avatar">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <div class="message-content"></div>
    `;
    div.querySelector('.message-content').appendChild(template);
    chatMessages.appendChild(div);
    
    // Bind Copy Button
    const copyBtn = div.querySelector('.copy-btn');
    const answerText = div.querySelector('.answer-text');
    if (copyBtn && answerText) {
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(answerText.innerText);
                const originalHTML = copyBtn.innerHTML;
                copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied`;
                copyBtn.style.color = "var(--success)";
                setTimeout(() => {
                    copyBtn.innerHTML = originalHTML;
                    copyBtn.style.color = "";
                }, 2000);
            } catch (err) {
                console.error("Failed to copy text: ", err);
            }
        });
    }

    return {
        container: div,
        answerText: answerText,
        confFill: div.querySelector('.confidence-fill'),
        confVal: div.querySelector('.confidence-val'),
        statusTag: div.querySelector('.status-tag'),
        reasoningText: div.querySelector('.reasoning-text'),
        fixesList: div.querySelector('.fixes-list'),
        sourcesTags: div.querySelector('.sources-tags'),
        approvalBox: div.querySelector('.approval-box'),
        approveBtn: div.querySelector('.approve-btn'),
        rejectBtn: div.querySelector('.reject-btn')
    };
}

// Chat Submission
const loadingStages = [
    "🔍 Retrieving historical incidents...",
    "🛠️ Running live system diagnostics...",
    "🧠 AI generating root cause...",
    "🛡️ Verifying security rules..."
];

// Textarea auto-resize and Enter key handling
input.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.value === '') {
        this.style.height = 'auto';
    }
});

input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        btn.click(); // Trigger form submit
    }
});

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    appendUserMessage(query);
    input.value = '';
    
    loadingState.classList.remove('hidden');
    btn.disabled = true;
    
    const loaderText = loadingState.querySelector('p');
    loaderText.textContent = loadingStages[0];
    let stage = 0;
    loadingInterval = setInterval(() => {
        stage = (stage + 1) % loadingStages.length;
        loaderText.textContent = loadingStages[stage];
    }, 2500);

    try {
        const response = await fetch(`${API_BASE_URL}/incident/analyze`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ query: query, session_id: currentSessionId })
        });

        if (response.status === 401) {
            logoutBtn.click();
            throw new Error("Session expired. Please login again.");
        }
        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        await handleStream(response);
        loadSidebarHistory(); // Refresh sidebar title

    } catch (err) {
        clearInterval(loadingInterval);
        loadingState.classList.add('hidden');
        btn.disabled = false;
        appendSimpleAIMessage(`Error: ${err.message}`);
    }
});

async function handleStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let accumulatedAnswer = "";

    const ui = createAIResponseCard();
    ui.answerText.classList.add('typing-cursor');

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        const parts = buffer.split('\n\n');
        buffer = parts.pop(); 

        for (const part of parts) {
            if (part.startsWith('data: ')) {
                const jsonStr = part.slice(6);
                try {
                    const event = JSON.parse(jsonStr);
                    
                    if (event.type === 'status') {
                        const loaderText = loadingState.querySelector('p');
                        if (loaderText) loaderText.textContent = event.message;
                    } 
                    else if (event.type === 'token') {
                        if(loadingState.classList.contains('hidden') === false) {
                            clearInterval(loadingInterval);
                            loadingState.classList.add('hidden');
                            btn.disabled = false;
                        }
                        
                        accumulatedAnswer += event.content;
                        ui.answerText.innerHTML = marked.parse(accumulatedAnswer);
                        chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
                    } 
                    else if (event.type === 'final_result') {
                        ui.answerText.classList.remove('typing-cursor');
                        renderResult(event.data, accumulatedAnswer, ui);
                    } 
                    else if (event.type === 'error') {
                        ui.answerText.classList.remove('typing-cursor');
                        throw new Error(event.message);
                    }
                } catch (e) {
                    if (e.message !== "Unexpected end of JSON input") {
                        console.error("Error parsing SSE JSON:", e, jsonStr);
                    }
                }
            }
        }
    }
    
    clearInterval(loadingInterval);
    loadingState.classList.add('hidden');
    btn.disabled = false;
    ui.answerText.classList.remove('typing-cursor');
}

function renderResult(data, streamedAnswer, ui) {
    if (data.generated_postmortem_path && !data.generated_postmortem_path.startsWith('Error')) {
        const filename = data.generated_postmortem_path.split(/[/\\]/).pop();
        const banner = document.createElement('div');
        banner.style.background = 'rgba(16, 185, 129, 0.1)';
        banner.style.color = 'var(--success)';
        banner.style.padding = '1rem';
        banner.style.borderRadius = '8px';
        banner.style.marginBottom = '1.5rem';
        banner.style.border = '1px solid rgba(16, 185, 129, 0.3)';
        banner.innerHTML = `<strong>Success:</strong> Postmortem <code>${filename}</code> automatically generated and ingested into the Knowledge Base!`;
        ui.container.querySelector('.message-content').insertBefore(banner, ui.container.querySelector('.content-state'));
    }

    const confPerc = Math.round((data.confidence || 0) * 100);
    ui.confFill.style.width = `${confPerc}%`;
    ui.confVal.textContent = `${confPerc}%`;
    
    ui.statusTag.textContent = (data.status || 'unknown').replace('_', ' ').toUpperCase();
    if (data.status === 'pending_approval') {
        ui.statusTag.style.background = 'rgba(245, 158, 11, 0.2)';
        ui.statusTag.style.color = 'var(--warning)';
    } else {
        ui.statusTag.style.background = 'rgba(16, 185, 129, 0.2)';
        ui.statusTag.style.color = 'var(--success)';
    }

    const finalAnswerText = streamedAnswer || data.answer || "No specific answer provided.";
    ui.answerText.innerHTML = marked.parse(finalAnswerText);
    ui.reasoningText.textContent = data.reasoning || "No reasoning traces available.";

    ui.fixesList.innerHTML = '';
    if (data.suggested_fixes && data.suggested_fixes.length > 0) {
        data.suggested_fixes.forEach(fix => {
            const li = document.createElement('li');
            li.innerHTML = marked.parseInline(fix);
            ui.fixesList.appendChild(li);
        });
    } else {
        ui.fixesList.innerHTML = '<li>None identified</li>';
    }

    ui.sourcesTags.innerHTML = '';
    if (data.sources && data.sources.length > 0) {
        data.sources.forEach(src => {
            const a = document.createElement('a');
            a.className = 'source-tag';
            a.textContent = src;
            let filename = src;
            if (filename.includes('\\')) filename = filename.split('\\').pop();
            if (filename.includes('/')) filename = filename.split('/').pop();
            
            const match = src.match(/\(([^)]+\.(?:md|txt|docx|pdf))\)$/i) || src.match(/^([^ ]+\.(?:md|txt|docx|pdf))$/i);
            if (match && match[1]) filename = match[1];
            else if (!src.includes('.')) filename = null;

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
            ui.sourcesTags.appendChild(a);
        });
    } else {
        const span = document.createElement('span');
        span.className = 'tag source-tag';
        span.textContent = 'No sources used';
        span.style.opacity = '0.5';
        span.style.cursor = 'default';
        ui.sourcesTags.appendChild(span);
    }
    
    // Conditionally hide empty sections for chitchat
    if (data.mode === 'chitchat' || data.mode === 'known' || (!data.reasoning && (!data.suggested_fixes || data.suggested_fixes.length === 0))) {
        const grid2 = ui.container.querySelector('.grid-2');
        const sourcesCard = ui.container.querySelector('.sources-card');
        if (grid2) grid2.style.display = 'none';
        if (sourcesCard) sourcesCard.style.display = 'none';
    }

    if (data.status === 'pending_approval') {
        ui.approvalBox.classList.remove('hidden');
        ui.approveBtn.onclick = () => resumeGraph('approve', ui);
        ui.rejectBtn.onclick = () => resumeGraph('reject', ui);
    }
}

async function resumeGraph(action, ui) {
    ui.approvalBox.classList.add('hidden');
    
    // We append a new AI card for the continuation
    const newUI = createAIResponseCard();
    newUI.answerText.classList.add('typing-cursor');
    chatMessages.scrollTo(0, chatMessages.scrollHeight);

    try {
        const response = await fetch(`${API_BASE_URL}/incident/analyze`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ 
                query: "Resume analysis",
                session_id: currentSessionId,
                resume_action: action
            })
        });

        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        // We override handleStream to target newUI
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        let accumulatedAnswer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop(); 

            for (const part of parts) {
                if (part.startsWith('data: ')) {
                    const jsonStr = part.slice(6);
                    try {
                        const event = JSON.parse(jsonStr);
                        if (event.type === 'token') {
                            accumulatedAnswer += event.content;
                            newUI.answerText.innerHTML = marked.parse(accumulatedAnswer);
                            chatMessages.scrollTo(0, chatMessages.scrollHeight);
                        } 
                        else if (event.type === 'final_result') {
                            newUI.answerText.classList.remove('typing-cursor');
                            renderResult(event.data, accumulatedAnswer, newUI);
                        } 
                    } catch (e) {}
                }
            }
        }
        newUI.answerText.classList.remove('typing-cursor');

    } catch (err) {
        newUI.answerText.classList.remove('typing-cursor');
        newUI.answerText.innerHTML = `Error resuming graph: ${err.message}`;
    }
}

// Upload Logic
const openUploadBtn = document.getElementById('open-upload-btn');
const closeUploadBtn = document.getElementById('close-upload-btn');
const uploadModal = document.getElementById('upload-modal');
const uploadStatus = document.getElementById('upload-status');

if (openUploadBtn) openUploadBtn.addEventListener('click', () => {
    uploadModal.classList.remove('hidden');
    if (uploadStatus) uploadStatus.classList.add('hidden');
});
if (closeUploadBtn) closeUploadBtn.addEventListener('click', () => uploadModal.classList.add('hidden'));

// Drag and Drop File Input
const fileDropZone = document.getElementById('file-drop-zone');
const uploadFileInput = document.getElementById('upload-file');
const selectedFileName = document.getElementById('selected-file-name');

if (fileDropZone && uploadFileInput) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        fileDropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        fileDropZone.addEventListener(eventName, () => fileDropZone.classList.add('drag-over'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        fileDropZone.addEventListener(eventName, () => fileDropZone.classList.remove('drag-over'), false);
    });

    fileDropZone.addEventListener('drop', (e) => {
        let dt = e.dataTransfer;
        let files = dt.files;
        if (files.length) {
            uploadFileInput.files = files;
            updateFileName();
        }
    });

    uploadFileInput.addEventListener('change', updateFileName);

    function updateFileName() {
        if (uploadFileInput.files.length > 0) {
            selectedFileName.textContent = `Selected: ${uploadFileInput.files[0].name}`;
            selectedFileName.classList.remove('hidden');
        } else {
            selectedFileName.textContent = '';
            selectedFileName.classList.add('hidden');
        }
    }
}

// Handle Form Submissions for Upload
const uploadForm = document.getElementById('upload-form');
if (uploadForm) {
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        if (!uploadFileInput.files.length) return;
        
        const file = uploadFileInput.files[0];
        const formData = new FormData();
        formData.append('file', file);
        
        const uploadBtn = document.getElementById('upload-btn');
        const originalText = uploadBtn.textContent;
        uploadBtn.textContent = 'Uploading...';
        uploadBtn.disabled = true;
        
        try {
            const res = await fetch(`${API_BASE_URL}/incident/ingest`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });
            const data = await res.json();
            
            if (!res.ok) throw new Error(data.detail || data.message || 'Upload failed');
            
            uploadStatus.textContent = data.message;
            uploadStatus.style.color = 'var(--success)';
            uploadStatus.classList.remove('hidden');
            uploadForm.reset();
            if (selectedFileName) selectedFileName.classList.add('hidden');
            
        } catch (err) {
            uploadStatus.textContent = err.message;
            uploadStatus.style.color = 'var(--red)';
            uploadStatus.classList.remove('hidden');
        } finally {
            uploadBtn.textContent = originalText;
            uploadBtn.disabled = false;
        }
    });
}

// Handle Manual Form
const manualForm = document.getElementById('manual-form');
if (manualForm) {
    manualForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const title = document.getElementById('manual-title').value;
        const service = document.getElementById('manual-service').value;
        const symptoms = document.getElementById('manual-symptoms').value;
        const fix = document.getElementById('manual-fix').value;
        
        const content = `# ${title}\n\n**Service:** ${service}\n\n## Symptoms\n${symptoms}\n\n## Resolution\n${fix}`;
        
        // Convert string to file
        const file = new File([content], `${title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.md`, { type: 'text/markdown' });
        const formData = new FormData();
        formData.append('file', file);
        
        const manualBtn = document.getElementById('manual-btn');
        const originalText = manualBtn.textContent;
        manualBtn.textContent = 'Uploading...';
        manualBtn.disabled = true;
        
        try {
            const res = await fetch(`${API_BASE_URL}/incident/ingest`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` },
                body: formData
            });
            const data = await res.json();
            
            if (!res.ok) throw new Error(data.detail || data.message || 'Upload failed');
            
            uploadStatus.textContent = data.message;
            uploadStatus.style.color = 'var(--success)';
            uploadStatus.classList.remove('hidden');
            manualForm.reset();
            
        } catch (err) {
            uploadStatus.textContent = err.message;
            uploadStatus.style.color = 'var(--red)';
            uploadStatus.classList.remove('hidden');
        } finally {
            manualBtn.textContent = originalText;
            manualBtn.disabled = false;
        }
    });
}

// Initialize on Load
checkAuth();
