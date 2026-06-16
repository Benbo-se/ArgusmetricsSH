/**
 * JobbSynk AI Chatbot - Vanilla JavaScript
 * Version: 1.0
 * Date: 2025-10-28
 */

(function() {
  'use strict';

  // Chatbot state
  const state = {
    isOpen: false,
    messages: [],
    isLoading: false,
    sessionId: null
  };

  // Initialize session ID
  function initSession() {
    let id = localStorage.getItem('argusmetricsChatSession');
    if (!id) {
      id = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
      localStorage.setItem('argusmetricsChatSession', id);
    }
    state.sessionId = id;

    // Load chat history
    const saved = localStorage.getItem('argusmetricsChatHistory');
    if (saved) {
      try {
        state.messages = JSON.parse(saved);
      } catch (e) {
        console.error('Failed to load chat history:', e);
        state.messages = [];
      }
    }
  }

  // Save chat history
  function saveHistory() {
    if (state.messages.length > 0) {
      localStorage.setItem('argusmetricsChatHistory', JSON.stringify(state.messages));
    }
  }

  // Format timestamp
  function formatTime(date) {
    return new Date(date).toLocaleTimeString('sv-SE', {
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  // Simple markdown link parser
  function parseMarkdownLinks(text) {
    // Convert [text](url) to <a href="url">text</a>
    return text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="chatbot-link">$1</a>');
  }

  // Create message element
  function createMessageElement(msg) {
    const div = document.createElement('div');
    div.className = `chatbot-message ${msg.role}`;

    const bubble = document.createElement('div');
    bubble.className = 'chatbot-message-bubble';

    // Parse markdown links and preserve line breaks
    const htmlContent = parseMarkdownLinks(msg.content).replace(/\n/g, '<br>');
    bubble.innerHTML = htmlContent;

    // Add feedback buttons for bot messages
    if (msg.role === 'bot' && msg.logId && !msg.isError) {
      const feedback = document.createElement('div');
      feedback.className = 'chatbot-feedback';

      const thumbsUp = document.createElement('button');
      thumbsUp.innerHTML = '👍';
      thumbsUp.title = 'Hjälpsamt svar';
      thumbsUp.onclick = () => submitFeedback(msg.logId, true);

      const thumbsDown = document.createElement('button');
      thumbsDown.innerHTML = '👎';
      thumbsDown.title = 'Inte hjälpsamt';
      thumbsDown.onclick = () => submitFeedback(msg.logId, false);

      feedback.appendChild(thumbsUp);
      feedback.appendChild(thumbsDown);
      bubble.appendChild(feedback);
    }

    const time = document.createElement('div');
    time.className = 'chatbot-message-time';
    time.textContent = formatTime(msg.timestamp);

    div.appendChild(bubble);
    div.appendChild(time);

    return div;
  }

  // Create typing indicator
  function createTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'chatbot-typing';
    div.id = 'typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    return div;
  }

  // Render messages
  function renderMessages() {
    const container = document.getElementById('chatbot-messages');
    if (!container) return;

    container.innerHTML = '';

    state.messages.forEach(msg => {
      container.appendChild(createMessageElement(msg));
    });

    // Show typing indicator if loading
    if (state.isLoading) {
      container.appendChild(createTypingIndicator());
    }

    // Scroll to bottom
    container.scrollTop = container.scrollHeight;
  }

  // Send message to API
  async function sendMessage(userInput) {
    if (!userInput.trim() || state.isLoading) return;

    const userMessage = {
      role: 'user',
      content: userInput.trim(),
      timestamp: new Date().toISOString()
    };

    state.messages.push(userMessage);
    state.isLoading = true;
    renderMessages();
    saveHistory();

    try {
      const response = await fetch('/api/v1/chatbot/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userInput.trim(),
          sessionId: state.sessionId,
          context: {
            currentPage: window.location.pathname,
            conversationHistory: state.messages.slice(-6) // Last 3 exchanges
          }
        })
      });

      const data = await response.json();

      if (response.ok) {
        const botMessage = {
          role: 'bot',
          content: data.answer,
          timestamp: new Date().toISOString(),
          logId: data.logId
        };
        state.messages.push(botMessage);
      } else if (response.status === 429 && data.detail && data.detail.demo_mode) {
        // Demo limit reached
        const demoLimitMessage = {
          role: 'bot',
          content: `🎉 ${data.detail.message}\n\n✨ Med ett gratis konto får du:\n• 10,000 pageviews/månad\n• Obegränsad AI-assistans (STARTER plan)\n• Full access till analytics\n• Email support\n\n[→ Skapa gratis konto nu!](${data.detail.signup_url})`,
          timestamp: new Date().toISOString(),
          isError: false,
          isDemoLimit: true
        };
        state.messages.push(demoLimitMessage);

        // Disable input
        const input = document.getElementById('chatbot-input');
        const submitBtn = document.querySelector('.chatbot-send');
        if (input) {
          input.disabled = true;
          input.placeholder = 'Demo limit nådd - skapa konto för att fortsätta';
        }
        if (submitBtn) {
          submitBtn.disabled = true;
        }
      } else {
        throw new Error(data.error || data.detail?.message || 'Något gick fel');
      }
    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage = {
        role: 'bot',
        content: 'Oj, något gick fel! Försök igen eller kontakta oss på redaekengren@protonmail.com',
        timestamp: new Date().toISOString(),
        isError: true
      };
      state.messages.push(errorMessage);
    } finally {
      state.isLoading = false;
      renderMessages();
      saveHistory();
    }
  }

  // Submit feedback
  async function submitFeedback(logId, helpful) {
    if (!logId) return;

    try {
      await fetch('/api/v1/chatbot/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ logId, helpful })
      });
    } catch (error) {
      console.error('Feedback error:', error);
    }
  }

  // Toggle chat window
  function toggleChat(open) {
    state.isOpen = open;
    const bubble = document.getElementById('chatbot-bubble');
    const window = document.getElementById('chatbot-window');

    if (state.isOpen) {
      bubble.style.display = 'none';
      window.style.display = 'flex';

      // Add welcome message if first time
      if (state.messages.length === 0) {
        state.messages.push({
          role: 'bot',
          content: '👋 Hej! Jag är Argusmetrics AI-assistent. Hur kan jag hjälpa dig med din analytics idag?',
          timestamp: new Date().toISOString()
        });
        renderMessages();
        saveHistory();
      }

      // Focus input
      setTimeout(() => {
        const input = document.getElementById('chatbot-input');
        if (input) input.focus();
      }, 100);
    } else {
      bubble.style.display = 'flex';
      window.style.display = 'none';
    }
  }

  // Clear chat history
  function clearHistory() {
    if (confirm('Vill du rensa chatthistoriken?')) {
      state.messages = [{
        role: 'bot',
        content: '👋 Hej! Jag är Argusmetrics AI-assistent. Hur kan jag hjälpa dig med din analytics idag?',
        timestamp: new Date().toISOString()
      }];
      localStorage.removeItem('argusmetricsChatHistory');
      renderMessages();
    }
  }

  // Handle form submit
  function handleSubmit(e) {
    e.preventDefault();
    const input = document.getElementById('chatbot-input');
    if (!input) return;

    const message = input.value.trim();
    if (message) {
      sendMessage(message);
      input.value = '';
      input.style.height = 'auto';
    }
  }

  // Handle quick question
  function handleQuickQuestion(question) {
    const input = document.getElementById('chatbot-input');
    if (input) {
      input.value = question;
      input.focus();
    }
  }

  // Auto-resize textarea
  function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
  }

  // Initialize chatbot when DOM is ready
  function init() {
    initSession();

    // Create chatbot HTML
    const chatbotHTML = `
      <!-- Floating Bubble -->
      <button id="chatbot-bubble" class="chatbot-bubble" aria-label="Öppna chat">
        <img src="/static/img/favicon.png" alt="Chatbot" class="chatbot-avatar-img">
        <span class="chatbot-pulse"></span>
      </button>

      <!-- Chat Window -->
      <div id="chatbot-window" class="chatbot-window" style="display: none;">
        <!-- Header -->
        <div class="chatbot-header">
          <div class="chatbot-header-content">
            <img src="/static/img/favicon.png" alt="Chatbot" class="chatbot-avatar-header">
            <div>
              <h3>Argusmetrics Assistent</h3>
              <p class="chatbot-status">
                <span class="status-dot"></span> Online
              </p>
            </div>
          </div>
          <div class="chatbot-header-actions">
            <button class="chatbot-action-btn" id="clear-history-btn" aria-label="Rensa historik" title="Rensa historik">
              🗑️
            </button>
            <button class="chatbot-close" id="close-chat-btn" aria-label="Stäng chat">
              ✕
            </button>
          </div>
        </div>

        <!-- Messages -->
        <div id="chatbot-messages" class="chatbot-messages"></div>

        <!-- Input Form -->
        <form id="chatbot-form" class="chatbot-input-container">
          <textarea
            id="chatbot-input"
            class="chatbot-input"
            placeholder="Skriv din fråga..."
            rows="1"
            maxlength="500"
          ></textarea>
          <button type="submit" class="chatbot-send" aria-label="Skicka meddelande">
            ➤
          </button>
        </form>

        <!-- Quick Questions (only show on first message) -->
        <div id="quick-questions" class="chatbot-quick-questions" style="display: none;">
          <p>Vanliga frågor:</p>
          <button type="button" class="quick-q" data-question="Hur fungerar spårningen?">
            📊 Hur fungerar spårningen?
          </button>
          <button type="button" class="quick-q" data-question="Vad är skillnaden mot Plausible?">
            ⭐ Skillnad mot Plausible?
          </button>
          <button type="button" class="quick-q" data-question="Hur skyddar ni min integritet?">
            💡 Integritetsskydd?
          </button>
        </div>
      </div>
    `;

    // Insert chatbot into page
    document.body.insertAdjacentHTML('beforeend', chatbotHTML);

    // Event listeners
    document.getElementById('chatbot-bubble').addEventListener('click', () => toggleChat(true));
    document.getElementById('close-chat-btn').addEventListener('click', () => toggleChat(false));
    document.getElementById('clear-history-btn').addEventListener('click', clearHistory);
    document.getElementById('chatbot-form').addEventListener('submit', handleSubmit);

    // Auto-resize textarea
    const input = document.getElementById('chatbot-input');
    input.addEventListener('input', (e) => autoResize(e.target));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e);
      }
    });

    // Quick questions
    document.querySelectorAll('.quick-q').forEach(btn => {
      btn.addEventListener('click', () => {
        handleQuickQuestion(btn.dataset.question);
      });
    });

    // Show quick questions only on first message
    const observer = new MutationObserver(() => {
      const quickQuestions = document.getElementById('quick-questions');
      if (state.messages.length === 1) {
        quickQuestions.style.display = 'flex';
      } else {
        quickQuestions.style.display = 'none';
      }
    });

    observer.observe(document.getElementById('chatbot-messages'), {
      childList: true
    });

    // Initial render if history exists
    if (state.messages.length > 0) {
      renderMessages();
    }
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose functions globally if needed
  window.JobbSynkChat = {
    open: () => toggleChat(true),
    close: () => toggleChat(false),
    clear: clearHistory
  };
})();
