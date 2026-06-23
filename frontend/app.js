// ==========================================================================
// Application Configuration & State
// ==========================================================================
const API_BASE = "http://localhost:8000";
const USER_ID = "default_user";
const APP_NAME = "app";

let currentSessionId = null;
let sessions = [];

// DOM Elements
const sidebar = document.querySelector(".sidebar");
const sessionsList = document.getElementById("sessions-list");
const newChatBtn = document.getElementById("new-chat-btn");
const clearSessionBtn = document.getElementById("clear-session-btn");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const messagesContainer = document.getElementById("messages-container");
const welcomePanel = document.getElementById("welcome-panel");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const suggestionCards = document.querySelectorAll(".suggestion-card");

// Configure marked.js options
if (window.marked) {
    marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: false,
        mangle: false
    });
}

// ==========================================================================
// Initialization & Event Listeners
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    fetchSessions();
    setupEventListeners();
});

function setupEventListeners() {
    newChatBtn.addEventListener("click", () => startNewConversation());
    clearSessionBtn.addEventListener("click", () => clearCurrentConversation());
    themeToggleBtn.addEventListener("click", () => toggleTheme());
    
    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const text = messageInput.value.trim();
        if (text) {
            handleSendMessage(text);
            messageInput.value = "";
        }
    });

    // Suggestion prompt cards
    suggestionCards.forEach(card => {
        card.addEventListener("click", () => {
            const prompt = card.getAttribute("data-prompt");
            if (prompt) {
                handleSendMessage(prompt);
            }
        });
    });
}

// ==========================================================================
// Session & API Management
// ==========================================================================

// Fetch all sessions from the database
async function fetchSessions() {
    try {
        const response = await fetch(`${API_BASE}/apps/${APP_NAME}/users/${USER_ID}/sessions`);
        if (!response.ok) throw new Error("Failed to load sessions");
        
        sessions = await response.ok ? await response.json() : [];
        // Sort sessions by lastUpdateTime descending
        sessions.sort((a, b) => b.lastUpdateTime - a.lastUpdateTime);
        
        renderSessionsList();
    } catch (err) {
        console.error("Error fetching sessions:", err);
    }
}

// Render the sidebar sessions
function renderSessionsList() {
    sessionsList.innerHTML = "";
    
    if (sessions.length === 0) {
        sessionsList.innerHTML = `<li class="session-title" style="padding: 12px; text-align: center; color: var(--text-muted);">No history found</li>`;
        return;
    }
    
    sessions.forEach(session => {
        const li = document.createElement("li");
        li.className = `session-item ${session.id === currentSessionId ? "active" : ""}`;
        li.setAttribute("data-id", session.id);
        
        // Find first user message for title, or fallback to id
        let title = "Kate's Portfolio Chat";
        if (session.events && session.events.length > 0) {
            const firstUserEvent = session.events.find(e => e.content && e.content.role === "user");
            if (firstUserEvent && firstUserEvent.content.parts && firstUserEvent.content.parts[0]?.text) {
                title = firstUserEvent.content.parts[0].text;
            }
        }
        
        li.innerHTML = `
            <div class="session-title-wrapper">
                <i class="fa-solid fa-message"></i>
                <span class="session-title" title="${title}">${title}</span>
            </div>
            <button class="delete-session-btn" title="Delete conversation">
                <i class="fa-solid fa-trash"></i>
            </button>
        `;
        
        // Click to load session
        li.addEventListener("click", (e) => {
            if (e.target.closest(".delete-session-btn")) {
                e.stopPropagation();
                handleDeleteSession(session.id);
            } else {
                selectSession(session.id);
            }
        });
        
        sessionsList.appendChild(li);
    });
}

// Create a new session
async function createNewSessionOnBackend() {
    try {
        const response = await fetch(`${API_BASE}/apps/${APP_NAME}/users/${USER_ID}/sessions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({})
        });
        if (!response.ok) throw new Error("Failed to create session");
        const session = await response.json();
        return session.id;
    } catch (err) {
        console.error("Error creating session:", err);
        // Fallback to client-generated ID
        return crypto.randomUUID();
    }
}

// Triggered by the "New Conversation" button
async function startNewConversation() {
    currentSessionId = await createNewSessionOnBackend();
    welcomePanel.style.display = "flex";
    
    // Clear all previous message nodes
    const bubbleRows = messagesContainer.querySelectorAll(".message-row, .tool-badge");
    bubbleRows.forEach(row => row.remove());
    
    await fetchSessions();
}

// Select and load conversation history
async function selectSession(sessionId) {
    currentSessionId = sessionId;
    
    // Update active highlight
    document.querySelectorAll(".session-item").forEach(item => {
        item.classList.toggle("active", item.getAttribute("data-id") === sessionId);
    });
    
    welcomePanel.style.display = "none";
    
    // Clear chat pane
    const bubbleRows = messagesContainer.querySelectorAll(".message-row, .tool-badge");
    bubbleRows.forEach(row => row.remove());
    
    // Show typing loader while loading history
    const loadingIndicator = appendTypingIndicator();
    scrollToBottom();
    
    try {
        const response = await fetch(`${API_BASE}/apps/${APP_NAME}/users/${USER_ID}/sessions/${sessionId}`);
        if (!response.ok) throw new Error("Failed to load session details");
        
        const fullSession = await response.json();
        loadingIndicator.remove();
        
        // Render event logs
        if (fullSession.events && fullSession.events.length > 0) {
            fullSession.events.forEach(event => {
                const role = event.content?.role || (event.author === "user" ? "user" : "model");
                
                // Check for tool calls
                if (event.content && event.content.parts) {
                    event.content.parts.forEach(part => {
                        if (part.functionCall) {
                            renderToolCallBadge(part.functionCall.name, part.functionCall.args);
                        }
                    });
                }
                
                // Render text messages
                let textContent = "";
                if (event.content && event.content.parts) {
                    textContent = event.content.parts
                        .filter(p => p.text)
                        .map(p => p.text)
                        .join("");
                } else if (event.output && typeof event.output === "string") {
                    textContent = event.output;
                }
                
                if (textContent.trim()) {
                    appendMessageBubble(textContent, role === "user" ? "user" : "agent");
                }
            });
        }
    } catch (err) {
        console.error("Error loading session:", err);
        loadingIndicator.remove();
        appendMessageBubble("Could not load conversation history.", "agent");
    }
    
    scrollToBottom();
}

// Delete a session
async function handleDeleteSession(sessionId) {
    if (!confirm("Are you sure you want to delete this conversation?")) return;
    
    try {
        const response = await fetch(`${API_BASE}/apps/${APP_NAME}/users/${USER_ID}/sessions/${sessionId}`, {
            method: "DELETE"
        });
        if (!response.ok) throw new Error("Failed to delete session");
        
        if (currentSessionId === sessionId) {
            currentSessionId = null;
            welcomePanel.style.display = "flex";
            const bubbleRows = messagesContainer.querySelectorAll(".message-row, .tool-badge");
            bubbleRows.forEach(row => row.remove());
        }
        
        await fetchSessions();
    } catch (err) {
        console.error("Error deleting session:", err);
    }
}

// Clear currently selected conversation
async function clearCurrentConversation() {
    if (currentSessionId) {
        await handleDeleteSession(currentSessionId);
    } else {
        const bubbleRows = messagesContainer.querySelectorAll(".message-row, .tool-badge");
        bubbleRows.forEach(row => row.remove());
    }
}

// ==========================================================================
// Message Handling & Stream Rendering
// ==========================================================================

// Handle sending message
async function handleSendMessage(messageText) {
    welcomePanel.style.display = "none";
    
    // 1. Ensure we have an active session
    if (!currentSessionId) {
        currentSessionId = await createNewSessionOnBackend();
    }
    
    // 2. Render user bubble immediately
    appendMessageBubble(messageText, "user");
    scrollToBottom();
    
    // 3. Render typing indicator
    const typingIndicator = appendTypingIndicator();
    scrollToBottom();
    
    try {
        // 4. Send request to backend /run-multi-agent (multi-agent orchestration)
        const response = await fetch(`${API_BASE}/run-multi-agent`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: messageText
            })
        });
        
        // Remove typing indicator
        typingIndicator.remove();
        
        if (!response.ok) {
            throw new Error("Backend response error");
        }
        
        const result = await response.json();
        
        // 5. Handle response from multi-agent orchestration
        if (result.status === "success" && result.answer) {
            // Display the agent's synthesized answer
            appendMessageBubble(result.answer, "agent");
            
            // Optionally show agent runs count (metadata)
            if (result.agent_runs_count && result.agent_runs_count > 0) {
                console.log(`✓ Orchestrated with ${result.agent_runs_count} agent(s) (question_id: ${result.question_id})`);
            }
        } else {
            appendMessageBubble(result.message || "I couldn't fetch an answer. Please try again.", "agent");
        }
        
    } catch (err) {
        console.error("Error running agent:", err);
        typingIndicator.remove();
        appendMessageBubble("Sorry, I encountered an error communicating with the agent server. Please make sure the backend is running.", "agent");
    }
    
    scrollToBottom();
    await fetchSessions();
}

// Append a message bubble to the messages pane
function appendMessageBubble(text, sender) {
    const row = document.createElement("div");
    row.className = `message-row ${sender}`;
    
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    
    if (sender === "agent" && window.marked) {
        // Parse markdown for agent replies
        bubble.innerHTML = marked.parse(text);
    } else {
        bubble.textContent = text;
    }
    
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    return row;
}

// Append tool execution badge
function renderToolCallBadge(toolName, args) {
    const badge = document.createElement("div");
    badge.className = "tool-badge";
    
    let argsStr = "";
    if (args && Object.keys(args).length > 0) {
        argsStr = Object.entries(args)
            .map(([k, v]) => `${k}="${v}"`)
            .join(", ");
    }
    
    badge.innerHTML = `<i class="fa-solid fa-gears"></i> Running tool: <code>${toolName}(${argsStr})</code>`;
    messagesContainer.appendChild(badge);
    return badge;
}

// Append typing loader
function appendTypingIndicator() {
    const row = document.createElement("div");
    row.className = "message-row agent";
    
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    
    const indicator = document.createElement("div");
    indicator.className = "typing-indicator";
    indicator.innerHTML = `
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
    `;
    
    bubble.appendChild(indicator);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    return row;
}

// Helper to scroll message area to the bottom
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// ==========================================================================
// Theme / Styling Management
// ==========================================================================
function initTheme() {
    const activeTheme = localStorage.getItem("portfolio-theme") || "dark";
    document.documentElement.setAttribute("data-theme", activeTheme);
    updateThemeToggleUI(activeTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const newTheme = currentTheme === "dark" ? "light" : "dark";
    
    document.documentElement.setAttribute("data-theme", newTheme);
    localStorage.setItem("portfolio-theme", newTheme);
    updateThemeToggleUI(newTheme);
}

function updateThemeToggleUI(theme) {
    const icon = themeToggleBtn.querySelector("i");
    const text = themeToggleBtn.querySelector("span");
    
    if (theme === "dark") {
        icon.className = "fa-solid fa-sun";
        text.textContent = "Light Mode";
    } else {
        icon.className = "fa-solid fa-moon";
        text.textContent = "Dark Mode";
    }
}
