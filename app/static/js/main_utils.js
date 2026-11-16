// app/static/js/main_utils.js
/* Shared utility functions for the main application UI. */

const mainUtilsLogPrefix = "[MainUtilsJS]";

const LOG_LEVELS = Object.freeze({
    debug: 10,
    info: 20,
    warn: 30,
    error: 40
});

function isDebugEnabled() {
    return Boolean(window.APP_DEBUG_MODE);
}

function isInfoEnabled() {
    return Boolean(window.APP_DEBUG_MODE);
}

function shouldLog(level) {
    if (level === 'warn' || level === 'error') return true;
    if (level === 'info') return isInfoEnabled();
    if (level === 'debug') return isDebugEnabled();
    return false;
}

function normalizeScope(scope) {
    if (!scope) return "App";
    if (scope.startsWith("[") && scope.endsWith("]")) {
        return scope.slice(1, -1);
    }
    return scope;
}

function emitLog(level, scope, message, metadata) {
    if (!shouldLog(level)) return;
    const consoleMethod = level === 'debug'
        ? console.debug
        : level === 'info'
            ? console.info
            : level === 'warn'
                ? console.warn
                : console.error;

    const parts = [`[${scope}]`];
    if (message !== undefined && message !== null) {
        parts.push(message);
    }
    if (metadata !== undefined) {
        parts.push(metadata);
    }
    consoleMethod(...parts);
}

function normalizeLegacyArgs(arg1, arg2, arg3) {
    if (typeof arg1 === 'string' && arg1.startsWith("[")) {
        return {
            scope: normalizeScope(arg1),
            message: arg2,
            metadata: arg3
        };
    }
    return {
        scope: "App",
        message: arg1,
        metadata: arg2
    };
}

window.logger = {
    debug(arg1, arg2, arg3) {
        const { scope, message, metadata } = normalizeLegacyArgs(arg1, arg2, arg3);
        emitLog('debug', scope, message, metadata);
    },
    info(arg1, arg2, arg3) {
        const { scope, message, metadata } = normalizeLegacyArgs(arg1, arg2, arg3);
        emitLog('info', scope, message, metadata);
    },
    warn(arg1, arg2, arg3) {
        const { scope, message, metadata } = normalizeLegacyArgs(arg1, arg2, arg3);
        emitLog('warn', scope, message, metadata);
    },
    error(arg1, arg2, arg3) {
        const { scope, message, metadata } = normalizeLegacyArgs(arg1, arg2, arg3);
        emitLog('error', scope, message, metadata);
    },
    scoped(scopeName) {
        const normalizedScope = normalizeScope(scopeName);
        return {
            debug: (message, metadata) => emitLog('debug', normalizedScope, message, metadata),
            info: (message, metadata) => emitLog('info', normalizedScope, message, metadata),
            warn: (message, metadata) => emitLog('warn', normalizedScope, message, metadata),
            error: (message, metadata) => emitLog('error', normalizedScope, message, metadata),
            isDebugEnabled: () => shouldLog('debug'),
            isInfoEnabled: () => shouldLog('info')
        };
    },
    isDebugEnabled,
    isInfoEnabled
};
const mainUtilsLogger = window.logger.scoped("MainUtilsJS");

const PERSISTED_NOTIFICATION_STORAGE_KEY = 'app:pendingNotifications';

const NOTIFICATION_TYPE_CONFIG = Object.freeze({
    error: {
        alertClass: 'alert-danger',
        iconName: 'error',
        defaultDuration: 6000,
        defaultPersistent: true,
        ariaLive: 'assertive'
    },
    warning: {
        alertClass: 'alert-warning',
        iconName: 'warning',
        defaultDuration: 5000,
        defaultPersistent: false,
        ariaLive: 'polite'
    },
    success: {
        alertClass: 'alert-success',
        iconName: 'check_circle',
        defaultDuration: 4000,
        defaultPersistent: false,
        ariaLive: 'polite'
    },
    info: {
        alertClass: 'alert-info',
        iconName: 'info',
        defaultDuration: 6000,
        defaultPersistent: true,
        ariaLive: 'polite'
    }
});


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
window.escapeHtml = escapeHtml;


/**
 * Displays a persistent notification message at the top of the page using Tailwind CSS.
 * @param {string} message - The message text.
 * @param {string} [type='info'] - Type of notification ('error', 'info', 'warning', 'success'). Determines styling.
 * @param {number} [duration] - Duration in ms before auto-dismissal. 0 for no auto-dismiss.
 * @param {boolean} [persistent] - If true, message doesn't dismiss on click (unless a close button is added).
 * @param {string} [id=null] - Optional unique ID for the notification element.
 * @returns {HTMLElement|null} The created notification element or null.
 */
function showNotification(message, type = 'info', duration, persistent, id = null) {
    const container = document.getElementById('notification-container');
    if (!container) {
        mainUtilsLogger.error("Notification container not found!");
        return null;
    }

    // If an ID is provided, remove any existing notification with the same ID
    if (id) {
        const existing = document.getElementById(id);
        if (existing) {
            existing.remove();
        }
    }

    const typeConfig = NOTIFICATION_TYPE_CONFIG[type] || NOTIFICATION_TYPE_CONFIG.info;
    const finalDuration = typeof duration === 'number' ? duration : typeConfig.defaultDuration;
    const finalPersistent = typeof persistent === 'boolean' ? persistent : typeConfig.defaultPersistent;

    const notificationDiv = document.createElement('div');
    if (id) {
        notificationDiv.id = id;
    }

    // Base classes shared with inline alerts for consistent styling
    const baseNotificationClasses = 'alert toast w-full max-w-full transition-all duration-300 ease-in-out transform opacity-0 translate-y-2 pointer-events-auto';
    const wrapperClasses = typeConfig.alertClass ? `${typeConfig.alertClass}` : '';
    notificationDiv.className = wrapperClasses ? `${baseNotificationClasses} ${wrapperClasses}` : baseNotificationClasses;
    notificationDiv.setAttribute('role', 'alert');
    notificationDiv.setAttribute('aria-live', typeConfig.ariaLive || 'polite');
    notificationDiv.dataset.notificationType = type;

    // Icon element wrapped to match flash alerts
    const iconWrapper = document.createElement('div');
    iconWrapper.className = 'alert-icon';
    const iconElement = document.createElement('i');
    iconElement.className = 'material-icons';
    iconElement.textContent = typeConfig.iconName;
    iconWrapper.appendChild(iconElement);

    // Message content element
    const messageElement = document.createElement('div');
    messageElement.className = 'alert-content';
    const bodyElement = document.createElement('p');
    bodyElement.textContent = (message === undefined || message === null) ? '' : String(message);
    messageElement.appendChild(bodyElement);

    notificationDiv.appendChild(iconWrapper);
    notificationDiv.appendChild(messageElement);

    // Close button (always add for persistent, or if not auto-dismissing for a long time)
    if (finalPersistent || finalDuration === 0 || finalDuration > 10000) {
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'alert-close';
        closeButton.setAttribute('aria-label', 'Close notification');
        const closeIcon = document.createElement('i');
        closeIcon.className = 'material-icons text-base';
        closeIcon.textContent = 'close';
        closeButton.appendChild(closeIcon);
        closeButton.addEventListener('click', () => dismissNotification(notificationDiv));
        notificationDiv.appendChild(closeButton);
    }

    container.appendChild(notificationDiv);

    // Enter animation
    requestAnimationFrame(() => {
        notificationDiv.classList.remove('opacity-0', 'translate-y-2');
        notificationDiv.classList.add('opacity-100', 'translate-y-0');
    });

    // Auto-dismissal
    if (finalDuration > 0) {
        setTimeout(() => dismissNotification(notificationDiv), finalDuration);
    }

    return notificationDiv;
}
window.showNotification = showNotification; // Expose globally

/**
 * Renders a message with an inline action link inside one text element.
 *
 * The action is placed inside the sentence: if the message text contains the
 * action label (e.g. "Add one in Manage API Keys."), that phrase becomes the
 * link; otherwise the link follows the text inline after a space. Every
 * toast, progress line and status message uses this, so actions never sit in
 * a separate block with their own margins, and the label is never repeated.
 * Text is always set with textContent (never parsed as markup).
 * @param {HTMLElement} target - Element that receives the text (e.g. a <p>).
 * @param {string} text - Plain message text.
 * @param {{label: string, onClick?: function, dataset?: object, className?: string}} action
 *   className is for JS hooks only (e.g. 'undo-delete-action'); styling comes
 *   from the shared .inline-action class.
 * @returns {HTMLButtonElement|null} The action button, or null when there is no action.
 */
function renderTextWithInlineAction(target, text, action) {
    const messageText = text === undefined || text === null ? '' : String(text);
    target.textContent = '';
    if (!action || !action.label) {
        target.textContent = messageText;
        return null;
    }
    const label = String(action.label);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = ['inline-action', action.className].filter(Boolean).join(' ');
    button.textContent = label;
    Object.entries(action.dataset || {}).forEach(([key, value]) => { button.dataset[key] = value; });
    if (typeof action.onClick === 'function') {
        button.addEventListener('click', event => action.onClick(event, button));
    }
    const appendText = value => {
        if (!value) return;
        const span = document.createElement('span');
        span.textContent = value;
        target.appendChild(span);
    };
    const index = messageText.indexOf(label);
    if (index >= 0) {
        appendText(messageText.slice(0, index));
        target.appendChild(button);
        appendText(messageText.slice(index + label.length));
    } else {
        appendText(messageText ? `${messageText} ` : '');
        target.appendChild(button);
    }
    return button;
}
window.renderTextWithInlineAction = renderTextWithInlineAction;

/**
 * Displays a text notification with one structured action button.
 *
 * This is intentionally separate from showNotification so ordinary messages
 * can never be interpreted as markup.
 * @param {string} message - The message text.
 * @param {{label: string, onClick: function, className?: string}} action - Action definition.
 * @param {string} [type='info'] - Notification type.
 * @param {number} [duration] - Duration in ms before auto-dismissal.
 * @param {boolean} [persistent] - Whether the notification is persistent.
 * @param {string|null} [id=null] - Optional unique ID for the notification element.
 * @returns {HTMLElement|null} The created notification element or null.
 */
function showNotificationWithAction(message, action, type = 'info', duration, persistent, id = null) {
    const notification = showNotification(message, type, duration, persistent, id);
    if (!notification || !action || typeof action.onClick !== 'function') {
        return notification;
    }

    const textElement = notification.querySelector('.alert-content p');
    if (!textElement) return notification;

    renderTextWithInlineAction(textElement, message, {
        label: action.label,
        className: action.className,
        onClick: (event, button) => action.onClick(event, notification, button),
    });
    return notification;
}
window.showNotificationWithAction = showNotificationWithAction;

function readPersistedNotifications() {
    if (typeof window === 'undefined' || typeof window.sessionStorage === 'undefined') return [];
    try {
        const stored = window.sessionStorage.getItem(PERSISTED_NOTIFICATION_STORAGE_KEY);
        if (!stored) return [];
        const parsed = JSON.parse(stored);
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        mainUtilsLogger.warn("Unable to read pending notifications from storage.", error);
        return [];
    }
}

function writePersistedNotifications(entries) {
    if (typeof window === 'undefined' || typeof window.sessionStorage === 'undefined') return;
    try {
        if (!entries || entries.length === 0) {
            window.sessionStorage.removeItem(PERSISTED_NOTIFICATION_STORAGE_KEY);
        } else {
            window.sessionStorage.setItem(PERSISTED_NOTIFICATION_STORAGE_KEY, JSON.stringify(entries));
        }
    } catch (error) {
        mainUtilsLogger.warn("Unable to write pending notifications to storage.", error);
    }
}

function persistNotificationForNextPage(message, type = 'info', options = {}) {
    if (!message) return;
    if (typeof window === 'undefined' || typeof window.sessionStorage === 'undefined') return;
    const normalizedType = typeof type === 'string' ? type : 'info';
    const entry = { message, type: normalizedType };
    if (typeof options.duration === 'number') {
        entry.duration = options.duration;
    }
    if (typeof options.persistent === 'boolean') {
        entry.persistent = options.persistent;
    }
    const pending = readPersistedNotifications();
    pending.push(entry);
    writePersistedNotifications(pending);
}
window.persistNotificationForNextPage = persistNotificationForNextPage;

function processPersistedNotifications() {
    const pending = readPersistedNotifications();
    if (!pending.length) return;
    writePersistedNotifications([]);
    pending.forEach(entry => {
        if (!entry || !entry.message) return;
        const durationOverride = typeof entry.duration === 'number' ? entry.duration : undefined;
        const persistentOverride = typeof entry.persistent === 'boolean' ? entry.persistent : undefined;
        showNotification(entry.message, entry.type || 'info', durationOverride, persistentOverride);
    });
}

function dismissNotification(notificationDiv) {
    if (!notificationDiv || !notificationDiv.parentNode) return;

    // Leave animation
    notificationDiv.classList.remove('opacity-100', 'translate-y-0');
    notificationDiv.classList.add('opacity-0', 'translate-y-2');

    setTimeout(() => {
        if (notificationDiv.parentNode) {
            notificationDiv.remove();
        }
    }, 300); // Match transition duration
}


/**
 * Helper function to Open API Key Modal.
 * (Used when an error message includes a link to manage keys)
 */
function openApiKeyModal(event) {
    if (event) event.preventDefault(); // Prevent default link behavior
    // The new Tailwind/JS modal opening logic is in user_settings.js
    if (typeof window.openApiKeyModalDialog === 'function') {
        window.openApiKeyModalDialog();
    } else {
        mainUtilsLogger.error("openApiKeyModalDialog function not found in user_settings.js. API Key management might be unavailable.");
        // Removed Materialize fallback code
        // alert('API Key management is not available or modal function missing.'); // This alert was commented out
    }
}
window.openApiKeyModal = openApiKeyModal; // Expose globally



/**
 * Simple minutes formatter for displaying usage limits.
 * @param {number} totalMinutes
 * @returns {string} Formatted string like "90 min". Returns "Unlimited" if 0 or less.
 */
function formatMinutesSimple(totalMinutes) {
    if (isNaN(totalMinutes) || totalMinutes <= 0) return "Unlimited";
    // Round up to the nearest whole minute for display consistency with history
    const roundedMinutes = Math.ceil(totalMinutes);
    return `${roundedMinutes} min`;
}
window.formatMinutesSimple = formatMinutesSimple; // Expose globally


/**
 * Finds all <time> elements with a datetime attribute on the page
 * and updates their content to a localized, formatted string.
 * This now relies on the functions in localization.js
 */
function initializeLocalizedDates() {
    const timeElements = document.querySelectorAll('time[datetime]');
    timeElements.forEach(timeEl => {
        const isoString = timeEl.getAttribute('datetime');
        if (isoString) {
            // Use the new global formatter from localization.js
            if (typeof window.formatDateTime === 'function') {
                timeEl.textContent = window.formatDateTime(isoString);
            } else {
                mainUtilsLogger.warn("window.formatDateTime function not found. Dates will not be localized.");
            }
        }
    });
}

// Run the date localization on page load.
function processFlashMessagesFromServer() {
    const flashContainers = document.querySelectorAll('[data-flash-messages]');
    if (!flashContainers.length) return;

    flashContainers.forEach(container => {
        const payload = container.dataset.flashMessages;
        if (!payload) return;

        let messages = [];
        try {
            messages = JSON.parse(payload);
        } catch (error) {
            mainUtilsLogger.warn("Failed to parse flash messages payload.", { error, payload });
            return;
        }

        if (!Array.isArray(messages) || messages.length === 0) {
            return;
        }

        container.classList.add('hidden');
        container.setAttribute('aria-hidden', 'true');

        messages.forEach(entry => {
            if (!entry) return;
            const type = typeof entry.type === 'string' ? entry.type : 'info';
            const text = entry.message || '';
            showNotification(text, type);
        });
    });
}

function handleDomContentLoaded() {
    initializeLocalizedDates();
    processFlashMessagesFromServer();
    processPersistedNotifications();
}

document.addEventListener('DOMContentLoaded', handleDomContentLoaded);


// --- Copy to Clipboard Functionality with Toast Cooldown ---
let lastCopyToastTime = 0;
const TOAST_COOLDOWN_MS = 1000; // 1 second cooldown for copy toasts

function fallbackCopyToClipboard(text) {
  const log = window.logger.scoped("MainUtilsJS:fallbackCopy");
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.position = "fixed"; // Prevent scrolling to bottom
  textArea.style.top = "-9999px";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    const successful = document.execCommand('copy');
    const now = Date.now();
    if (successful) {
      if (now - lastCopyToastTime > TOAST_COOLDOWN_MS) {
        showNotification('Copied (fallback)!', 'info', 2000, false);
        lastCopyToastTime = now;
      } else {
        log.debug("Fallback copy toast suppressed due to cooldown.");
      }
      log.debug("Text copied using fallback method.");
    } else {
      showNotification('Copy failed (fallback)!', 'error', 3000, false);
      log.error('Fallback copy command failed.');
    }
  } catch (err) {
    showNotification('Copy failed (fallback)!', 'error', 3000, false);
    log.error('Error during fallback copy:', err);
  }
  document.body.removeChild(textArea);
}
window.fallbackCopyToClipboard = fallbackCopyToClipboard; // Expose globally

function copyToClipboard(text) {
  const log = window.logger.scoped("MainUtilsJS:copyToClipboard");
  if (!text) {
    showNotification('Nothing to copy!', 'warning', 2000, false);
    return;
  }

  const now = Date.now();

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text)
      .then(() => {
        if (now - lastCopyToastTime > TOAST_COOLDOWN_MS) {
          showNotification('Copied to clipboard!', 'success', 2000, false);
          lastCopyToastTime = now;
        } else {
          log.debug("Clipboard API copy toast suppressed due to cooldown.");
        }
        log.debug("Text copied using Clipboard API.");
      })
      .catch(err => {
        showNotification('Copy failed!', 'error', 3000, false);
        log.error('Async copy failed:', err);
        window.fallbackCopyToClipboard(text); // Ensure fallback is called
      });
  } else {
    log.warn("Using fallback copy method (navigator.clipboard not available or insecure context).");
    window.fallbackCopyToClipboard(text); // Ensure fallback is called
  }
}
window.copyToClipboard = copyToClipboard; // Expose globally


/**
 * Renders markdown to sanitized HTML.
 *
 * All markdown rendered from stored content (workflow results, transcripts)
 * MUST go through this helper: marked output is untrusted (LLM-generated or
 * user-edited text) and is inserted via innerHTML. DOMPurify strips scripts,
 * event handlers and javascript: URLs; if DOMPurify failed to load we fail
 * closed and render the raw text as escaped preformatted text instead.
 */
function renderMarkdownSafe(markdownText) {
  const text = String(markdownText ?? '');
  const escapeHtmlFn = typeof window.escapeHtml === 'function' ? window.escapeHtml : null;
  const fallbackHtml = `<pre class="whitespace-pre-wrap break-words">${escapeHtmlFn ? escapeHtmlFn(text) : text}</pre>`;
  if (typeof window.marked === 'undefined' || typeof window.DOMPurify === 'undefined') {
    mainUtilsLogger.warn("renderMarkdownSafe: marked or DOMPurify unavailable; rendering escaped plain text.");
    return fallbackHtml;
  }
  try {
    window.marked.setOptions({ gfm: true, breaks: false });
    return window.DOMPurify.sanitize(window.marked.parse(text));
  } catch (e) {
    mainUtilsLogger.error("renderMarkdownSafe: markdown parsing failed; rendering escaped plain text.", e);
    return fallbackHtml;
  }
}
window.renderMarkdownSafe = renderMarkdownSafe;

// Node test hook (same pattern as progress_timeline.js).
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { renderMarkdownSafe, showNotification, showNotificationWithAction };
}

mainUtilsLogger.info("Utilities ready.");
