// Dynamically detect API base URL based on environment
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8080' 
    : 'https://65-0-174-137.sslip.io';

// ===========================================================
// CHATGPT-STYLE MARKED RENDERER
// ===========================================================
if (typeof marked !== 'undefined') {
    const renderer = new marked.Renderer();
    
    renderer.code = function(code, language) {
        // Support both old (string) and new (object) marked API
        const codeStr = (typeof code === 'object' && code !== null) ? (code.text || '') : (code || '');
        const lang = (typeof code === 'object' && code !== null) ? (code.lang || language || 'plaintext') : (language || 'plaintext');
        const langLabel = lang || 'plaintext';
        let highlighted = codeStr;
        if (typeof hljs !== 'undefined') {
            const validLang = hljs.getLanguage(langLabel) ? langLabel : 'plaintext';
            highlighted = hljs.highlight(codeStr, { language: validLang }).value;
        }
        // Escape for data-code attribute
        const escapedCode = codeStr.replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<div class="code-block-wrapper">
            <div class="code-block-header">
                <span class="code-block-lang">${langLabel.toUpperCase()}</span>
                <button class="code-copy-btn" onclick="copyCodeBlock(this)" data-code="${escapedCode}">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    Copy
                </button>
            </div>
            <pre class="code-block-pre"><code class="hljs language-${langLabel}">${highlighted}</code></pre>
        </div>`;
    };

    marked.use({ renderer });
}

function copyCodeBlock(btn) {
    // data-rawcode is used by the live-logs panel (no entity escaping needed)
    // data-code is used by the markdown code blocks (HTML entities must be decoded)
    const rawCode = btn.getAttribute('data-rawcode');
    if (rawCode) {
        // Already unescaped — just write it directly
        navigator.clipboard.writeText(rawCode.replace(/&quot;/g, '"')).then(() => {
            btn.textContent = 'Copied!';
            btn.style.color = 'var(--success)';
            setTimeout(() => {
                btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy Logs`;
                btn.style.color = '';
            }, 2000);
        }).catch(console.error);
    } else {
        // Decode HTML entities from data-code attribute
        const raw = btn.getAttribute('data-code') || '';
        const decoded = raw.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
        navigator.clipboard.writeText(decoded).then(() => {
            btn.textContent = 'Copied!';
            btn.style.color = 'var(--success)';
            setTimeout(() => {
                btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
                btn.style.color = '';
            }, 2000);
        }).catch(console.error);
    }
}

// Global Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
    // '/' to focus chat input
    if (e.key === '/' && document.activeElement !== input && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
        e.preventDefault();
        input.focus();
    }
});

let currentSessionId = crypto.randomUUID();
let loadingInterval = null;
let token = localStorage.getItem('incidentiq_token');
let username = localStorage.getItem('incidentiq_user') || 'User';

// Map of sessionId -> 'pending' | 'done' | 'error'
const activeSessions = new Map();

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

// ===========================================================
// RESIZABLE SIDEBAR
// ===========================================================
const sidebar = document.getElementById('sidebar');
const resizeHandle = document.getElementById('sidebar-resize-handle');
let isResizing = false;

resizeHandle.addEventListener('mousedown', (e) => {
    isResizing = true;
    resizeHandle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
});

document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const newWidth = e.clientX;
    if (newWidth >= 180 && newWidth <= 480) {
        sidebar.style.width = newWidth + 'px';
    }
});

document.addEventListener('mouseup', () => {
    if (isResizing) {
        isResizing = false;
        resizeHandle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    }
});

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
                const isPending = activeSessions.get(t.thread_id) === 'pending';
                titleSpan.textContent = isPending ? "⚙️ Generating..." : (t.title || "New Incident");
                titleSpan.style.whiteSpace = "nowrap";
                titleSpan.style.overflow = "hidden";
                titleSpan.style.textOverflow = "ellipsis";
                titleSpan.style.flex = "1";
                titleSpan.style.minWidth = "0";
                titleSpan.style.marginRight = "8px";
                
                const deleteBtn = document.createElement('span');
                deleteBtn.innerHTML = '🗑️';
                deleteBtn.style.cursor = 'pointer';
                deleteBtn.style.fontSize = '12px';
                deleteBtn.style.opacity = '0.6';
                deleteBtn.style.flexShrink = '0';
                
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

function bindSuggestionCards() {
    document.querySelectorAll('.suggestion-card').forEach(card => {
        // Remove old listener if any to avoid duplicates
        const newCard = card.cloneNode(true);
        card.parentNode.replaceChild(newCard, card);
        newCard.addEventListener('click', () => {
            input.value = newCard.getAttribute('data-query');
            btn.click(); // Auto submit
        });
    });
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
                <div class="suggestion-card" data-query="I want to write a .md document to ingest an issue into the knowledge base. Please provide a standard Markdown template. Also, include guidelines reminding users to check for duplicates first and wait about 1 minute after ingestion for the async SQS queue to process before searching.">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#eab308" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    <h4>Document an Issue</h4>
                    <p>Get a template & ingestion rules</p>
                </div>
                <div class="suggestion-card" data-query="What is your architecture and how do you resolve incidents?">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path></svg>
                    <h4>Learn about IncidentIQ</h4>
                    <p>Ask how the AI agent works</p>
                </div>
            </div>
        </div>
    `;

    bindSuggestionCards();
}

// Bind initial cards on page load
document.addEventListener("DOMContentLoaded", () => {
    bindSuggestionCards();
});

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
    
    // 1. If we know it's currently generating in the background, reconnect to it
    if (activeSessions.get(threadId) === 'pending') {
        try {
            const res = await fetch(`${API_BASE_URL}/incident/session/${threadId}/result`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.headers.get('content-type')?.includes('text/event-stream')) {
                // It's still running, reconnect stream
                chatMessages.appendChild(loadingState);
                await handleStream(res);
                return;
            } else {
                const data = await res.json();
                if (data.status === 'done') {
                    loadingState.classList.add('hidden');
                    const ui = createAIResponseCard();
                    ui.answerText.classList.remove('typing-cursor');
                    renderResult(data.data, data.data.answer, ui);
                    activeSessions.set(threadId, 'done');
                    loadSidebarHistory();
                    return;
                }
            }
        } catch (e) {
            console.error("Failed to reconnect to pending session", e);
        }
    }
    
    // 2. Otherwise load historical completed messages
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
                    // Render rich historical messages if they have mode/reasoning
                    if (msg.mode || msg.reasoning) {
                        const ui = createAIResponseCard();
                        ui.answerText.classList.remove('typing-cursor');
                        renderResult(msg, msg.content, ui);
                    } else {
                        appendSimpleAIMessage(msg.content);
                    }
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
        contentEl: div.querySelector('.message-content'),
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

// Scroll to bottom of chat
function scrollToBottom() {
    chatMessages.scrollTo({ top: chatMessages.scrollHeight, behavior: 'smooth' });
}

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
    
    // Mark as pending and update sidebar immediately
    activeSessions.set(currentSessionId, 'pending');
    loadSidebarHistory();
    
    // Move loading state into the chat messages container so it appears inline
    chatMessages.appendChild(loadingState);
    loadingState.classList.remove('hidden');
    btn.disabled = true;
    
    const loaderText = loadingState.querySelector('p');
    loaderText.textContent = loadingStages[0];
    let stage = 0;
    loadingInterval = setInterval(() => {
        stage = (stage + 1) % loadingStages.length;
        loaderText.textContent = loadingStages[stage];
    }, 2500);
    scrollToBottom();

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
    let userHasScrolledUp = false;

    // Track if user scrolled up during generation
    const onUserScroll = () => {
        const distFromBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight;
        userHasScrolledUp = distFromBottom > 80;
    };
    chatMessages.addEventListener('scroll', onUserScroll, { passive: true });

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
                        if (!userHasScrolledUp) {
                            scrollToBottom();
                        }
                    } 
                    else if (event.type === 'final_result') {
                        ui.answerText.classList.remove('typing-cursor');
                        renderResult(event.data, accumulatedAnswer, ui);
                        activeSessions.set(currentSessionId, 'done');
                        loadSidebarHistory();
                    } 
                    else if (event.type === 'error') {
                        ui.answerText.classList.remove('typing-cursor');
                        ui.answerText.innerHTML = `<span style="color:var(--red);">Error: ${event.message}</span>`;
                        clearInterval(loadingInterval);
                        loadingState.classList.add('hidden');
                        btn.disabled = false;
                        activeSessions.set(currentSessionId, 'error');
                        loadSidebarHistory();
                        return;
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
    chatMessages.removeEventListener('scroll', onUserScroll);
}

function renderResult(data, streamedAnswer, ui) {
    // ---------------------------------------------------------------
    // DECISION MATRIX — which node produced this answer?
    //
    //  followup_type="followup_conv" → pure conversational reply (no new RAG)
    //    → show ONLY answer text. No meta, no sections.
    //
    //  query_type="chitchat"          → off-topic / greeting
    //    → show ONLY answer text. No meta, no sections.
    //
    //  query_type="live"              → live incident diagnosis
    //    → show meta + all sections + live logs window
    //
    //  followup_type="followup_rag"   → new RAG search triggered by follow-up
    //    → show meta + all sections (+ live logs if query_type=live)
    //
    //  everything else (new_query historical / followup_rag historical)
    //    → show meta + all sections, no live logs
    // ---------------------------------------------------------------
    const mode        = data.mode        || 'unknown';
    const queryType   = data.query_type  || 'historical';
    const followupType = data.followup_type || 'new_query';

    // Two cases where we show ONLY the bare answer — no chrome at all
    const isAnswerOnly = (followupType === 'followup_conv') || (queryType === 'chitchat');

    const isLive      = (queryType === 'live');
    const hasLiveLogs = isLive && (
        (data.live_logs && data.live_logs.trim()) ||
        (data.service_health && Object.keys(data.service_health).length > 0)
    );

    // ---------------------------------------------------------------
    // Postmortem banner (always shown when present)
    // ---------------------------------------------------------------
    if (data.generated_postmortem_path && !data.generated_postmortem_path.startsWith('Error')) {
        const filename = data.generated_postmortem_path.split(/[/\\]/).pop();
        const banner = document.createElement('div');
        banner.style.cssText = 'background:rgba(16,185,129,.1);color:var(--success);padding:1rem;border-radius:8px;margin-bottom:1.5rem;border:1px solid rgba(16,185,129,.3);';
        banner.innerHTML = `<strong>Success:</strong> Postmortem <code>${filename}</code> automatically generated and ingested into the Knowledge Base!`;
        ui.container.querySelector('.message-content').insertBefore(banner, ui.container.querySelector('.content-state'));
    }

    // ---------------------------------------------------------------
    // Meta panel (confidence + status)
    // ---------------------------------------------------------------
    const metaPanel = ui.container.querySelector('.meta-panel');
    if (isAnswerOnly) {
        if (metaPanel) metaPanel.style.display = 'none';
    } else {
        if (metaPanel) metaPanel.style.display = '';
        const confPerc = Math.round((data.confidence || 0) * 100);
        ui.confFill.style.width = `${confPerc}%`;
        ui.confVal.textContent = `${confPerc}%`;
        const statusText = (data.status || 'COMPLETED').replace('_', ' ').toUpperCase();
        ui.statusTag.textContent = statusText;
        if (data.status === 'pending_approval' || data.needs_postmortem) {
            ui.statusTag.style.background = 'rgba(245, 158, 11, 0.2)';
            ui.statusTag.style.color = 'var(--warning)';
        } else {
            ui.statusTag.style.background = 'rgba(16, 185, 129, 0.2)';
            ui.statusTag.style.color = 'var(--success)';
        }
    }

    // ---------------------------------------------------------------
    // Answer card title
    // ---------------------------------------------------------------
    const answerCard = ui.container.querySelector('.answer-card');
    const answerCardTitle = answerCard ? answerCard.querySelector('h3') : null;
    if (answerCardTitle) {
        if (followupType === 'followup_conv') answerCardTitle.textContent = 'Clarification';
        else if (queryType === 'chitchat')    answerCardTitle.textContent = 'IncidentIQ Response';
        else if (isLive)                      answerCardTitle.textContent = 'Live Incident Analysis';
        else if (followupType === 'followup_rag') answerCardTitle.textContent = 'Follow-Up Analysis';
        else                                  answerCardTitle.textContent = 'Root Cause Analysis';
    }

    // ---------------------------------------------------------------
    // Main answer text
    // ---------------------------------------------------------------
    const finalAnswerText = streamedAnswer || data.answer || 'No specific answer provided.';
    ui.answerText.innerHTML = marked.parse(finalAnswerText);
    // Only highlight code blocks NOT already processed by our custom renderer
    if (typeof hljs !== 'undefined') {
        ui.answerText.querySelectorAll('pre:not(.code-block-pre) > code').forEach(el => hljs.highlightElement(el));
    }

    // ---------------------------------------------------------------
    // Live Logs panel — only for live incidents
    // ---------------------------------------------------------------
    const existingLogsWindow = ui.container.querySelector('.live-logs-window');
    if (existingLogsWindow) existingLogsWindow.remove();

    if (!isAnswerOnly && hasLiveLogs) {
        const logsWindow = document.createElement('div');
        logsWindow.className = 'live-logs-window';

        let logsContent = '';
        if (data.service_health && Object.keys(data.service_health).length > 0) {
            logsContent += JSON.stringify(data.service_health, null, 2);
        }
        if (data.live_logs && data.live_logs.trim()) {
            if (logsContent) logsContent += '\n\n';
            logsContent += data.live_logs.trim();
        }
        if (data.recent_deploys && data.recent_deploys.length > 0) {
            if (logsContent) logsContent += '\n\n=== Recent Deployments ===\n';
            logsContent += JSON.stringify(data.recent_deploys, null, 2);
        }

        const escapedLogs = logsContent.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        logsWindow.innerHTML = `
            <div class="code-block-header">
                <span class="code-block-lang">📋 LIVE DIAGNOSTICS</span>
                <button class="code-copy-btn" onclick="copyCodeBlock(this)" data-rawcode="${logsContent.replace(/"/g, '&quot;')}">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    Copy Logs
                </button>
            </div>
            <pre class="code-block-pre" style="max-height:320px;"><code>${escapedLogs}</code></pre>
        `;
        const contentState = ui.container.querySelector('.content-state');
        if (contentState) {
            answerCard ? answerCard.insertAdjacentElement('afterend', logsWindow) : contentState.appendChild(logsWindow);
        }
    }

    // ---------------------------------------------------------------
    // Reasoning, Fixes, Sources, grid-2 — HIDDEN for answer-only modes
    // ---------------------------------------------------------------
    const reasoningCard = ui.container.querySelector('.reasoning-card');
    const fixesCard     = ui.container.querySelector('.fixes-card');
    const sourcesCard   = ui.container.querySelector('.sources-card');
    const grid2         = ui.container.querySelector('.grid-2');

    if (isAnswerOnly) {
        if (reasoningCard) reasoningCard.style.display = 'none';
        if (fixesCard)     fixesCard.style.display     = 'none';
        if (sourcesCard)   sourcesCard.style.display   = 'none';
        if (grid2)         grid2.style.display         = 'none';
    } else {
        // --- Reasoning ---
        const hasReasoning = data.reasoning && data.reasoning.trim();
        if (reasoningCard) reasoningCard.style.display = hasReasoning ? '' : 'none';
        if (hasReasoning) ui.reasoningText.textContent = data.reasoning;

        // --- Suggested Fixes ---
        const hasFixes = data.suggested_fixes && data.suggested_fixes.length > 0;
        if (fixesCard) fixesCard.style.display = '';  // Always show for non-answer-only
        ui.fixesList.innerHTML = '';
        if (hasFixes) {
            data.suggested_fixes.forEach(fix => {
                const li = document.createElement('li');
                li.innerHTML = marked.parseInline(fix);
                ui.fixesList.appendChild(li);
            });
        } else {
            ui.fixesList.innerHTML = '<li style="opacity:0.5;">None identified</li>';
        }

        // --- Sources ---
        const hasSources = data.sources && data.sources.length > 0;
        if (sourcesCard) sourcesCard.style.display = '';  // Always show for non-answer-only
        ui.sourcesTags.innerHTML = '';
        if (hasSources) {
            data.sources.forEach(src => {
                const a = document.createElement('a');
                a.className = 'source-tag';
                let filename = src;
                if (filename.includes('\\')) filename = filename.split('\\').pop();
                if (filename.includes('/')) filename = filename.split('/').pop();
                const match = src.match(/\(([^)]+\.(?:md|txt|docx|pdf))\)$/i) || src.match(/^([^ ]+\.(?:md|txt|docx|pdf))$/i);
                if (match && match[1]) filename = match[1];
                else if (!src.includes('.')) filename = null;
                a.textContent = filename || src;
                if (filename) {
                    a.href = `${API_BASE_URL}/document/${filename}`;
                    a.download = filename;
                    a.target = '_blank';
                    a.title = 'Click to download raw postmortem';
                    a.style.cssText = 'text-decoration:none;cursor:pointer;';
                } else {
                    a.style.cursor = 'default';
                }
                ui.sourcesTags.appendChild(a);
            });
        } else {
            const span = document.createElement('span');
            span.className = 'tag source-tag';
            span.textContent = 'No sources used';
            span.style.cssText = 'opacity:0.5;cursor:default;';
            ui.sourcesTags.appendChild(span);
        }

        // --- grid-2 visibility: hide only if BOTH reasoning AND fixes are hidden ---
        if (grid2) {
            const rHidden = reasoningCard && reasoningCard.style.display === 'none';
            const fHidden = fixesCard && fixesCard.style.display === 'none';
            grid2.style.display = (rHidden && fHidden) ? 'none' : '';
        }
    }

    // ---------------------------------------------------------------
    // Human approval box
    // ---------------------------------------------------------------
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
