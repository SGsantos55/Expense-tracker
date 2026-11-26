document.addEventListener('DOMContentLoaded', () => {
    const periodForm = document.querySelector('[data-period-form]');
    const periodSelect = document.querySelector('[data-period-select]');
    const customRange = document.querySelector('[data-custom-range]');

    if (periodForm && periodSelect && customRange) {
        const dateInputs = customRange.querySelectorAll('input[type="date"]');
        const syncCustomRange = () => {
            const isCustom = periodSelect.value === 'custom';
            customRange.hidden = !isCustom;
            dateInputs.forEach((input) => {
                input.required = isCustom;
                input.disabled = !isCustom;
            });
        };
        periodSelect.addEventListener('change', syncCustomRange);
        periodForm.addEventListener('submit', syncCustomRange);
        syncCustomRange();
    }

    document.querySelectorAll('[data-summary-submit]').forEach((button) => {
        const form = button.closest('form');
        if (!form) return;
        form.addEventListener('submit', () => {
            button.disabled = true;
            button.textContent = 'Generating…';
        });
    });

    const chatPanel = document.querySelector('[data-chat-panel]');
    if (!chatPanel || chatPanel.dataset.aiEnabled !== 'true') return;

    const thread = chatPanel.querySelector('[data-chat-thread]');
    const form = chatPanel.querySelector('[data-chat-form]');
    const input = chatPanel.querySelector('#chat-message');
    const submit = chatPanel.querySelector('[data-chat-submit]');
    const status = chatPanel.querySelector('[data-chat-status]');
    const count = chatPanel.querySelector('[data-chat-count]');
    const suggestions = chatPanel.querySelector('[data-chat-suggestions]');
    const setStatus = (text) => {
        if (status) status.textContent = text || '';
    };

    const removeEmptyState = () => {
        const empty = thread && thread.querySelector('[data-chat-empty]');
        if (empty) empty.remove();
    };

    const appendMessage = (role, text) => {
        if (!thread) return;
        removeEmptyState();
        const article = document.createElement('article');
        article.className = `chat-message is-${role}`;
        const label = document.createElement('span');
        label.className = 'chat-message-label';
        label.textContent = role === 'user' ? 'You' : 'Assistant';
        const paragraph = document.createElement('p');
        paragraph.className = 'chat-message-text';
        paragraph.textContent = text;
        article.append(label, paragraph);
        thread.appendChild(article);
        thread.scrollTop = thread.scrollHeight;
    };

    const renderSuggestions = (items) => {
        if (!suggestions || !Array.isArray(items)) return;
        suggestions.replaceChildren();
        items.slice(0, 3).forEach((text) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'chat-suggestion';
            button.dataset.chatSuggestion = '';
            button.dataset.message = text;
            button.textContent = text;
            suggestions.appendChild(button);
        });
    };

    const updateCount = () => {
        if (count && input) count.textContent = `${input.value.length} / 500`;
    };

    if (input) input.addEventListener('input', updateCount);
    updateCount();

    if (suggestions) {
        suggestions.addEventListener('click', (event) => {
            const button = event.target.closest('[data-chat-suggestion]');
            if (!button || !input) return;
            input.value = button.dataset.message || '';
            updateCount();
            input.focus();
        });
    }

    if (form && input && submit) {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const message = input.value.trim();
            if (!message) return;

            const payload = {
                message,
                preset: form.elements.preset.value,
                date_from: form.elements.date_from.value,
                date_to: form.elements.date_to.value,
            };
            appendMessage('user', message);
            input.value = '';
            updateCount();
            submit.disabled = true;
            submit.textContent = 'Asking…';
            setStatus('Thinking…');

            try {
                const response = await fetch(chatPanel.dataset.chatUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    setStatus(data.error || 'Could not answer that question.');
                    appendMessage('assistant', data.error || 'Could not answer that question.');
                    return;
                }
                appendMessage('assistant', data.answer || 'No answer was returned.');
                renderSuggestions(data.follow_up_suggestions);
                setStatus(data.degraded ? 'Answered with a safe fallback.' : 'Answered using current period data.');
            } catch (error) {
                setStatus('Could not reach the chat service.');
                appendMessage('assistant', 'Could not reach the chat service.');
            } finally {
                submit.disabled = false;
                submit.textContent = 'Ask';
            }
        });
    }
});
