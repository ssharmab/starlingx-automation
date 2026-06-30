// SPDX-License-Identifier: Apache-2.0
// Agent Chat UI — with Debug Mode support
"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let conversations = [];
let activeConversationId = null;
let debugMode = false;
let debugPollInterval = null;
let currentPendingDecisionId = null;

// ---------------------------------------------------------------------------
// DOM elements
// ---------------------------------------------------------------------------

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const chatMessages = document.getElementById("chat-messages");
const chatHistory = document.getElementById("chat-history");
const newChatBtn = document.getElementById("new-chat-btn");
const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebar = document.getElementById("sidebar");

// Debug elements
const debugToggleBtn = document.getElementById("debug-toggle-btn");
const debugToggleLabel = document.getElementById("debug-toggle-label");
const debugIndicator = document.getElementById("debug-indicator");
const debugPanel = document.getElementById("debug-panel");
const debugPrompt = document.getElementById("debug-prompt");
const debugToolInput = document.getElementById("debug-tool");
const debugReasonInput = document.getElementById("debug-reason");
const debugParamsInput = document.getElementById("debug-params");
const debugSubmitBtn = document.getElementById("debug-submit-btn");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateId() {
    return "conv-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
}

function getActiveConversation() {
    return conversations.find(function (c) { return c.id === activeConversationId; });
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Debug Mode
// ---------------------------------------------------------------------------

function toggleDebugMode() {
    debugMode = !debugMode;
    debugToggleLabel.textContent = "Debug: " + (debugMode ? "ON" : "OFF");
    debugToggleBtn.classList.toggle("active", debugMode);
    debugIndicator.style.display = debugMode ? "inline-block" : "none";

    if (debugMode) {
        startDebugPolling();
    } else {
        stopDebugPolling();
        debugPanel.style.display = "none";
    }
}

function startDebugPolling() {
    if (debugPollInterval) return;
    debugPollInterval = setInterval(pollForPendingDecisions, 1000);
}

function stopDebugPolling() {
    if (debugPollInterval) {
        clearInterval(debugPollInterval);
        debugPollInterval = null;
    }
}

async function pollForPendingDecisions() {
    try {
        const response = await fetch("/api/debug/pending");
        if (!response.ok) return;

        const pending = await response.json();

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

function showDebugPanel(decision) {
    // Only reset fields if this is a new decision
    if (currentPendingDecisionId === decision.id) {
        return;
    }
    currentPendingDecisionId = decision.id;
    debugPrompt.textContent = decision.prompt;
    debugPanel.style.display = "block";
    debugToolInput.value = "";
    debugReasonInput.value = "";
    debugParamsInput.value = "{}";
    debugToolInput.focus();
    scrollToBottom();
}

async function submitDebugDecision() {
    if (!currentPendingDecisionId) return;

    const tool = debugToolInput.value.trim();
    const reason = debugReasonInput.value.trim();
    let parameters = {};

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
                tool: tool,
                reason: reason,
                parameters: parameters,
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
                    content: "[Debug Decision] tool=" + tool + ", reason=" + reason,
                    timestamp: new Date().toISOString(),
                });
                renderMessages();
            }
        }
    } catch (e) {
        alert("Failed to submit decision: " + e);
    }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderMessages() {
    const conversation = getActiveConversation();

    if (!conversation || conversation.messages.length === 0) {
        chatMessages.innerHTML =
            '<div class="welcome-message">' +
            "<h2>Welcome to Automation for Deployments</h2>" +
            "<h3>Currently only limited to a very small number of usecases.</h3>" +
            "<p>Send a message to get started.</p>" +
            "</div>";
        return;
    }

    chatMessages.innerHTML = conversation.messages
        .map(function (msg) {
            return (
                '<div class="message">' +
                '<div class="message-avatar ' + msg.role + '">' +
                (msg.role === "user" ? "Y" : "A") +
                "</div>" +
                '<div class="message-content">' + escapeHtml(msg.content) + "</div>" +
                "</div>"
            );
        })
        .join("");

    scrollToBottom();
}

function renderHistory() {
    chatHistory.innerHTML = conversations
        .map(function (conv) {
            return (
                '<div class="history-item ' +
                (conv.id === activeConversationId ? "active" : "") +
                '" data-id="' + conv.id + '">' +
                escapeHtml(conv.title) +
                "</div>"
            );
        })
        .join("");

    chatHistory.querySelectorAll(".history-item").forEach(function (el) {
        el.addEventListener("click", function () {
            var id = el.dataset.id;
            switchConversation(id);
        });
    });
}

// ---------------------------------------------------------------------------
// Conversation management
// ---------------------------------------------------------------------------

function createNewConversation() {
    var conv = {
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

function switchConversation(id) {
    activeConversationId = id;
    renderMessages();
    renderHistory();
}

// ---------------------------------------------------------------------------
// API communication
// ---------------------------------------------------------------------------

async function sendMessage(content) {
    let conversation = getActiveConversation();

    if (!conversation) {
        createNewConversation();
        conversation = getActiveConversation();
    }

    var userMsg = {
        role: "user",
        content: content,
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
            throw new Error("HTTP " + response.status);
        }

        const data = await response.json();

        var assistantMsg = {
            role: "assistant",
            content: data.reply,
            timestamp: data.timestamp,
        };
        conversation.messages.push(assistantMsg);
    } catch (error) {
        var errorMsg = {
            role: "assistant",
            content: "Error: Could not reach the server. " + error,
            timestamp: new Date().toISOString(),
        };
        conversation.messages.push(errorMsg);
    }

    renderMessages();
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

chatInput.addEventListener("input", function () {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + "px";
    sendBtn.disabled = chatInput.value.trim().length === 0;
});

chatForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var content = chatInput.value.trim();
    if (!content) return;

    chatInput.value = "";
    chatInput.style.height = "auto";
    sendBtn.disabled = true;
    sendMessage(content);
});

chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit"));
    }
});

newChatBtn.addEventListener("click", function () {
    createNewConversation();
});

sidebarToggle.addEventListener("click", function () {
    sidebar.classList.toggle("hidden");
});

// Debug toggle button
debugToggleBtn.addEventListener("click", function () {
    toggleDebugMode();
});

// Debug submit button
debugSubmitBtn.addEventListener("click", function () {
    submitDebugDecision();
});

// Allow Enter in debug tool/reason fields to submit
debugToolInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
        e.preventDefault();
        submitDebugDecision();
    }
});

debugReasonInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
        e.preventDefault();
        submitDebugDecision();
    }
});

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

createNewConversation();
