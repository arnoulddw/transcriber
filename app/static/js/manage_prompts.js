// ./app/static/js/manage_prompts.js
// Handles interactions on the user's "Manage Workflow Prompts" page.

const managePromptsLogPrefix = "[ManagePromptsJS]";

// Default colors for the color picker
const pastelColors = [
    "#ffffff", "#ffd1dc", "#aec6cf", "#cfffd1", "#fffacd", "#e6e6fa", "#ffb347"
];

// Map of color hex codes to human-readable names, falling back to hex if not found.
// Uses the global COLOR_NAME_MAP injected from base.html if available.
const colorNameMap = window.COLOR_NAME_MAP || {
    "#ffffff": "Default", "#ffd1dc": "Pink", "#aec6cf": "Blue Grey",
    "#cfffd1": "Mint Green", "#fffacd": "Lemon", "#e6e6fa": "Lavender",
    "#ffb347": "Orange"
};

// Edit Modal State & Elements
let editPromptModal = null;
let editPromptModalOverlay = null;
let editPromptModalPanel = null;
let editPromptModalCloseButtons = [];
let previouslyFocusedElementEditPrompt = null;

/**
 * Initializes references to the core elements of the Edit Prompt modal.
 * @returns {boolean} True if all core elements are found, false otherwise.
 */
function initializeEditPromptModalElements() {
    editPromptModal = document.getElementById('editPromptModal');
    editPromptModalOverlay = document.getElementById('editPromptModalOverlay');
    editPromptModalPanel = document.getElementById('editPromptModalPanel');
    if (editPromptModal) {
        editPromptModalCloseButtons = Array.from(editPromptModal.querySelectorAll('#editPromptModalCloseButtonHeader, #editPromptModalCloseButtonFooter'));
    }

    if (!editPromptModal || !editPromptModalOverlay || !editPromptModalPanel) {
        window.logger.warn(managePromptsLogPrefix, "One or more Edit Prompt modal core elements not found.");
        return false;
    }
    return true;
}

/**
 * Opens the Edit Prompt modal dialog with Tailwind CSS transitions.
 * Manages focus and ARIA attributes.
 */
function openEditPromptModalDialog() {
    if (!editPromptModal || !editPromptModalOverlay || !editPromptModalPanel) {
        window.logger.error(managePromptsLogPrefix, "Cannot open Edit Prompt modal: core elements missing.");
        return;
    }
    previouslyFocusedElementEditPrompt = document.activeElement;

    editPromptModal.classList.remove('hidden');
    editPromptModalOverlay.classList.remove('hidden');
    editPromptModalPanel.classList.remove('hidden');

    void editPromptModal.offsetWidth; // Force reflow for transition

    editPromptModal.classList.add('opacity-100');
    editPromptModalOverlay.classList.add('opacity-100');
    editPromptModalPanel.classList.add('opacity-100', 'scale-100');
    editPromptModalPanel.classList.remove('opacity-0', 'scale-95');

    editPromptModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden'; // Prevent background scroll

    // Focus trap: set focus to the first focusable element in the modal
    const focusableElements = Array.from(
        editPromptModalPanel.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
    ).filter(el => !el.disabled && !el.closest('.hidden'));

    if (focusableElements.length > 0) {
        focusableElements[0].focus();
    } else {
        editPromptModalPanel.focus(); // Fallback focus
    }
    window.logger.info(managePromptsLogPrefix, "Edit Prompt modal opened.");
}

/**
 * Closes the Edit Prompt modal dialog with Tailwind CSS transitions.
 * Manages focus and ARIA attributes.
 */
function closeEditPromptModalDialog() {
    if (!editPromptModal || !editPromptModalOverlay || !editPromptModalPanel) {
        window.logger.error(managePromptsLogPrefix, "Cannot close Edit Prompt modal: core elements missing.");
        return;
    }

    editPromptModal.classList.remove('opacity-100');
    editPromptModalOverlay.classList.remove('opacity-100');
    editPromptModalPanel.classList.remove('opacity-100', 'scale-100');
    editPromptModalPanel.classList.add('opacity-0', 'scale-95');

    editPromptModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = ''; // Restore background scroll

    // Delay hiding to allow for transition
    setTimeout(() => {
        editPromptModal.classList.add('hidden');
        editPromptModalOverlay.classList.add('hidden');
    }, 300);

    // Restore focus to the element that opened the modal
    if (previouslyFocusedElementEditPrompt) {
        previouslyFocusedElementEditPrompt.focus();
        previouslyFocusedElementEditPrompt = null;
    }
    window.logger.info(managePromptsLogPrefix, "Edit Prompt modal closed.");
}


document.addEventListener('DOMContentLoaded', function() {
    // Initialize Edit Prompt Modal elements and event listeners
    if (!initializeEditPromptModalElements()) {
        window.logger.warn(managePromptsLogPrefix, "Edit Prompt modal setup skipped due to missing elements.");
    } else {
        editPromptModalCloseButtons.forEach(button => {
            button.addEventListener('click', closeEditPromptModalDialog);
        });
        if (editPromptModalOverlay) {
            editPromptModalOverlay.addEventListener('click', closeEditPromptModalDialog);
        }
        // Keyboard navigation for the modal (Escape key and Tab trapping)
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && editPromptModal && !editPromptModal.classList.contains('hidden')) {
                closeEditPromptModalDialog();
            }
            // Basic focus trap for Tab key within the Edit Prompt modal
            if (event.key === 'Tab' && editPromptModal && !editPromptModal.classList.contains('hidden')) {
                const focusableElements = Array.from(
                    editPromptModalPanel.querySelectorAll(
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
    }

    // Event listener for the "Add new workflow" form
    const addForm = document.getElementById('addPromptForm');
    if (addForm) {
        addForm.addEventListener('submit', handleAddPrompt);
        window.logger.debug(managePromptsLogPrefix, "Add prompt form listener attached.");
        populateColorPicker('newPromptColorOptions', 'newPromptColor');
    } else {
        window.logger.warn(managePromptsLogPrefix, "Add prompt form not found.");
    }

    // Event listener for the "Edit workflow" form (inside the modal)
    const editForm = document.getElementById('editPromptForm');
    if (editForm) {
        editForm.addEventListener('submit', handleSaveEditPrompt);
        window.logger.debug(managePromptsLogPrefix, "Edit prompt form listener attached.");
        populateColorPicker('editPromptColorOptions', 'editPromptColor');
    } else {
        window.logger.warn(managePromptsLogPrefix, "Edit prompt form not found.");
    }

    // Event delegation for Edit/Delete buttons on the saved prompts list
    const promptsList = document.getElementById('savedPromptsList');
    if (promptsList) {
        promptsList.addEventListener('click', function(event) {
            const editButton = event.target.closest('.edit-prompt-btn');
            const deleteButton = event.target.closest('.delete-prompt-btn');

            if (editButton) {
                event.preventDefault();
                const promptItem = editButton.closest('li[data-prompt-id]');
                const promptId = promptItem?.dataset.promptId;
                if (promptId) {
                    openEditPromptModal(promptId);
                }
            } else if (deleteButton) {
                event.preventDefault();
                const promptItem = deleteButton.closest('li[data-prompt-id]');
                const promptId = promptItem?.dataset.promptId;
                // Get title from the pill or the hidden display for confirmation
                const promptTitle = promptItem?.querySelector('.prompt-label-pill')?.textContent.trim() ||
                                    promptItem?.querySelector('.prompt-title-display')?.textContent.trim();
                if (promptId && promptTitle) {
                    handleDeletePrompt(promptId, promptTitle, promptItem);
                }
            }
        });
        window.logger.debug(managePromptsLogPrefix, "Edit/Delete prompt listeners attached.");
    } else {
        window.logger.warn(managePromptsLogPrefix, "Saved prompts list not found.");
    }

    // Auto-resize for textareas
    const newPromptTextarea = document.getElementById('newPromptText');
    if (newPromptTextarea) {
        newPromptTextarea.addEventListener('input', autoResizeTextarea);
    }
    const editPromptTextarea = document.getElementById('editPromptText');
    if (editPromptTextarea) {
        editPromptTextarea.addEventListener('input', autoResizeTextarea);
    }

    // Initial load of user prompts
    loadUserPrompts();
});

/**
 * Automatically resizes a textarea to fit its content.
 * @param {Event} event - The input event from the textarea.
 */
function autoResizeTextarea(event) {
    this.style.height = 'auto'; // Reset height to shrink if text is deleted
    this.style.height = (this.scrollHeight) + 'px'; // Set to scroll height
}

/**
 * Determines if black or white text provides better contrast against a given background hex color.
 * @param {string} hexColor - Background color in hex format (e.g., "#ffffff").
 * @returns {string} 'black' or 'white'.
 */
function getTextColorForBackground(hexColor) {
    try {
        const hex = hexColor.replace('#', '');
        const r = parseInt(hex.substring(0, 2), 16);
        const g = parseInt(hex.substring(2, 4), 16);
        const b = parseInt(hex.substring(4, 6), 16);
        // Calculate luminance (standard formula)
        const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        return luminance > 0.5 ? 'black' : 'white';
    } catch (e) {
        window.logger.error(managePromptsLogPrefix, `Error calculating text color for ${hexColor}:`, e);
        return 'black'; // Default to black on error
    }
}

/**
 * Populates a color picker container with color swatches.
 * @param {string} containerId - The ID of the div element to hold the color swatches.
 * @param {string} hiddenInputId - The ID of the hidden input field to store the selected color.
 */
function populateColorPicker(containerId, hiddenInputId) {
    const container = document.getElementById(containerId);
    const hiddenInput = document.getElementById(hiddenInputId);
    if (!container || !hiddenInput) {
        window.logger.warn(managePromptsLogPrefix, `Color picker container or hidden input not found: ${containerId}, ${hiddenInputId}`);
        return;
    }

    container.innerHTML = ''; // Clear existing options

    pastelColors.forEach(color => {
        const option = document.createElement('div');
        // Tailwind classes for styling the color swatch.
        // Base border is always visible: a border-transparent base loses the
        // cascade against .border-*color* rules in the compiled CSS (they come
        // earlier), which made the white swatch invisible on the card.
        option.className = 'flex-shrink-0 w-badge h-badge rounded-full cursor-pointer border border-black/10 transition-all duration-200 ease-in-out';
        option.dataset.color = color;
        option.style.backgroundColor = color;
        option.setAttribute('title', colorNameMap[color] || color); // Tooltip with color name

        option.addEventListener('click', function() {
            const selectedColor = this.dataset.color;
            hiddenInput.value = selectedColor; // Update hidden input
            // Update visual selection state for all swatches
            container.querySelectorAll('div[data-color]').forEach(el => {
                el.classList.remove('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
            });
            this.classList.add('ring-2', 'ring-offset-2', 'ring-primary');
            if (selectedColor === "#ffffff") { // Darker border keeps white visible inside its own ring
                this.classList.add('border-gray-700');
            }
        });
        container.appendChild(option);
    });

    // Set initial selected color based on hidden input's value or default to white
    const initialColor = hiddenInput.value || '#ffffff';
    const initialOption = container.querySelector(`div[data-color="${initialColor}"]`);
    if (initialOption) {
        initialOption.classList.add('ring-2', 'ring-offset-2', 'ring-primary');
        if (initialColor === "#ffffff") {
            initialOption.classList.add('border-gray-700');
        }
    } else { // Fallback if initialColor in hidden input is invalid
        const defaultWhiteOption = container.querySelector('div[data-color="#ffffff"]');
        if (defaultWhiteOption) {
            defaultWhiteOption.classList.add('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
        }
        hiddenInput.value = '#ffffff';
    }
}

/**
 * Fetches user's saved prompts from the API and populates the list.
 */
async function loadUserPrompts() {
    const logPrefix = "[ManagePromptsJS:loadUserPrompts]";
    window.logger.debug(logPrefix, "Fetching user prompts...");
    const promptsList = document.getElementById('savedPromptsList');
    const placeholder = document.getElementById('prompts-placeholder');

    if (!promptsList || !placeholder) {
        window.logger.error(logPrefix, "Prompts list or placeholder element not found.");
        return;
    }

    // Show loading placeholder
    placeholder.textContent = 'Loading workflows...';
    placeholder.style.display = 'block'; // Ensure it's visible
    promptsList.innerHTML = ''; // Clear previous items
    promptsList.appendChild(placeholder); // Add placeholder back

    try {
        const response = await fetch('/api/user/prompts', {
            method: 'GET',
            headers: { 'Accept': 'application/json', 'X-CSRFToken': window.csrfToken }
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP error ${response.status}` }));
            throw new Error(errorData.error || `Failed to fetch prompts (${response.status})`);
        }

        const data = await response.json();
        window.logger.debug(logPrefix, "User prompts received:", data);

        promptsList.innerHTML = ''; // Clear loading placeholder

        if (data && data.length > 0) {
            data.forEach(prompt => addPromptToList(prompt, false));
        } else {
            placeholder.textContent = 'You have no saved workflows yet.';
            promptsList.appendChild(placeholder);
            placeholder.style.display = 'block';
        }

    } catch (error) {
        window.logger.error(logPrefix, 'Error loading user prompts:', error);
        promptsList.innerHTML = ''; // Clear list on error
        placeholder.textContent = `Error loading workflows: ${error.message}`;
        promptsList.appendChild(placeholder); // Show error in placeholder
        placeholder.style.display = 'block';
        window.showNotification(`Error loading workflows: ${error.message}`, 'error', 6000, false);
    }
}
window.loadUserPrompts = loadUserPrompts;

/**
 * Adds a single prompt item to the saved prompts list in the UI.
 * @param {object} prompt - The prompt object data.
 * @param {boolean} [prepend=false] - If true, prepends the item; otherwise, appends.
 */
function addPromptToList(prompt, prepend = false) {
    const promptsList = document.getElementById('savedPromptsList');
    if (!promptsList) return;

    const placeholder = document.getElementById('prompts-placeholder');
    if (placeholder) placeholder.style.display = 'none';

    const listItem = document.createElement('li');
    listItem.className = 'raised-card flex items-start justify-between gap-4 p-4 hover:shadow-raised-hover';
    listItem.dataset.promptId = prompt.id;
    const bgColor = prompt.color || '#ffffff';
    listItem.dataset.promptColor = bgColor;
    // Prompt text lives here now: its gray display box was removed from the card.
    listItem.dataset.promptText = prompt.prompt_text || '';

    const textColor = getTextColorForBackground(bgColor);

    const isSystemDefined = prompt.source_template_id;
    const displayTitle = isSystemDefined
        ? (window.i18n.systemDefined || 'System defined - ') + prompt.title
        : prompt.title;

    const templateIconHtml = isSystemDefined
        ? `<i class="material-icons text-base text-primary align-middle ml-2" title="System defined workflow">flash_on</i>`
        : '';

    const actionButtonsHtml = isSystemDefined
        ? ''
        : `<div class="flex-shrink-0 flex gap-0.5">
            <button class="edit-prompt-btn icon-btn" title="Edit workflow">
                <span class="sr-only">Edit</span>
                <i class="material-icons text-base">edit</i>
            </button>
            <button class="delete-prompt-btn icon-btn icon-btn--danger" title="Delete workflow">
                <span class="sr-only">Delete</span>
                <i class="material-icons text-base">delete</i>
            </button>
        </div>`;

    listItem.innerHTML = `
        <div class="flex-grow min-w-0">
            <div class="flex items-center">
                <div class="prompt-label-pill inline-block px-3 py-1 text-xs font-semibold rounded-full"
                     style="background-color: ${escapeHtml(bgColor)}; color: ${escapeHtml(textColor)};">
                    ${escapeHtml(displayTitle)}
                </div>
                ${templateIconHtml}
            </div>
            <div class="prompt-text-display mt-1.5 text-sm text-text-strong whitespace-pre-wrap break-words">${escapeHtml(prompt.prompt_text.trim())}</div>
        </div>
        ${actionButtonsHtml}
    `;

    if (prepend) {
        promptsList.prepend(listItem);
    } else {
        promptsList.appendChild(listItem);
    }
}

/**
 * Handles the submission of the "Add new workflow" form.
 * @param {Event} event - The form submission event.
 */
async function handleAddPrompt(event) {
    event.preventDefault();
    const logPrefix = "[ManagePromptsJS:handleAdd]";
    const form = event.target;
    const titleInput = document.getElementById('newPromptTitle');
    const textInput = document.getElementById('newPromptText');
    const colorInput = document.getElementById('newPromptColor');
    const submitButton = form.querySelector('button[type="submit"]');

    const title = titleInput.value.trim();
    const promptText = textInput.value.trim();
    const color = colorInput.value || '#ffffff';

    if (!title || !promptText) {
        window.showNotification('Please provide both a label and prompt text.', 'warning', 4000, false);
        return;
    }

    window.logger.info(logPrefix, "Submitting new workflow:", title, "Color:", color);
    const originalButtonHtml = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = 'Adding... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';

    const payload = { title: title, prompt_text: promptText, color: color };

    try {
        const response = await fetch('/api/user/prompts', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP error ${response.status}`);

        window.showNotification(data.message || 'Workflow added successfully!', 'success', 4000, false);
        addPromptToList(data.prompt, true);

        titleInput.value = '';
        textInput.value = '';
        textInput.style.height = 'auto';

        const colorOptionsContainer = document.getElementById('newPromptColorOptions');
        if (colorOptionsContainer) {
            colorOptionsContainer.querySelectorAll('div[data-color]').forEach(el => {
                el.classList.remove('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
            });
            const defaultWhiteOption = colorOptionsContainer.querySelector('div[data-color="#ffffff"]');
            if (defaultWhiteOption) {
                defaultWhiteOption.classList.add('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
            }
            colorInput.value = '#ffffff';
        }
    } catch (error) {
        window.logger.error(logPrefix, "Error adding workflow:", error);
        window.showNotification(`Error: ${error.message}`, 'error', 6000, false);
    } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = originalButtonHtml;
    }
}

/**
 * Opens the edit prompt modal and populates it with the selected prompt's data.
 * @param {string} promptId - The ID of the prompt to edit.
 */
function openEditPromptModal(promptId) {
    const logPrefix = `[ManagePromptsJS:openEdit:${promptId}]`;
    const promptItem = document.querySelector(`li[data-prompt-id="${promptId}"]`);
    if (!promptItem) {
        window.logger.error(logPrefix, "Could not find workflow item in list.");
        window.showNotification('Error: Could not find workflow to edit.', 'error', 4000, false);
        return;
    }

    const titlePill = promptItem.querySelector('.prompt-label-pill');
    const title = titlePill ? titlePill.textContent.trim() : 'Unknown Title';
    const text = (promptItem.dataset.promptText || '').trim();
    const color = promptItem.dataset.promptColor || '#ffffff';

    const idInput = document.getElementById('editPromptId');
    const titleInput = document.getElementById('editPromptTitle');
    const textInput = document.getElementById('editPromptText');
    const colorInput = document.getElementById('editPromptColor');
    const colorOptionsContainer = document.getElementById('editPromptColorOptions');

    if (!idInput || !titleInput || !textInput || !colorInput || !colorOptionsContainer) {
        window.logger.error(logPrefix, "Edit modal form elements not found.");
        return;
    }

    idInput.value = promptId;
    titleInput.value = title;
    textInput.value = text;
    colorInput.value = color;

    colorOptionsContainer.querySelectorAll('div[data-color]').forEach(el => {
        el.classList.remove('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
    });
    const selectedOption = colorOptionsContainer.querySelector(`div[data-color="${color}"]`);
    if (selectedOption) {
        selectedOption.classList.add('ring-2', 'ring-offset-2', 'ring-primary');
        if (color === "#ffffff") {
            selectedOption.classList.add('border-gray-700');
        }
    } else {
        const defaultWhiteOption = colorOptionsContainer.querySelector('div[data-color="#ffffff"]');
        if (defaultWhiteOption) {
            defaultWhiteOption.classList.add('ring-2', 'ring-offset-2', 'ring-primary', 'border-gray-700');
        }
        colorInput.value = '#ffffff';
    }

    textInput.style.height = 'auto';
    textInput.style.height = (textInput.scrollHeight) + 'px';

    openEditPromptModalDialog();
    window.logger.info(logPrefix, "Edit modal opened for workflow:", title, "Color:", color);
}

/**
 * Handles saving the edited prompt.
 * @param {Event} event - The form submission event.
 */
async function handleSaveEditPrompt(event) {
    event.preventDefault();
    const logPrefix = "[ManagePromptsJS:handleSaveEdit]";
    const form = event.target;
    const promptId = document.getElementById('editPromptId').value;
    const titleInput = document.getElementById('editPromptTitle');
    const textInput = document.getElementById('editPromptText');
    const colorInput = document.getElementById('editPromptColor');
    const saveButton = document.getElementById('saveEditPromptBtn');

    const title = titleInput.value.trim();
    const promptText = textInput.value.trim();
    const color = colorInput.value || '#ffffff';

    if (!promptId || !title || !promptText) {
        window.showNotification('Please provide both a label and prompt text.', 'warning', 4000, false);
        return;
    }

    window.logger.info(logPrefix, `Saving changes for workflow ID: ${promptId}`, "Color:", color);
    const originalButtonHtml = saveButton.innerHTML;
    saveButton.disabled = true;
    saveButton.innerHTML = 'Saving... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';

    const payload = { title: title, prompt_text: promptText, color: color };

    try {
        const response = await fetch(`/api/user/prompts/${promptId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP error ${response.status}`);

        window.showNotification(data.message || 'Workflow updated successfully!', 'success', 4000, false);
        closeEditPromptModalDialog();

        loadUserPrompts();
    } catch (error) {
        window.logger.error(logPrefix, "Error updating workflow:", error);
        window.showNotification(`Error: ${error.message}`, 'error', 6000, false);
    } finally {
        saveButton.disabled = false;
        saveButton.innerHTML = originalButtonHtml;
    }
}

/**
 * Handles deleting a prompt after confirmation.
 * @param {string} promptId - The ID of the prompt to delete.
 * @param {string} promptTitle - The title of the prompt for confirmation message.
 * @param {HTMLElement} listItemElement - The <li> element to remove from the list.
 */
async function handleDeletePrompt(promptId, promptTitle, listItemElement) {
    const logPrefix = `[ManagePromptsJS:handleDelete:${promptId}]`;
    if (!confirm(`Are you sure you want to delete the workflow "${promptTitle}"?`)) {
        window.logger.debug(logPrefix, "Delete cancelled by user.");
        return;
    }
    window.logger.info(logPrefix, "Deleting workflow...");
    const deleteButton = listItemElement.querySelector('.delete-prompt-btn');
    if (deleteButton) deleteButton.disabled = true;

    try {
        const response = await fetch(`/api/user/prompts/${promptId}`, {
            method: 'DELETE',
            headers: { 'Accept': 'application/json', 'X-CSRFToken': window.csrfToken }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP error ${response.status}`);

        window.showNotification(data.message || 'Workflow deleted successfully!', 'success', 4000, false);
        window.logger.info(logPrefix, "Workflow deleted successfully via API.");
        listItemElement.remove();

        const promptsList = document.getElementById('savedPromptsList');
        const placeholder = document.getElementById('prompts-placeholder');
        if (promptsList && placeholder && promptsList.children.length === 0) {
             placeholder.textContent = 'You have no saved workflows yet.';
             promptsList.appendChild(placeholder);
             placeholder.style.display = 'block';
        }
    } catch (error) {
        window.logger.error(logPrefix, "Error deleting workflow:", error);
        window.showNotification(`Error: ${error.message}`, 'error', 6000, false);
        if (deleteButton) deleteButton.disabled = false;
    }
}

/**
 * Escapes HTML special characters in a string.
 * @param {string} str - The string to escape.
 * @returns {string} The escaped string.
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
