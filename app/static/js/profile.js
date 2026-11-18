/*  app/static/js/profile.js */
/* Handles interactions within the User Settings modal. */

const profileLogPrefix = "[ProfileJS]";

// Modal State & Elements
let profileModal = null;
let profileModalOverlay = null;
let profileModalPanel = null;
let profileModalTriggers = [];
let profileModalCloseButtons = [];
let previouslyFocusedElementProfile = null;

function initializeProfileModalElements() {
    profileModal = document.getElementById('profileModal');
    profileModalOverlay = document.getElementById('profileModalOverlay');
    profileModalPanel = document.getElementById('profileModalPanel');
    profileModalTriggers = Array.from(document.querySelectorAll('#profileSettingsBtn, #profileSettingsBtnMobile'));
    if (profileModal) {
        profileModalCloseButtons = Array.from(profileModal.querySelectorAll('#profileModalCloseButtonHeader, #profileModalCloseButtonFooter'));
    }

    if (!profileModal || !profileModalOverlay || !profileModalPanel) {
        window.logger.warn(profileLogPrefix, "One or more Profile modal core elements not found.");
        return false;
    }
    if (profileModalTriggers.length === 0) {
        window.logger.warn(profileLogPrefix, "Profile modal trigger buttons not found.");
    }
    return true;
}

function openProfileModalDialog() {
    if (!profileModal || !profileModalOverlay || !profileModalPanel) {
        window.logger.error(profileLogPrefix, "Cannot open Profile modal: core elements missing.");
        return;
    }
    previouslyFocusedElementProfile = document.activeElement;

    profileModal.classList.remove('hidden');
    profileModalOverlay.classList.remove('hidden');
    profileModalPanel.classList.remove('hidden');

    void profileModal.offsetWidth; // Force reflow for transition

    profileModal.classList.add('opacity-100');
    profileModalOverlay.classList.add('opacity-100');
    profileModalPanel.classList.add('opacity-100', 'scale-100');
    profileModalPanel.classList.remove('opacity-0', 'scale-95');

    profileModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    loadProfileData();

    const focusableElements = Array.from(
        profileModalPanel.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
    ).filter(el => !el.disabled && !el.closest('.hidden'));

    if (focusableElements.length > 0) {
        focusableElements[0].focus();
    } else {
        profileModalPanel.focus();
    }
    window.logger.info(profileLogPrefix, "Profile modal opened.");
}

function closeProfileModalDialog() {
    if (!profileModal || !profileModalOverlay || !profileModalPanel) {
        window.logger.error(profileLogPrefix, "Cannot close Profile modal: core elements missing.");
        return;
    }

    profileModal.classList.remove('opacity-100');
    profileModalOverlay.classList.remove('opacity-100');
    profileModalPanel.classList.remove('opacity-100', 'scale-100');
    profileModalPanel.classList.add('opacity-0', 'scale-95');

    profileModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';

    setTimeout(() => {
        profileModal.classList.add('hidden');
        profileModalOverlay.classList.add('hidden');
    }, 300);

    if (previouslyFocusedElementProfile) {
        previouslyFocusedElementProfile.focus();
        previouslyFocusedElementProfile = null;
    }
    window.logger.info(profileLogPrefix, "Profile modal closed.");
}

function populateProfileLlmModelSelect(select) {
    if (!select) return;
    while (select.options.length > 0) select.remove(0);
    select.appendChild(new Option('-- Use System Default --', ''));

    const catalogModels = window.LLM_MODEL_CATALOG || [];
    const userPermissions = window.USER_PERMISSIONS || {};
    catalogModels.forEach(model => {
        if (!model.code || (model.permission_key && !userPermissions[model.permission_key])) return;
        select.appendChild(new Option(model.display_name || model.code, model.code));
    });
}

function populateProfileLiveModelSelect(select) {
    if (!select) return;
    while (select.options.length > 0) select.remove(0);
    select.appendChild(new Option('-- Use System Default --', ''));
    const seenModelKeys = new Set();
    (window.LIVE_TRANSCRIPTION_MODELS || []).forEach(model => {
        const modelKey = typeof model === 'string' ? model : (model.model_key || model.code);
        const label = typeof model === 'string' ? model : (model.display_name || model.code || modelKey);
        if (modelKey && !seenModelKeys.has(modelKey)) {
            seenModelKeys.add(modelKey);
            select.appendChild(new Option(label, modelKey));
        }
    });
}


document.addEventListener('DOMContentLoaded', function() {
    if (!initializeProfileModalElements()) {
        window.logger.warn(profileLogPrefix, "Profile modal setup skipped due to missing elements.");
        return;
    }

    profileModalTriggers.forEach(trigger => {
        trigger.addEventListener('click', (event) => {
            event.preventDefault();
            openProfileModalDialog();
        });
    });

    profileModalCloseButtons.forEach(button => {
        button.addEventListener('click', closeProfileModalDialog);
    });

    if (profileModalOverlay) {
        profileModalOverlay.addEventListener('click', closeProfileModalDialog);
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && profileModal && !profileModal.classList.contains('hidden')) {
            closeProfileModalDialog();
        }
        // Basic focus trap for Tab key
        if (event.key === 'Tab' && profileModal && !profileModal.classList.contains('hidden')) {
            const focusableElements = Array.from(
                profileModalPanel.querySelectorAll(
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


    const profileForm = document.getElementById('profileForm');
    if (profileForm) {
        profileForm.addEventListener('submit', handleProfileSave);
    } else {
        window.logger.warn(profileLogPrefix, "User settings form element (#profileForm) not found.");
    }

    const changePasswordToggleBtn = document.getElementById('changePasswordToggleBtn');
    const changePasswordSection = document.getElementById('changePasswordSection');
    const passwordToggleIconDisplay = document.getElementById('passwordToggleIconDisplay');

    if (changePasswordToggleBtn && changePasswordSection && passwordToggleIconDisplay) {
        changePasswordToggleBtn.addEventListener('click', () => {
            const isHidden = changePasswordSection.classList.contains('hidden');
            changePasswordSection.classList.toggle('hidden', !isHidden);
            passwordToggleIconDisplay.textContent = isHidden ? 'expand_less' : 'expand_more';
        });
    }

    const changePasswordForm = document.getElementById('changePasswordForm');
    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', handlePasswordChange);
    }
});

async function loadProfileData() {
    window.logger.debug(profileLogPrefix, "Fetching profile data...");
    const usernameInput = document.getElementById('profileUsername');
    const emailInput = document.getElementById('profileEmail');
    const firstNameInput = document.getElementById('profileFirstName');
    const lastNameInput = document.getElementById('profileLastName');
    const langSelect = document.getElementById('profileDefaultLanguage');
    const modelSelect = document.getElementById('profileDefaultModel');
    const workflowModelSelect = document.getElementById('profileDefaultWorkflowModel');
    const auxiliaryModelSelect = document.getElementById('profileDefaultAuxiliaryModel');
    const liveModelSelect = document.getElementById('profileDefaultLiveModel');
    const autoTitleCheckbox = document.getElementById('enable_auto_title_generation');
    const uiLangSelect = document.getElementById('profileLanguage');

    if (!usernameInput || !emailInput || !firstNameInput || !lastNameInput || !langSelect || !modelSelect || !workflowModelSelect || !auxiliaryModelSelect || !liveModelSelect || !autoTitleCheckbox || !uiLangSelect) {
        window.logger.error(profileLogPrefix, "One or more profile form elements not found.");
        window.showNotification('Error loading profile form.', 'error', 4000, false);
        return;
    }

    usernameInput.value = '';
    emailInput.value = '';
    firstNameInput.value = '';
    lastNameInput.value = '';
    langSelect.value = '';
    modelSelect.value = '';
    workflowModelSelect.value = '';
    auxiliaryModelSelect.value = '';
    liveModelSelect.value = '';
    uiLangSelect.value = '';
    autoTitleCheckbox.checked = false;
    clearProfileErrors();

    // Populate transcription language dropdown
    while (langSelect.options.length > 0) langSelect.remove(0);
    const supportedLangs = window.SUPPORTED_LANGUAGE_MAP || {};
    const sortedLangEntries = Object.entries(supportedLangs).sort(([, nameA], [, nameB]) => nameA.localeCompare(nameB));
    if (supportedLangs['auto']) {
        langSelect.appendChild(new Option(supportedLangs['auto'], 'auto'));
    }
    sortedLangEntries.forEach(([code, name]) => {
        if (code !== 'auto') langSelect.appendChild(new Option(name, code));
    });

    // Populate model dropdown
    while (modelSelect.options.length > 0) modelSelect.remove(0);
    const catalogModels = window.TRANSCRIPTION_MODELS || [];
    const userPermissions = window.USER_PERMISSIONS || {};
    const apiKeyStatus = window.API_KEY_STATUS || {};
    const missingKeyMarker = ' (API Key Missing)';
    const seenTranscriptionModels = new Set();
    catalogModels.forEach(model => {
        if (model.permission_key && !userPermissions[model.permission_key]) return;
        const modelKey = model.model_key || model.code;
        if (!modelKey || seenTranscriptionModels.has(modelKey)) return;
        seenTranscriptionModels.add(modelKey);

        const opt = new Option(model.display_name || model.code, modelKey);
        if (model.provider_code) opt.dataset.provider = model.provider_code;
        if (model.model_name) opt.dataset.modelName = model.model_name;
        const requiredKey = model.required_api_key;
        if (requiredKey && !apiKeyStatus[requiredKey]) {
            opt.disabled = true;
            opt.textContent += missingKeyMarker;
        }
        if (requiredKey) opt.dataset.keyRequired = requiredKey;
        modelSelect.appendChild(opt);
    });

    populateProfileLlmModelSelect(workflowModelSelect);
    populateProfileLlmModelSelect(auxiliaryModelSelect);
    populateProfileLiveModelSelect(liveModelSelect);

    // Populate UI language dropdown
    while (uiLangSelect.options.length > 0) uiLangSelect.remove(0);
    const supportedUiLangs = window.SUPPORTED_LANGUAGES || [];
    const uiLangNames = { 'en': 'English', 'es': 'Español', 'fr': 'Français', 'nl': 'Nederlands' };
    supportedUiLangs.forEach(code => {
        uiLangSelect.appendChild(new Option(uiLangNames[code] || code, code));
    });


    try {
        const response = await fetch('/api/user/profile', {
            method: 'GET',
            headers: { 'Accept': 'application/json', 'X-CSRFToken': window.csrfToken }
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP error ${response.status}` }));
            throw new Error(errorData.error || `Failed to fetch profile (${response.status})`);
        }
        const data = await response.json();
        window.logger.debug(profileLogPrefix, "Profile data received:", data);

        usernameInput.value = data.username || '';
        emailInput.value = data.email || '';
        firstNameInput.value = data.first_name || '';
        lastNameInput.value = data.last_name || '';
        langSelect.value = data.default_content_language || '';
        const storedModel = data.default_transcription_model || '';
        const matchedModelOption = Array.from(modelSelect.options).find(
            option => option.value === storedModel
        );
        if (matchedModelOption) matchedModelOption.selected = true;
        else modelSelect.value = '';
        workflowModelSelect.value = data.default_workflow_model || '';
        auxiliaryModelSelect.value = data.default_title_generation_model || '';
        liveModelSelect.value = data.default_live_transcription_model || '';
        uiLangSelect.value = data.language || window.CURRENT_UI_LANGUAGE || 'en';
        autoTitleCheckbox.checked = data.enable_auto_title_generation === true;

    } catch (error) {
        window.logger.error(profileLogPrefix, 'Error fetching profile data:', error);
        window.showNotification(`Error loading profile: ${error.message}`, 'error', 6000, false);
    }
}

async function handleProfileSave(event) {
    event.preventDefault();
    const logPrefix = "[ProfileJS:handleProfileSave]";
    window.logger.info(logPrefix, "Save profile form submitted.");

    const form = event.target;
    const submitButton = document.getElementById('saveProfileBtn');
    clearProfileErrors();

    if (submitButton) {
        submitButton.disabled = true;
        submitButton.innerHTML = 'Saving... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';
    }

    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
    data.first_name = data.first_name || null;
    data.last_name = data.last_name || null;
    const autoTitleCheckbox = document.getElementById('enable_auto_title_generation');
    data.enable_auto_title_generation = autoTitleCheckbox ? autoTitleCheckbox.checked : false;

    window.logger.debug(logPrefix, "Sending data:", data);

    try {
        const response = await fetch('/api/user/profile', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(data)
        });
        const responseData = await response.json();

        if (!response.ok) {
            if (response.status === 400 || response.status === 409) {
                window.logger.warn(logPrefix, `Validation/Conflict Error (${response.status}):`, responseData);
                displayProfileErrors(responseData.errors || { general: responseData.error });
                window.showNotification(responseData.error || 'Please check the form for errors.', 'warning', 4000, false);
            } else {
                throw new Error(responseData.error || `HTTP error ${response.status}`);
            }
        } else {
            window.logger.info(logPrefix, "Profile update successful:", responseData);
            window.showNotification(responseData.message || 'Profile updated successfully!', 'success', 4000, false);
            
            // Reload the page if the language was changed to apply new translations
            if (data.language && data.language !== window.CURRENT_UI_LANGUAGE) {
                window.location.reload();
            } else {
                closeProfileModalDialog();
            }
            
            const displayNameElemDesktop = document.querySelector('#user-menu-button-desktop');
            const mobileDisplayNameElem = document.querySelector('#mobile-nav .text-lg.font-medium.text-gray-800');
            const newDisplayName = data.first_name || data.username;

            if (displayNameElemDesktop) {
                const nameNode = Array.from(displayNameElemDesktop.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0);
                if (nameNode) nameNode.textContent = ` ${newDisplayName} `;
            }
            if (mobileDisplayNameElem) {
                mobileDisplayNameElem.textContent = newDisplayName;
            }
        }
    } catch (error) {
        window.logger.error(logPrefix, 'Error saving profile:', error);
        window.showNotification(`Error saving profile: ${error.message}`, 'error', 6000, false);
        displayProfileErrors({ general: error.message });
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.innerHTML = 'Save Changes <i class="material-icons right text-base ml-2">save</i>';
        }
    }
}

async function handlePasswordChange(event) {
    event.preventDefault();
    const logPrefix = "[ProfileJS:handlePasswordChange]";
    window.logger.info(logPrefix, "Change password form submitted.");

    const form = event.target;
    const submitButton = document.getElementById('submitPasswordChangeBtn');
    clearPasswordErrors();

    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmNewPassword').value;
    if (newPassword !== confirmPassword) {
        window.showNotification('New passwords do not match.', 'warning', 4000, false);
        displayPasswordErrors({ confirm_new_password: ['New passwords must match.'] });
        return;
    }

    const originalButtonHtml = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = 'Updating... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';

    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());

    try {
        const response = await fetch('/api/user/change-password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(data)
        });
        const responseData = await response.json();

        if (!response.ok) {
            if (response.status === 400) {
                window.logger.warn(logPrefix, `Validation Error (400):`, responseData);
                displayPasswordErrors(responseData.errors || { general: responseData.error });
                if (responseData.field === 'current_password') {
                     document.getElementById('currentPassword')?.classList.add('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
                }
                window.showNotification(responseData.error || 'Please check the form for errors.', 'warning', 4000, false);
            } else {
                throw new Error(responseData.error || `HTTP error ${response.status}`);
            }
        } else {
            window.logger.info(logPrefix, "Password change successful:", responseData);
            window.showNotification(responseData.message || 'Password changed successfully!', 'success', 4000, false);
            form.reset();
            const changePasswordSection = document.getElementById('changePasswordSection');
            const passwordToggleIconDisplay = document.getElementById('passwordToggleIconDisplay');
            if (changePasswordSection) changePasswordSection.classList.add('hidden');
            if (passwordToggleIconDisplay) passwordToggleIconDisplay.textContent = 'expand_more';
        }
    } catch (error) {
        window.logger.error(logPrefix, 'Error changing password:', error);
        window.showNotification(`Error changing password: ${error.message}`, 'error', 6000, false);
        displayPasswordErrors({ general: error.message });
    } finally {
        submitButton.disabled = false;
        submitButton.innerHTML = originalButtonHtml;
    }
}

function displayProfileErrors(errors) {
    clearProfileErrors();
    for (const field in errors) {
        const errorMsg = Array.isArray(errors[field]) ? errors[field][0] : errors[field];
        const fieldMappings = {
            default_workflow_model: ['profileDefaultWorkflowModelError', 'profileDefaultWorkflowModel'],
            default_title_generation_model: ['profileDefaultAuxiliaryModelError', 'profileDefaultAuxiliaryModel'],
        };
        const [errorSpanId, inputId] = fieldMappings[field] || [
            `profile${field.charAt(0).toUpperCase() + field.slice(1)}Error`,
            `profile${field.charAt(0).toUpperCase() + field.slice(1)}`,
        ];
        const errorSpan = document.getElementById(errorSpanId);
        const inputElement = document.getElementById(inputId);

        if (errorSpan) {
            errorSpan.textContent = errorMsg;
        } else if (field === 'general') {
             window.logger.warn("Unhandled general profile error:", errorMsg);
        }
        if (inputElement) {
            inputElement.classList.add('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
            inputElement.classList.remove('border-gray-300', 'focus:border-primary', 'focus:ring-primary');
        }
    }
}

function clearProfileErrors() {
    document.querySelectorAll('#profileForm .text-xs.text-red-600').forEach(span => span.textContent = '');
    document.querySelectorAll('#profileForm input, #profileForm select').forEach(input => {
        input.classList.remove('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
        input.classList.add('border-gray-300', 'focus:border-primary', 'focus:ring-primary');
    });
}

function displayPasswordErrors(errors) {
    clearPasswordErrors();
    for (const field in errors) {
        const errorMsg = Array.isArray(errors[field]) ? errors[field][0] : errors[field];
        let errorSpanId = '';
        let inputElementId = '';

        if (field === 'current_password') { errorSpanId = 'currentPasswordError'; inputElementId = 'currentPassword'; }
        else if (field === 'new_password') { errorSpanId = 'newPasswordError'; inputElementId = 'newPassword'; }
        else if (field === 'confirm_new_password') { errorSpanId = 'confirmNewPasswordError'; inputElementId = 'confirmNewPassword'; }
        else if (field === 'general') { window.logger.warn("Unhandled general password error:", errorMsg); }

        const errorSpan = document.getElementById(errorSpanId);
        const inputElement = document.getElementById(inputElementId);

        if (errorSpan) errorSpan.textContent = errorMsg;
        if (inputElement) {
            inputElement.classList.add('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
            inputElement.classList.remove('border-gray-300', 'focus:border-primary', 'focus:ring-primary');
        }
    }
}

function clearPasswordErrors() {
    document.querySelectorAll('#changePasswordForm .text-xs.text-red-600').forEach(span => span.textContent = '');
    document.querySelectorAll('#changePasswordForm input').forEach(input => {
        input.classList.remove('border-red-500', 'focus:border-red-500', 'focus:ring-red-500');
        input.classList.add('border-gray-300', 'focus:border-primary', 'focus:ring-primary');
    });
}

function escapeHtmlProfile(str) {
    if (str === null || str === undefined) return '';
    return String(str)
          .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#39;");
}
