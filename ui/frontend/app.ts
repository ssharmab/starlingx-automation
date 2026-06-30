// SPDX-License-Identifier: Apache-2.0
/**
 * Agent Chat UI — Frontend TypeScript
 *
 * Handles chat interaction, message rendering, conversation history,
 * debug mode with human-in-the-loop decisions, and communication
 * with the FastAPI backend.
 */

interface ChatMessage {
    role: "user" | "assistant";
    content: string;
    timestamp: string;
}

interface Conversation {
    id: string;
    title: string;
    messages: ChatMessage[];
}

interface ChatResponse {
    reply: string;
    conversation_id: string;
    timestamp: string;
}

interface PendingDecision {
    id: string;
    prompt: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let conversations: Conversation[] = [];
let activeConversationId: string | null = null;
let debugMode = false;
let debugPollInterval: number | null = null;
let currentPendingDecisionId: string | null = null;

// ---------------------------------------------------------------------------
// DOM elements
// ---------------------------------------------------------------------------

const chatForm = document.getElementById("chat-form") as HTMLFormElement;
const chatInput = document.getElementById("chat-input") as HTMLTextAreaElement;
const sendBtn = document.getElementById("send-btn") as HTMLButtonElement;
const chatMessages = document.getElementById("chat-messages") as HTMLDivElement;
const chatHistory = document.getElementById("chat-history") as HTMLDivElement;
const newChatBtn = document.getElementById("new-chat-btn") as HTMLButtonElement;
const sidebarToggle = document.getElementById("sidebar-toggle") as HTMLButtonElement;
const sidebar = document.getElementById("sidebar") as HTMLElement;

// Debug elements
const debugToggleBtn = document.getElementById("debug-toggle-btn") as HTMLButtonElement;
const debugToggleLabel = document.getElementById("debug-toggle-label") as HTMLSpanElement;
const debugIndicator = document.getElementById("debug-indicator") as HTMLSpanElement;
const debugPanel = document.getElementById("debug-panel") as HTMLDivElement;
const debugPrompt = document.getElementById("debug-prompt") as HTMLParagraphElement;
const debugToolInput = document.getElementById("debug-tool") as HTMLInputElement;
const debugReasonInput = document.getElementById("debug-reason") as HTMLInputElement;
const debugParamsInput = document.getElementById("debug-params") as HTMLTextAreaElement;
const debugSubmitBtn = document.getElementById("debug-submit-btn") as HTMLButtonElement;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId(): string {
    return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function getActiveConversation(): Conversation | undefined {
    return conversations.find((c) => c.id === activeConversationId);
}

function scrollToBottom(): void {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Debug Mode
// ---------------------------------------------------------------------------

function toggleDebugMode(): void {
    debugMode = !debugMode;
    debugToggleLabel.textContent = `Debug: ${debugMode ? "ON" : "OFF"}`;
    debugToggleBtn.classList.toggle("active", debugMode);
    debugIndicator.style.display = debugMode ? "inline-block" : "none";

    if (debugMode) {
        startDebugPolling();
    } else {
        stopDebugPolling();
        debugPanel.style.display = "none";
    }
}

function startDebugPolling(): void {
    if (debugPollInterval) return;
    debugPollInterval = window.setInterval(pollForPendingDecisions, 1000);
}

function stopDebugPolling(): void {
    if (debugPollInterval) {
        clearInterval(debugPollInterval);
        debugPollInterval = null;
    }
}

async function pollForPendingDecisions(): Promise<void> {
    try {
        const response = await fetch("/api/debug/pending");
        if (!response.ok) return;

        const pending: PendingDecision[] = await response.json();

        if (pending.length > 0) {
            showDebugPanel(pending[0]);
        } else {
            debugPanel.style.display = "none";
            currentPendingDecisionId = null;
        }
    } catch (e) {
        // Silently ignore polling errors
    }
}

function showDebugPanel(decision: PendingDecision): void {
    currentPendingDecisionId = decision.id;
    debugPrompt.textContent = decision.prompt;
    debugPanel.style.display = "block";
    debugToolInput.value = "";
    debugReasonInput.value = "";
    debugParamsInput.value = "{}";
    debugToolInput.focus();
    scrollToBottom();
}

async function submitDebugDecision(): Promise<void> {
    if (!currentPendingDecisionId) return;

    const tool = debugToolInput.value.trim();
    const reason = debugReasonInput.value.trim();
    let parameters: Record<string, unknown> = {};

    if (!tool) {
        alert("Tool name is required.");
        return;
    }
    if (!reason) {
        alert("Reason is required.");
        return;
    }

    try {
        parameters = JSON.parse(debugParamsInput.value || "{}");
    } catch (e) {
        alert("Parameters must be valid JSON.");
        return;
    }

    try {
        const response = await fetch("/api/debug/respond", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                decision_id: currentPendingDecisionId,
                tool,
                reason,
                parameters,
            }),
        });

        if (response.ok) {
            debugPanel.style.display = "none";
            currentPendingDecisionId = null;

            // Add a message showing what was submitted
            const conversation = getActiveConversation();
            if (conversation) {
                conversation.messages.push({
                    role: "user",
                    content: `[Debug Decision] tool=${tool}, reason=${reason}`,
                    timestamp: new Date().toISOString(),
                });
                renderMessages();
            }
        }
    } catch (e) {
        alert(`Failed to submit decision: ${e}`);
    }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderMessages(): void {
    const conversation = getActiveConversation();

    if (!conversation || conversation.messages.length === 0) {
        chatMessages.innerHTML = `
            <div class="welcome-message">
                <h2>Welcome to Automation for Deployments</h2>
                <h3>Currently only limited to a very small number of usecases.</h3>
                <p>Send a message to get started.</p>
            </div>
        `;
        return;
    }

    chatMessages.innerHTML = conversation.messages
        .map(
            (msg) => `
        <div class="message">
            <div class="message-avatar ${msg.role}">
                ${msg.role === "user" ? "Y" : "A"}
            </div>
            <div class="message-content">${escapeHtml(msg.content)}</div>
        </div>
    `
        )
        .join("");

    scrollToBottom();
}

function renderHistory(): void {
    chatHistory.innerHTML = conversations
        .map(
            (conv) => `
        <div class="history-item ${conv.id === activeConversationId ? "active" : ""}"
             data-id="${conv.id}">
            ${escapeHtml(conv.title)}
        </div>
    `
        )
        .join("");

    chatHistory.querySelectorAll(".history-item").forEach((el) => {
        el.addEventListener("click", () => {
            const id = (el as HTMLElement).dataset.id!;
            switchConversation(id);
        });
    });
}

// ---------------------------------------------------------------------------
// Conversation management
// ---------------------------------------------------------------------------

function createNewConversation(): void {
    const conv: Conversation = {
        id: generateId(),
        title: "New Chat",
        messages: [],
    };
    conversations.unshift(conv);
    activeConversationId = conv.id;
    renderMessages();
    renderHistory();
    chatInput.focus();
}

function switchConversation(id: string): void {
    activeConversationId = id;
    renderMessages();
    renderHistory();
}

// ---------------------------------------------------------------------------
// API communication
// ---------------------------------------------------------------------------

async function sendMessage(content: string): Promise<void> {
    let conversation = getActiveConversation();

    if (!conversation) {
        createNewConversation();
        conversation = getActiveConversation()!;
    }

    const userMsg: ChatMessage = {
        role: "user",
        content,
        timestamp: new Date().toISOString(),
    };
    conversation.messages.push(userMsg);

    if (conversation.messages.length === 1) {
        conversation.title = content.slice(0, 40) + (content.length > 40 ? "..." : "");
        renderHistory();
    }

    renderMessages();

    // If debug mode is on, start polling immediately
    if (debugMode) {
        startDebugPolling();
    }

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: content,
                conversation_id: conversation.id,
                debug_mode: debugMode,
            }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data: ChatResponse = await response.json();

        const assistantMsg: ChatMessage = {
            role: "assistant",
            content: data.reply,
            timestamp: data.timestamp,
        };
        conversation.messages.push(assistantMsg);
    } catch (error) {
        const errorMsg: ChatMessage = {
            role: "assistant",
            content: `Error: Could not reach the server. ${error}`,
            timestamp: new Date().toISOString(),
        };
        conversation.messages.push(errorMsg);
    }

    renderMessages();
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + "px";
    sendBtn.disabled = chatInput.value.trim().length === 0;
});

chatForm.addEventListener("submit", (e: Event) => {
    e.preventDefault();
    const content = chatInput.value.trim();
    if (!content) return;

    chatInput.value = "";
    chatInput.style.height = "auto";
    sendBtn.disabled = true;
    sendMessage(content);
});

chatInput.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit"));
    }
});

newChatBtn.addEventListener("click", () => createNewConversation());

sidebarToggle.addEventListener("click", () => sidebar.classList.toggle("hidden"));

// Debug toggle button
debugToggleBtn.addEventListener("click", () => toggleDebugMode());

// Debug submit button
debugSubmitBtn.addEventListener("click", () => submitDebugDecision());

// Allow Enter in debug tool/reason fields to submit
debugToolInput.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter") {
        e.preventDefault();
        submitDebugDecision();
    }
});

debugReasonInput.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter") {
        e.preventDefault();
        submitDebugDecision();
    }
});

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

createNewConversation();
