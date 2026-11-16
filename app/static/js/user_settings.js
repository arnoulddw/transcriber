// app/static/js/user_settings.js
/* Handles interactions within the 'Manage API Keys' modal. */

const userSettingsLogPrefix = "[UserSettingsJS]"; // Prefix for console logs

// --- Modal State & Elements ---
let apiKeyModal = null;
let apiKeyModalOverlay = null;
let apiKeyModalPanel = null;
let apiKeyModalTriggers = [];
let apiKeyModalCloseButtons = [];
let previouslyFocusedElement = null;
let publicApiKeyStatusEl = null;
let publicApiKeyForm = null;
let publicApiKeyNameInput = null;
let publicApiKeyCreatedPanel = null;
let publicApiKeyValueInput = null;
let publicApiCopyBtn = null;
let publicApiCreateBtn = null;
let publicApiKeyListEl = null;
let lastGeneratedPublicApiKey = null;
let openRouterSuggestedMask = '';

function initializeApiKeyModalElements() {
    apiKeyModal = document.getElementById('apiKeyModal');
    apiKeyModalOverlay = document.getElementById('apiKeyModalOverlay');
    apiKeyModalPanel = document.getElementById('apiKeyModalPanel'); // Panel for focus trap
    apiKeyModalTriggers = Array.from(document.querySelectorAll('#apiKeysBtn, #apiKeysBtnMobile'));
    if (apiKeyModal) {
        apiKeyModalCloseButtons = Array.from(apiKeyModal.querySelectorAll('#apiKeyModalCloseButtonHeader, #apiKeyModalCloseButtonFooter'));
    }
    publicApiKeyStatusEl = document.getElementById('publicApiKeyStatus');
    publicApiKeyForm = document.getElementById('publicApiKeyForm');
    publicApiKeyNameInput = document.getElementById('publicApiKeyName');
    publicApiKeyCreatedPanel = document.getElementById('publicApiKeyCreatedPanel');
    publicApiKeyValueInput = document.getElementById('publicApiKeyValue');
    publicApiCopyBtn = document.getElementById('copyPublicApiKeyBtn');
    publicApiCreateBtn = document.getElementById('createPublicApiKeyBtn');
    publicApiKeyListEl = document.getElementById('publicApiKeyList');

    if (!apiKeyModal || !apiKeyModalOverlay || !apiKeyModalPanel) {
        window.logger.warn(userSettingsLogPrefix, "One or more API Key modal core elements not found.");
        return false;
    }
    if (apiKeyModalTriggers.length === 0 && window.IS_MULTI_USER) { // Only warn if multi-user and triggers expected
        window.logger.warn(userSettingsLogPrefix, "API Key trigger buttons not found.");
    }
    return true;
}

function getProviderKeyEntries(service) {
    const status = window.API_KEY_STATUS || {};
    if (status.provider_keys && Array.isArray(status.provider_keys[service])) {
        return status.provider_keys[service];
    }
    const legacyEntries = status[`${service}_keys`];
    if (Array.isArray(legacyEntries)) return legacyEntries;
    return service === 'openrouter' && Array.isArray(status.openrouter_keys)
        ? status.openrouter_keys
        : [];
}

function setApiKeySuggestion(force = false) {
    const serviceSelect = document.getElementById('apiKeyServiceSelect');
    const keyInput = document.getElementById('apiKeyInput');
    const modelInput = document.getElementById('apiKeyOpenrouterModel');
    if (!serviceSelect || !keyInput || !modelInput || !serviceSelect.value) return;

    const requestedModel = modelInput.value.trim();
    const entries = getProviderKeyEntries(serviceSelect.value);
    const suggestion = entries.find(entry =>
        requestedModel && (entry.model_name || entry.model_slug) === requestedModel
    ) || entries[0];
    const suffix = suggestion && (suggestion.last_three || suggestion.lastThree);
    const mask = suffix ? `***${suffix}` : '';

    if (!force && keyInput.value && keyInput.value !== openRouterSuggestedMask) return;
    openRouterSuggestedMask = mask;
    keyInput.type = mask ? 'text' : 'password';
    keyInput.value = mask;
}

// Kept as a compatibility alias for pages or tests that still call the old
// OpenRouter-specific helper.
function setOpenRouterApiKeySuggestion(force = false) {
    setApiKeySuggestion(force);
}

function updateModelSettings(service) {
    const modelInput = document.getElementById('apiKeyOpenrouterModel');
    const modelHint = document.getElementById('modelNameHint');
    if (!modelInput) return;

    const providerHints = {
        openai: {
            placeholder: 'gpt-4o-transcribe',
            text: 'Enter the OpenAI model name only, without the vendor prefix.',
        },
        assemblyai: {
            placeholder: 'universal',
            text: 'Enter the AssemblyAI model name only, without the vendor prefix.',
        },
        gemini: {
            placeholder: 'gemini-3.0-flash',
            text: 'Enter the Google model name only, without the vendor prefix.',
        },
        openrouter: {
            placeholder: 'google/gemini-3.7-flash',
            text: 'Enter the OpenRouter model as vendor/model.',
        },
    };
    const hint = providerHints[service] || {
        placeholder: 'gpt-4o-transcribe',
        text: 'Enter the model name exactly as shown by the provider.',
    };
    modelInput.placeholder = hint.placeholder;
    if (modelHint) modelHint.textContent = hint.text;
    setApiKeySuggestion(true);
}

// Compatibility alias used by older callers.
function updateOpenRouterModelSettings(service) {
    updateModelSettings(service);
}

const MODEL_PURPOSE_LABELS = {
    transcription: 'Transcription',
    llm: 'LLM',
    live: 'Live',
};

// Status badge shared by provider keys and public keys: same width so the
// "Configured" / "Not Configured" column lines up.
function createKeyStatusBadge(configured) {
    const status = document.createElement('span');
    status.className = configured
        ? 'inline-flex h-badge w-32 flex-none items-center justify-center gap-1 rounded-full bg-green-50 text-badge font-semibold text-success'
        : 'inline-flex h-badge w-32 flex-none items-center justify-center gap-1 rounded-full bg-amber-50 text-badge font-semibold text-warning';
    const icon = document.createElement('i');
    icon.className = 'material-icons text-hero leading-none';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = configured ? 'check_circle' : 'error';
    const text = document.createElement('span');
    text.textContent = configured ? 'Configured' : 'Not Configured';
    status.append(icon, text);
    return status;
}

function createModelPurposeBadges(purposes) {
    const badges = document.createElement('span');
    badges.className = 'inline-flex flex-wrap items-center gap-1';
    const normalized = Array.isArray(purposes) && purposes.length
        ? purposes
        : ['transcription'];
    normalized.forEach(purpose => {
        const label = MODEL_PURPOSE_LABELS[purpose] || MODEL_PURPOSE_LABELS.transcription;
        const badge = document.createElement('span');
        badge.className = 'badge badge-primary text-tag px-2';
        badge.textContent = label;
        badge.dataset.modelPurpose = purpose;
        badges.appendChild(badge);
    });
    return badges;
}

function appendModelLabel(content, modelName, purposes, providerLabel) {
    const model = document.createElement('span');
    model.className = 'text-sm font-medium text-text-strong';
    model.textContent = modelName;
    if (modelName === providerLabel) {
        content.append(model, createModelPurposeBadges(purposes));
        return;
    }
    const provider = document.createElement('span');
    provider.className = 'text-sm text-text-muted';
    provider.textContent = `· ${providerLabel}`;
    content.append(model, provider, createModelPurposeBadges(purposes));
}

function openApiKeyModalDialog() {
    if (!apiKeyModal || !apiKeyModalOverlay || !apiKeyModalPanel) {
        window.logger.error(userSettingsLogPrefix, "Cannot open API Key modal: core elements missing.");
        return;
    }
    previouslyFocusedElement = document.activeElement;

    apiKeyModal.classList.remove('hidden');
    apiKeyModalOverlay.classList.remove('hidden');
    apiKeyModalPanel.classList.remove('hidden'); // Ensure panel is also visible for transitions

    // Force reflow for transition
    void apiKeyModal.offsetWidth;

    apiKeyModal.classList.add('opacity-100');
    apiKeyModalOverlay.classList.add('opacity-100');
    apiKeyModalPanel.classList.add('opacity-100', 'scale-100');
    apiKeyModalPanel.classList.remove('opacity-0', 'scale-95');


    apiKeyModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden'; // Prevent background scroll

    fetchApiKeyStatus(); // Fetch status when modal opens

    // Focus trap
    const focusableElements = Array.from(
        apiKeyModalPanel.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
    ).filter(el => !el.disabled && !el.closest('.hidden'));

    if (focusableElements.length > 0) {
        focusableElements[0].focus();
    } else {
        apiKeyModalPanel.focus(); // Fallback
    }
    window.logger.info(userSettingsLogPrefix, "API Key modal opened.");
}
window.openApiKeyModalDialog = openApiKeyModalDialog;

function closeApiKeyModalDialog() {
    if (!apiKeyModal || !apiKeyModalOverlay || !apiKeyModalPanel) {
        window.logger.error(userSettingsLogPrefix, "Cannot close API Key modal: core elements missing.");
        return;
    }

    apiKeyModal.classList.remove('opacity-100');
    apiKeyModalOverlay.classList.remove('opacity-100');
    apiKeyModalPanel.classList.remove('opacity-100', 'scale-100');
    apiKeyModalPanel.classList.add('opacity-0', 'scale-95');


    apiKeyModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';

    setTimeout(() => {
        apiKeyModal.classList.add('hidden');
        apiKeyModalOverlay.classList.add('hidden');
        // apiKeyModalPanel.classList.add('hidden'); // Panel visibility controlled by parent
    }, 300); // Match transition duration

    if (previouslyFocusedElement) {
        previouslyFocusedElement.focus();
        previouslyFocusedElement = null;
    }
    window.logger.info(userSettingsLogPrefix, "API Key modal closed.");
}


document.addEventListener('DOMContentLoaded', function() {
    if (!initializeApiKeyModalElements()) {
        window.logger.warn(userSettingsLogPrefix, "API Key modal setup skipped due to missing elements.");
        return;
    }

    apiKeyModalTriggers.forEach(trigger => {
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            openApiKeyModalDialog();
        });
    });

    apiKeyModalCloseButtons.forEach(button => {
        button.addEventListener('click', closeApiKeyModalDialog);
    });

    if (apiKeyModalOverlay) {
        apiKeyModalOverlay.addEventListener('click', closeApiKeyModalDialog);
    }

    if (publicApiKeyForm) {
        publicApiKeyForm.addEventListener('submit', handleGeneratePublicApiKey);
    }
    if (publicApiCreateBtn) {
        publicApiCreateBtn.addEventListener('click', handleGeneratePublicApiKey);
    }
    if (publicApiCopyBtn) {
        publicApiCopyBtn.addEventListener('click', copyPublicApiKeyToClipboard);
    }
    if (publicApiKeyListEl) {
        publicApiKeyListEl.addEventListener('click', function(event) {
            const revokeButton = event.target.closest('.revoke-public-key-btn');
            if (revokeButton) {
                event.preventDefault();
                handleRevokePublicApiKey(revokeButton);
            }
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && apiKeyModal && !apiKeyModal.classList.contains('hidden')) {
            closeApiKeyModalDialog();
        }
        // Basic focus trap for Tab key
        if (event.key === 'Tab' && apiKeyModal && !apiKeyModal.classList.contains('hidden')) {
            const focusableElements = Array.from(
                apiKeyModalPanel.querySelectorAll(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                )
            ).filter(el => !el.disabled && !el.closest('.hidden'));

            if (focusableElements.length === 0) return;

            const firstFocusable = focusableElements[0];
            const lastFocusable = focusableElements[focusableElements.length - 1];

            if (event.shiftKey) { // Shift + Tab
                if (document.activeElement === firstFocusable) {
                    lastFocusable.focus();
                    event.preventDefault();
                }
            } else { // Tab
                if (document.activeElement === lastFocusable) {
                    firstFocusable.focus();
                    event.preventDefault();
                }
            }
        }
    });

    // --- API Key Form Submission Listener ---
    const apiKeyForm = document.getElementById('apiKeyForm');
    const apiKeyServiceSelect = document.getElementById('apiKeyServiceSelect');
    if (apiKeyServiceSelect) {
        apiKeyServiceSelect.addEventListener('change', () => {
            updateModelSettings(apiKeyServiceSelect.value);
        });
        updateModelSettings(apiKeyServiceSelect.value);
    }

    const apiKeyInput = document.getElementById('apiKeyInput');
    const modelNameInput = document.getElementById('apiKeyOpenrouterModel');
    const purposeInputs = document.querySelectorAll('input[name="model_purpose"]');
    if (modelNameInput) {
        modelNameInput.addEventListener('input', () => {
            setApiKeySuggestion();
        });
    }
    purposeInputs.forEach(input => {
        input.addEventListener('change', () => updateModelSettings(apiKeyServiceSelect?.value || ''));
    });
    if (apiKeyInput) {
        apiKeyInput.addEventListener('input', () => {
            if (apiKeyInput.value !== openRouterSuggestedMask) {
                apiKeyInput.type = 'password';
            }
        });
    }
    if (apiKeyForm) {
        apiKeyForm.addEventListener('submit', handleApiKeySave);
        window.logger.debug(userSettingsLogPrefix, "API Key save form listener attached.");
    } else if (window.IS_MULTI_USER) {
         window.logger.warn(userSettingsLogPrefix, "API Key form element (#apiKeyForm) not found.");
    }

    // --- API Key Deletion Listener (Event Delegation) ---
    const keyStatusListContainer = apiKeyModalPanel.querySelector('ul.divide-y'); // Target the ul inside the panel
    if (keyStatusListContainer) {
        keyStatusListContainer.addEventListener('click', function(event) {
            const deleteButton = event.target.closest('.delete-key-btn');
            if (deleteButton) {
                window.logger.info(userSettingsLogPrefix, "Delete button clicked:", deleteButton);
                event.preventDefault();
                handleApiKeyDelete(deleteButton);
            }
        });
        window.logger.debug(userSettingsLogPrefix, "API Key delete listener (delegation) attached.");
    } else if (window.IS_MULTI_USER) {
         window.logger.warn(userSettingsLogPrefix, "API Key status list container not found for delete listener.");
    }

}); // End DOMContentLoaded


function updatePublicApiKeySection(publicStatus) {
    if (!publicApiKeyValueInput || !publicApiCopyBtn) return;
    const status = publicStatus || {};
    const keys = Array.isArray(status.keys) ? status.keys : [];
    const enabled = Boolean(status && status.enabled);

    if (publicApiKeyStatusEl) {
        publicApiKeyStatusEl.textContent = enabled ? 'Configured' : 'Not Configured';
        publicApiKeyStatusEl.className = enabled
            ? 'text-sm text-success font-medium'
            : 'text-sm text-warning font-medium';
    }

    if (lastGeneratedPublicApiKey) {
        if (publicApiKeyCreatedPanel) publicApiKeyCreatedPanel.classList.remove('hidden');
        publicApiKeyValueInput.value = lastGeneratedPublicApiKey;
        publicApiCopyBtn.disabled = false;
    } else {
        if (publicApiKeyCreatedPanel) publicApiKeyCreatedPanel.classList.add('hidden');
        publicApiKeyValueInput.value = '';
        publicApiCopyBtn.disabled = true;
    }

    if (publicApiKeyListEl) {
        publicApiKeyListEl.innerHTML = '';
        if (keys.length === 0) {
            const emptyRow = document.createElement('li');
            emptyRow.className = 'py-3 text-sm text-text-muted';
            emptyRow.textContent = 'No public API keys configured.';
            publicApiKeyListEl.appendChild(emptyRow);
        } else {
            keys.forEach(key => {
                const row = document.createElement('li');
                row.className = 'py-3 flex items-center justify-between gap-3';

                const content = document.createElement('div');
                content.className = 'min-w-0';

                const name = document.createElement('p');
                name.className = 'text-sm font-medium text-text-strong truncate';
                name.textContent = key.name || 'Public API key';

                const meta = document.createElement('p');
                meta.className = 'text-xs text-text-muted';
                const createdAt = key.created_at ? formatPublicApiCreatedAt(key.created_at) : null;
                meta.textContent = createdAt ? `****${key.last_four || '----'} • Created ${createdAt}` : `****${key.last_four || '----'}`;

                content.appendChild(name);
                content.appendChild(meta);

                const actions = document.createElement('div');
                actions.className = 'flex items-center gap-2 flex-none';

                const active = createKeyStatusBadge(true);

                const revokeBtn = document.createElement('button');
                revokeBtn.type = 'button';
                revokeBtn.className = 'revoke-public-key-btn icon-btn icon-btn--danger';
                revokeBtn.dataset.keyId = key.id;
                revokeBtn.dataset.keyName = key.name || 'Public API key';
                revokeBtn.setAttribute('aria-label', `Revoke ${key.name || 'public API key'}`);
                revokeBtn.innerHTML = '<i class="material-icons text-lg">delete</i>';

                actions.appendChild(active);
                actions.appendChild(revokeBtn);
                row.appendChild(content);
                row.appendChild(actions);
                publicApiKeyListEl.appendChild(row);
            });
        }
    }
}

function formatPublicApiCreatedAt(createdAt) {
    try {
        return window.formatDateTime(createdAt);
    } catch (e) {
        return createdAt;
    }
}

function copyPublicApiKeyToClipboard(event) {
    event.preventDefault();
    if (!lastGeneratedPublicApiKey) {
        window.showNotification('Nothing to copy. Generate a key first.', 'warning', 4000, false);
        return;
    }
    navigator.clipboard.writeText(lastGeneratedPublicApiKey)
        .then(() => {
            window.showNotification('API key copied to clipboard.', 'success', 3000, false);
        })
        .catch(() => {
            window.showNotification('Could not copy API key. Please copy it manually.', 'error', 4000, false);
        });
}

function handleGeneratePublicApiKey(event) {
    event.preventDefault();
    if (!publicApiKeyForm) return;

    const submitButton = publicApiCreateBtn || publicApiKeyForm.querySelector('button[type="submit"], button');
    const keyName = publicApiKeyNameInput ? publicApiKeyNameInput.value.trim() : '';
    if (!keyName) {
        window.showNotification('Please name this API key.', 'warning', 4000, false);
        return;
    }

    const originalHtml = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = 'Creating... <span class="spinner ml-2 inline-block" style="width: 1em; height: 1em; border-width: .15em;"></span>';

    const formData = new FormData(publicApiKeyForm);

    fetch('/api/user/public-api-key', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().catch(() => ({ error: `HTTP error! Status: ${response.status}` })).then(errData => {
                throw new Error(errData.error || `HTTP error! Status: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        lastGeneratedPublicApiKey = data.api_key;
        if (publicApiKeyNameInput) publicApiKeyNameInput.value = '';
        window.showNotification('New API key generated. Copy it now and keep it secure.', 'success', 5000, false);
        return fetchApiKeyStatus();
    })
    .catch(error => {
        window.logger.error(userSettingsLogPrefix, 'Error generating public API key:', error);
        window.showNotification(`Error generating API key: ${error.message}`, 'error', 6000, false);
    })
    .finally(() => {
        submitButton.disabled = false;
        submitButton.innerHTML = originalHtml;
    });
}

function handleRevokePublicApiKey(button) {
    const keyId = button.dataset.keyId;
    const keyName = button.dataset.keyName || 'this public API key';
    if (!keyId) {
        window.showNotification('Could not determine which public API key to revoke.', 'error', 4000, false);
        return;
    }
    if (!confirm(`Revoke ${keyName}? Existing scripts using this key will stop working.`)) {
        return;
    }
    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner inline-block" style="width: 0.8em; height: 0.8em; border-width: .15em;"></span>';

    fetch(`/api/user/public-api-key/${encodeURIComponent(keyId)}`, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().catch(() => ({ error: `HTTP error! Status: ${response.status}` })).then(errData => {
                throw new Error(errData.error || `HTTP error! Status: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        lastGeneratedPublicApiKey = null;
        window.showNotification(data.message || 'Public API key revoked.', 'success', 4000, false);
        return fetchApiKeyStatus();
    })
    .catch(error => {
        window.logger.error(userSettingsLogPrefix, 'Error revoking public API key:', error);
        window.showNotification(`Error revoking API key: ${error.message}`, 'error', 6000, false);
    })
    .finally(() => {
        button.disabled = false;
        button.innerHTML = originalHtml;
    });
}


function renderProviderKeyRows(service, keys) {
    const container = document.getElementById(`${service}KeyRows`);
    if (!container) return;

    const entries = Array.isArray(keys) ? keys : [];
    const providerLabels = {
        openai: 'OpenAI',
        assemblyai: 'AssemblyAI',
        gemini: 'Google',
        openrouter: 'OpenRouter',
    };
    container.innerHTML = '';
    container.className = 'py-3 space-y-3';

    if (entries.length === 0) {
        const row = document.createElement('div');
        row.className = 'flex justify-between items-center gap-3';
        const label = document.createElement('span');
        label.className = 'text-sm font-medium text-text-strong';
        label.textContent = providerLabels[service] || service;
        // Reserve the delete-button slot so 'Not Configured' lines up
        // with 'Configured' (both badges share one fixed width).
        const actions = document.createElement('div');
        actions.className = 'flex items-center gap-2';
        const spacer = document.createElement('span');
        spacer.className = 'h-8 w-8 flex-none';
        spacer.setAttribute('aria-hidden', 'true');
        actions.append(createKeyStatusBadge(false), spacer);
        row.append(label, actions);
        container.appendChild(row);
        return;
    }

    entries.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'flex justify-between items-center gap-3';

        const modelName = entry.model_name || entry.model_slug || providerLabels[service] || service;
        const label = document.createElement('div');
        label.className = 'flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1';
        appendModelLabel(
            label,
            modelName,
            entry.model_purposes,
            providerLabels[service] || service,
        );

        const actions = document.createElement('div');
        actions.className = 'flex items-center gap-2';
        const status = createKeyStatusBadge(true);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'delete-key-btn icon-btn icon-btn--danger';
        deleteBtn.dataset.service = service;
        if (entry.key_id) deleteBtn.dataset.keyId = entry.key_id;
        if (!entry.provider_wide && (entry.model_name || entry.model_slug)) {
            deleteBtn.dataset.modelSlug = entry.model_name || entry.model_slug;
        }
        deleteBtn.setAttribute('aria-label', `Delete ${modelName} key`);
        deleteBtn.innerHTML = '<i class="material-icons text-lg">delete</i>';
        actions.append(status, deleteBtn);
        row.append(label, actions);
        container.appendChild(row);
    });
}

function renderOpenRouterKeyRows(keys) {
    renderProviderKeyRows('openrouter', keys);
}

/**
 * Fetches the current status of configured API keys from the backend API.
 * Updates the status display within the modal.
 * Returns a Promise that resolves with the key status data or rejects on error.
 */
function fetchApiKeyStatus() {
    window.logger.debug(userSettingsLogPrefix, "Fetching API key status...");
    const permissions = window.USER_PERMISSIONS || {};
    const providerPermissions = {
        openai: permissions.use_api_openai || permissions.use_api_openai_whisper
            || permissions.use_api_openai_gpt_4o_transcribe || permissions.use_api_openai_live_transcribe,
        assemblyai: permissions.use_api_assemblyai,
        gemini: permissions.use_api_google || permissions.use_api_google_gemini,
        openrouter: permissions.use_api_openrouter,
    };

    return fetch('/api/user/keys', {
        method: 'GET',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': window.csrfToken }
    })
    .then(response => {
        if (response.status === 401) throw new Error('Authentication required (401)');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        window.logger.info(userSettingsLogPrefix, "API Key status received:", data);
        window.API_KEY_STATUS = data || {};
        const providerKeys = data.provider_keys || {};
        Object.entries(providerPermissions).forEach(([service, allowed]) => {
            if (!allowed) return;
            const entries = Array.isArray(providerKeys[service])
                ? providerKeys[service]
                : getProviderKeyEntries(service);
            renderProviderKeyRows(service, entries);
        });
        setApiKeySuggestion();

        if (typeof window.updateApiKeyNotificationVisibility === 'function') {
            window.updateApiKeyNotificationVisibility(data, permissions);
        } else {
            window.logger.error(userSettingsLogPrefix, "updateApiKeyNotificationVisibility function not found.");
        }
        updatePublicApiKeySection(data.public_api);
        return data;
    })
    .catch(error => {
        window.logger.error(userSettingsLogPrefix, 'Error fetching API key status:', error);
        window.showNotification(`Error fetching key status: ${error.message}`, 'error', 6000, false);
        Object.entries(providerPermissions).forEach(([service, allowed]) => {
            if (allowed) renderProviderKeyRows(service, []);
        });
        updatePublicApiKeySection(null);
        if (error.message.includes('Authentication required')) {
            closeApiKeyModalDialog();
        }
        throw error;
    });
}

/**
 * Refreshes the page-level model catalog globals so dropdowns built from
 * them (User Settings modal) include models saved or deleted through this
 * modal without a full page reload. Best-effort: a failure only logs, the
 * key-status UI above is already up to date at that point.
 */
function refreshModelCatalogGlobals() {
    return fetch('/api/user/model-catalog', {
        method: 'GET',
        headers: { 'Accept': 'application/json', 'X-CSRFToken': window.csrfToken }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if ('transcription' in data) window.TRANSCRIPTION_MODELS = data.transcription;
        if ('live' in data) window.LIVE_TRANSCRIPTION_MODELS = data.live;
        if ('llm' in data) window.LLM_MODEL_CATALOG = data.llm;
    })
    .catch(error => {
        window.logger.warn(userSettingsLogPrefix, "Could not refresh model catalog:", error);
    });
}

/**
 * Handles the submission of the API key form (Save Key button).
 * Sends the data to the backend API.
 * @param {Event} event - The form submission event.
 */
function handleApiKeySave(event) {
    event.preventDefault();
    const logPrefix = "[UserSettingsJS:handleApiKeySave]";
    window.logger.info(logPrefix, "Save key form submitted.");

    const form = event.target;
    const serviceSelect = document.getElementById('apiKeyServiceSelect');
    const keyInput = document.getElementById('apiKeyInput');
    const modelNameInput = document.getElementById('apiKeyOpenrouterModel');
    const submitButton = form.querySelector('button[type="submit"]');

    const service = serviceSelect?.value || '';
    const purpose = document.querySelector('input[name="model_purpose"]:checked')?.value || 'transcription';
    const modelName = modelNameInput?.value.trim() || '';
    const apiKey = keyInput?.value.trim() || '';
    const isMaskedKey = /^\*{3}.{3}$/.test(apiKey);

    if (!service) {
        window.showNotification('Please select an API service.', 'warning', 4000, false);
        return;
    }
    if (!modelName && service === 'openrouter') {
        window.showNotification('Please enter an OpenRouter model slug.', 'warning', 4000, false);
        return;
    }
    if (!apiKey) {
        window.showNotification('Please enter an API key.', 'warning', 4000, false);
        return;
    }
    if (apiKey.length < 10 && !isMaskedKey) {
         window.showNotification('API key seems too short.', 'warning', 4000, false);
         return;
    }
    if (service === 'openrouter' && !modelName.includes('/')) {
        window.showNotification('Please enter an OpenRouter model slug such as google/gemini-3.7-flash.', 'warning', 5000, false);
        return;
    }

    const originalButtonHtml = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = 'Saving... <span class="spinner ml-2 inline-block" style="width: 1em; height: 1em; border-width: .15em;"></span>';

    const formData = new FormData(form);
    // Keep both names in the request while older API clients migrate.
    formData.set('model_name', modelName);
    formData.set('openrouter_model', modelName);
    formData.set('model_purpose', purpose);
    formData.set('openrouter_model_purpose', purpose);

    fetch('/api/user/keys', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().catch(() => ({ error: `HTTP error! Status: ${response.status}` })).then(errData => {
                throw new Error(errData.error || `Save failed: ${response.statusText}`);
            });
        }
        return response.json();
    })
    .then(data => {
        window.logger.info(logPrefix, "API Key save response:", data);
        window.showNotification(data.message || 'API Key saved successfully!', 'success', 4000, false);
        keyInput.value = '';
        keyInput.type = 'password';
        openRouterSuggestedMask = '';
        serviceSelect.value = '';
        if (modelNameInput) modelNameInput.value = '';
        const transcriptionPurpose = document.querySelector('input[name="model_purpose"][value="transcription"]');
        if (transcriptionPurpose) transcriptionPurpose.checked = true;
        updateModelSettings(serviceSelect.value);
        return fetchApiKeyStatus()
            .then(() => refreshModelCatalogGlobals());
    })
    .then(() => {
        if (typeof window.invalidateReadinessCache === 'function') {
            window.invalidateReadinessCache();
        }
        if (typeof checkTranscribeButtonState === 'function') {
            window.logger.info(logPrefix, "Triggering main page UI update after save.");
            checkTranscribeButtonState();
        } else {
            window.logger.warn(logPrefix, "checkTranscribeButtonState function not found in main.js");
        }
    })
    .catch(error => {
        window.logger.error(logPrefix, 'Error saving API key:', error);
        if (!error.message.includes("fetching key status")) {
            window.showNotification(`Error saving key: ${error.message}`, 'error', 6000, false);
        }
        if (error.message.includes('Authentication required')) {
            closeApiKeyModalDialog();
        }
    })
    .finally(() => {
        submitButton.disabled = false;
        submitButton.innerHTML = originalButtonHtml;
    });
}


/**
 * Handles the click on a delete API key button (using event delegation).
 * @param {HTMLElement} button - The delete button element that was clicked.
 */
function handleApiKeyDelete(button) {
    const service = button.dataset.service;
    const modelSlug = button.dataset.modelSlug;
    const keyId = button.dataset.keyId;
    const logPrefix = `[UserSettingsJS:handleApiKeyDelete:${service}]`;
    window.logger.info(logPrefix, `Delete key requested.`);

    if (!service) {
        window.logger.error(logPrefix, "Delete handler called without a service specified on the button.");
        window.showNotification('Could not determine which key to delete.', 'error', 4000, false);
        return;
    }

    let serviceDisplayName = service.charAt(0).toUpperCase() + service.slice(1);
    if (service === 'openai') serviceDisplayName = 'OpenAI';
    else if (service === 'assemblyai') serviceDisplayName = 'AssemblyAI (Universal)';
    else if (service === 'gemini') serviceDisplayName = 'Google Gemini';
    else if (service === 'openrouter') {
        serviceDisplayName = modelSlug ? `${modelSlug} (OpenRouter)` : 'OpenRouter';
    }

    if (!confirm(`Are you sure you want to delete the API key for ${serviceDisplayName}?`)) {
        window.logger.info(logPrefix, "Delete cancelled by user.");
        return;
    }

    button.disabled = true;
    const originalIcon = button.innerHTML;
    button.innerHTML = '<span class="spinner inline-block" style="width: 0.8em; height: 0.8em; border-width: .15em;"></span>';


    const deleteParams = new URLSearchParams();
    if (keyId) deleteParams.set('key_id', keyId);
    else if (modelSlug) deleteParams.set('model', modelSlug);
    const deleteUrl = `/api/user/keys/${service}${deleteParams.toString() ? `?${deleteParams.toString()}` : ''}`;
    fetch(deleteUrl, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().catch(() => {
                return { error: `HTTP error! Status: ${response.status}` };
            }).then(errData => {
                const message = response.status === 404 ? (errData.error || 'Key not found.') : (errData.error || `Delete failed: ${response.statusText}`);
                throw new Error(message);
            });
        }
        return response.json();
    })
    .then(data => {
        window.logger.info(logPrefix, `API Key delete response:`, data);
        window.showNotification(data.message || `API Key for ${serviceDisplayName} deleted.`, 'success', 4000, false);

        return fetchApiKeyStatus()
            .then(() => refreshModelCatalogGlobals());
    })
    .then(() => {
        if (typeof window.invalidateReadinessCache === 'function') {
            window.invalidateReadinessCache(); // Invalidate cache
        }
        if (typeof checkTranscribeButtonState === 'function') {
            window.logger.info(logPrefix, "Triggering main page UI update after delete.");
            checkTranscribeButtonState();
        } else {
            window.logger.warn(logPrefix, "checkTranscribeButtonState function not found in main.js");
        }
    })
    .catch(error => {
        window.logger.error(logPrefix, `Error deleting API key:`, error);
        if (!error.message.includes("fetching key status")) {
             window.showNotification(`Error deleting key: ${error.message}`, 'error', 6000, false);
        }
        if (error.message.includes('Authentication required')) {
            closeApiKeyModalDialog(); // Close the new modal
        }

        if (document.body.contains(button)) {
            button.disabled = false;
            button.innerHTML = originalIcon;
        }
    });
}

/**
 * Simple HTML escaping.
 * @param {string} str The string to escape.
 * @returns {string} Escaped string.
 */
 function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Node test hook (same pattern as main_utils.js).
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { refreshModelCatalogGlobals };
}
