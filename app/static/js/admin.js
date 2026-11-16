// ./app/static/js/admin.js
/* JavaScript functionalities for the admin panel pages. */

/**
 * Handles saving the template workflow via Fetch API.
 * This function is called from create_edit_template_prompt.html
 */
window.handleSaveTemplateWorkflow = async function() { // MODIFIED: Attached to window
    const logPrefix = "[AdminJS:handleSaveTemplateWorkflow]";
    const form = document.getElementById('templateWorkflowForm');
    const saveButton = document.getElementById('saveTemplateWorkflowBtn');
    const promptIdInput = document.getElementById('templatePromptId');
    const promptId = promptIdInput ? promptIdInput.value : null;

    const titleInput = document.getElementById('title');
    const promptTextInput = document.getElementById('prompt_text');
    const languageSelect = document.getElementById('language');
    const colorInput = document.getElementById('templateColor');

    const title = titleInput ? titleInput.value.trim() : '';
    const prompt_text = promptTextInput ? promptTextInput.value.trim() : '';
    const language = languageSelect ? languageSelect.value : '';
    const color = colorInput ? colorInput.value : '#ffffff';

    if (!title || !prompt_text) {
        window.showNotification('Please provide both a label and prompt text.', 'warning', 4000, false);
        return;
    }
    window.logger.info(logPrefix, `Saving template. ID: ${promptId || 'New'}, Title: ${title}, Color: ${color}`);

    saveButton.disabled = true;
    const originalButtonHtml = saveButton.innerHTML;
    saveButton.innerHTML = 'Saving... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';

    const payload = {
        title: title,
        prompt_text: prompt_text,
        language: language,
        color: color
    };
    const url = promptId ? `/api/admin/template-workflows/${promptId}` : '/api/admin/template-workflows';
    const method = promptId ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || `HTTP error ${response.status}`);
        }

        const successMessage = data.message || 'Template workflow saved successfully!';
        if (typeof window.persistNotificationForNextPage === 'function') {
            window.persistNotificationForNextPage(successMessage, 'success');
        } else {
            window.showNotification(successMessage, 'success', 4000, false);
        }
        window.logger.info(logPrefix, "Save successful via API.");

        window.location.href = "/admin/template-workflows";

    } catch (error) {
        window.logger.error(logPrefix, "Error saving template workflow:", error);
        window.showNotification(`Error: ${error.message}`, 'error', 6000, false);
        saveButton.disabled = false;
        saveButton.innerHTML = originalButtonHtml;
    }
};


/**
 * Handles the deletion of a user after confirmation.
 * @param {string|number} userId - The ID of the user to delete.
 * @param {string} username - The username for the confirmation message.
 */
function handleDeleteUser(userId, username) {
    const logPrefix = `[AdminJS:handleDeleteUser:${userId}]`;

    if (!confirm(`Are you sure you want to permanently delete user "${username}" (ID: ${userId})?\n\nThis action cannot be undone.`)) {
        window.logger.debug(logPrefix, "Delete cancelled by user.");
        return;
    }

    window.logger.info(logPrefix, `Attempting to delete user...`);
    const deleteButton = document.querySelector(`.delete-user-btn[data-user-id="${userId}"]`);
    const originalButtonHtml = deleteButton ? deleteButton.innerHTML : '<i class="material-icons text-base">delete</i>';
    if (deleteButton) {
        deleteButton.disabled = true;
        deleteButton.innerHTML = '<span class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';
    }

    fetch(`/api/admin/users/${userId}`, {
        method: 'DELETE',
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (!response.ok) {
             return response.json()
                .catch(() => ({ error: `HTTP error! Status: ${response.status}` }))
                .then(errData => { throw new Error(errData.error || `HTTP error! Status: ${response.status}`); });
        }
        return response.json();
    })
    .then(data => {
        window.showNotification(data.message || `User "${username}" deleted successfully.`, 'success', 4000, false);
        window.logger.info(logPrefix, "User deleted successfully.");
        const rowToRemove = document.querySelector(`#usersTableBody tr[data-user-id="${userId}"]`);
        if (rowToRemove) {
            rowToRemove.remove();
        } else {
            window.logger.warn(logPrefix, "Row not found in table after deletion, reloading page.");
            window.location.reload();
        }
        const tableBody = document.getElementById('usersTableBody');
        if (tableBody && tableBody.rows.length === 0) {
             tableBody.innerHTML = '<tr><td colspan="9" class="px-6 py-4 text-center text-gray-500">No users found.</td></tr>';
        }
    })
    .catch(error => {
        window.logger.error(logPrefix, `Error deleting user:`, error);
        window.showNotification(`Error deleting user: ${error.message}`, 'error', 5000, false);
        if (deleteButton) {
            deleteButton.disabled = false;
            deleteButton.innerHTML = originalButtonHtml;
        }
    });
}

/**
 * Simple HTML escaping function to prevent XSS.
 * @param {string} str - Input string.
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



/**
 * Formats minutes (float) into a readable string, rounded up to the nearest whole minute.
 * @param {number|null|undefined} totalMinutes - The total number of minutes (float).
 * @returns {string} Formatted time string (e.g., "15 min", "1 min") or 'N/A'.
 */

/**
 * Handles clicking on the edit role icon button.
 * @param {HTMLElement} editButton - The edit button element that was clicked.
 */
function handleRoleEditClick(editButton) {
    if (editButton.disabled) {
        window.logger.debug("[AdminJS] Edit role button is disabled for this user.");
        return;
    }

    const parentCell = editButton.closest('tr').querySelector('td[data-label="Role"]');
    if (!parentCell) return;

    const roleSpan = parentCell.querySelector('.role-display');
    const roleSelect = parentCell.querySelector('.role-select');

    if (roleSpan && roleSelect) {
        roleSpan.classList.add('hidden');
        roleSelect.classList.remove('hidden');
        roleSelect.focus();
        window.logger.debug("[AdminJS] Role editing started for user:", roleSelect.dataset.userId);
    } else {
        window.logger.error("[AdminJS] Could not find role span or select elements within the cell.");
    }
}


/**
 * Handles changing the value in the role select dropdown.
 * @param {Event} event - The change event.
 */
function handleRoleChange(event) {
    const roleSelect = event.target;
    if (!roleSelect.classList.contains('role-select')) return;

    const userId = roleSelect.dataset.userId;
    const newRoleId = roleSelect.value;
    const parentCell = roleSelect.closest('td');
    const roleSpan = parentCell.querySelector('.role-display');
    const originalRoleId = roleSpan.dataset.roleId;

    window.logger.debug(`[AdminJS] Role changed for user ${userId} from ${originalRoleId} to ${newRoleId}`);

    if (newRoleId === originalRoleId) {
        roleSelect.classList.add('hidden');
        roleSpan.classList.remove('hidden');
        window.logger.debug("[AdminJS] Role selection reverted to original. No API call needed.");
        return;
    }

    roleSelect.disabled = true;
    const loadingIndicator = document.createElement('span');
    loadingIndicator.className = 'role-loading-indicator ml-1';
    loadingIndicator.innerHTML = '<span class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent align-middle"></span>';
    roleSelect.parentNode.insertBefore(loadingIndicator, roleSelect.nextSibling);

    updateUserRole(userId, newRoleId, roleSelect, roleSpan, originalRoleId);
}

/**
 * Handles the select dropdown losing focus (blur).
 * If the value hasn't changed, revert the UI.
 * @param {Event} event - The blur event.
 */
function handleRoleBlur(event) {
    const roleSelect = event.target;
    if (!roleSelect.classList.contains('role-select')) return;

    setTimeout(() => {
        if (!roleSelect.classList.contains('hidden') && document.activeElement !== roleSelect) {
            const parentCell = roleSelect.closest('td');
            const roleSpan = parentCell.querySelector('.role-display');
            const loadingIndicator = parentCell.querySelector('.role-loading-indicator');

            roleSelect.classList.add('hidden');
            roleSpan.classList.remove('hidden');
            roleSelect.value = roleSpan.dataset.roleId; // Reset to original value
            roleSelect.disabled = false;
            if (loadingIndicator) loadingIndicator.remove();
            window.logger.debug("[AdminJS] Role select blurred without save. Reverted UI.");
        }
    }, 150);
}

/**
 * Handles Escape key press within the role select dropdown to cancel editing.
 * @param {Event} event - The keydown event.
 */
function handleRoleKeydown(event) {
    const roleSelect = event.target;
    if (!roleSelect.classList.contains('role-select')) return;

    if (event.key === 'Escape') {
        event.preventDefault();
        const parentCell = roleSelect.closest('td');
        const roleSpan = parentCell.querySelector('.role-display');
        const loadingIndicator = parentCell.querySelector('.role-loading-indicator');

        roleSelect.classList.add('hidden');
        roleSpan.classList.remove('hidden');
        roleSelect.value = roleSpan.dataset.roleId; // Reset to original value
        roleSelect.disabled = false;
        if (loadingIndicator) loadingIndicator.remove();
        window.logger.debug("[AdminJS] Role editing cancelled via Escape key.");
    }
}


/**
 * Sends the API request to update the user's role.
 * @param {string} userId - The ID of the user.
 * @param {string} newRoleId - The ID of the new role.
 * @param {HTMLSelectElement} roleSelect - The select element.
 * @param {HTMLElement} roleSpan - The span element displaying the role.
 * @param {string} originalRoleId - The original role ID before editing.
 */
function updateUserRole(userId, newRoleId, roleSelect, roleSpan, originalRoleId) {
    const logPrefix = `[AdminJS:updateUserRole:${userId}]`;
    const loadingIndicator = roleSelect.parentNode.querySelector('.role-loading-indicator');

    fetch(`/api/admin/users/${userId}/role`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': window.csrfToken
        },
        body: JSON.stringify({ role_id: newRoleId })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.error || `HTTP error ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        window.logger.info(logPrefix, "Role update successful:", data.message);
        window.showNotification(data.message || 'Role updated successfully!', 'success', 4000, false);

        const newRoleName = roleSelect.options[roleSelect.selectedIndex].text;
        roleSpan.textContent = newRoleName;
        roleSpan.dataset.roleId = newRoleId;

        roleSelect.classList.add('hidden');
        roleSpan.classList.remove('hidden');
    })
    .catch(error => {
        window.logger.error(logPrefix, "Error updating role:", error);
        window.showNotification(`Error: ${error.message}`, 'error', 5000, false);
        roleSelect.value = originalRoleId;
        roleSelect.classList.add('hidden');
        roleSpan.classList.remove('hidden');
    })
    .finally(() => {
        roleSelect.disabled = false;
        if (loadingIndicator) {
            loadingIndicator.remove();
        }
    });
}


/**
 * Initializes a tab group with ARIA attributes and keyboard navigation.
 * @param {string} tabGroupId - The ID of the div containing the tablist and tabpanels.
 */
function initializeTabs(tabGroupId) {
    const tabGroup = document.getElementById(tabGroupId);
    if (!tabGroup) {
        window.logger.debug(`Tab group with ID '${tabGroupId}' not found; skipping initialization.`);
        return;
    }

    const tabButtons = Array.from(tabGroup.querySelectorAll('[role="tab"]'));
    if (tabButtons.length === 0) {
        window.logger.warn(`No tab buttons found in tab group '${tabGroupId}'.`);
        return;
    }

    function activateTab(selectedButton) {
        tabButtons.forEach(btn => {
            const isSelected = btn === selectedButton;
            btn.setAttribute('aria-selected', isSelected.toString());
            if (isSelected) {
                btn.setAttribute('data-headlessui-state', 'selected');
                btn.classList.remove('text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'border-transparent');
                btn.classList.add('text-primary', 'border-primary');
            } else {
                btn.removeAttribute('data-headlessui-state');
                btn.classList.remove('text-primary', 'border-primary');
                btn.classList.add('text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'border-transparent');
            }

            const panelId = btn.getAttribute('data-tab-target');
            const panel = tabGroup.querySelector(panelId);
            if (panel) {
                if (isSelected) {
                    panel.classList.remove('hidden');
                } else {
                    panel.classList.add('hidden');
                }
            }
        });
    }

    tabButtons.forEach((button, index) => {
        button.addEventListener('click', () => {
            activateTab(button);
        });

        button.addEventListener('keydown', (event) => {
            let newIndex = index;
            let newButton = null;

            if (event.key === 'ArrowRight') {
                newIndex = (index + 1) % tabButtons.length;
                newButton = tabButtons[newIndex];
            } else if (event.key === 'ArrowLeft') {
                newIndex = (index - 1 + tabButtons.length) % tabButtons.length;
                newButton = tabButtons[newIndex];
            } else if (event.key === 'Home') {
                newIndex = 0;
                newButton = tabButtons[newIndex];
            } else if (event.key === 'End') {
                newIndex = tabButtons.length - 1;
                newButton = tabButtons[newIndex];
            } else {
                return;
            }

            event.preventDefault();
            if (newButton) {
                activateTab(newButton);
                newButton.focus();
            }
        });

        // Initial state setup
        const panelId = button.getAttribute('data-tab-target');
        const panel = tabGroup.querySelector(panelId);
        if (panel) {
            if (button.getAttribute('aria-selected') === 'true' && button.hasAttribute('data-headlessui-state')) {
                panel.classList.remove('hidden');
                button.classList.remove('text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'border-transparent');
                button.classList.add('text-primary', 'border-primary');
            } else {
                panel.classList.add('hidden');
                button.classList.remove('text-primary', 'border-primary');
                button.classList.add('text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300', 'border-transparent');
            }
        }
    });
}


document.addEventListener('DOMContentLoaded', function() {
    // Event delegation for user table actions
    const userTableBody = document.getElementById('usersTableBody');
    if (userTableBody) {
        userTableBody.addEventListener('click', function(event) {
            const deleteButton = event.target.closest('.delete-user-btn');
            if (deleteButton && !deleteButton.disabled) {
                const userId = deleteButton.dataset.userId;
                const username = deleteButton.dataset.username;
                if (typeof handleDeleteUser === 'function') {
                    handleDeleteUser(userId, username);
                } else {
                    window.logger.error("[AdminJS] handleDeleteUser function is not defined.");
                    alert("Error: Delete functionality is not available.");
                }
            }

            const editButton = event.target.closest('.edit-role-btn');
            if (editButton && !editButton.disabled) {
                handleRoleEditClick(editButton);
            }
        });
    }

    // Event listeners for inline role editing on the users table
    const usersTable = document.getElementById('usersTable');
    if (usersTable) {
        usersTable.addEventListener('change', handleRoleChange);
        usersTable.addEventListener('blur', handleRoleBlur, true);
        usersTable.addEventListener('keydown', handleRoleKeydown, true);
    }

    // Initialize tab groups if they exist on the page
    initializeTabs('transcriptionErrorTabGroup');
    initializeTabs('workflowErrorTabGroup');

});

// Desktop sidebar: collapsible to an icon rail, expanded by default, remembered per browser.
document.addEventListener('DOMContentLoaded', function() {
    const collapseButton = document.getElementById('admin-sidebar-collapse');
    if (!collapseButton) return;
    const root = document.documentElement;
    function syncCollapseButton() {
        const collapsed = root.classList.contains('admin-collapsed');
        collapseButton.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
        collapseButton.setAttribute('aria-label', label);
        collapseButton.setAttribute('title', label);
        const icon = collapseButton.querySelector('.material-icons');
        if (icon) icon.textContent = collapsed ? 'last_page' : 'first_page';
    }
    collapseButton.addEventListener('click', function() {
        const collapsed = root.classList.toggle('admin-collapsed');
        try { localStorage.setItem('compass-admin-sidebar', collapsed ? 'collapsed' : 'expanded'); } catch (e) { /* storage unavailable */ }
        syncCollapseButton();
    });
    syncCollapseButton();
});

document.addEventListener('DOMContentLoaded', function() {
    const adminSidenavButton = document.getElementById('admin-sidenav-button');
    const adminSidebar = document.getElementById('admin-sidebar');
    const adminSidenavOverlay = document.getElementById('admin-sidenav-overlay');
    const closeAdminSidebarButton = document.getElementById('close-admin-sidebar-button');
    let firstFocusableElementAdmin, lastFocusableElementAdmin;

    function getFocusableElementsAdmin() {
        if (!adminSidebar) return [];
        const focusable = Array.from(
            adminSidebar.querySelectorAll(
                'a[href]:not([disabled]), button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), details:not([disabled]), [tabindex]:not([tabindex="-1"])'
            )
        ).filter(el => !el.hasAttribute('disabled') && !el.closest('.hidden')); // Ensure elements are visible
        firstFocusableElementAdmin = focusable[0];
        lastFocusableElementAdmin = focusable[focusable.length - 1];
        return focusable;
    }

    function openAdminSidebar() {
        if (!adminSidebar || !adminSidenavOverlay || !adminSidenavButton) return;
        adminSidebar.classList.remove('-translate-x-full');
        adminSidebar.setAttribute('aria-hidden', 'false');
        adminSidenavButton.setAttribute('aria-expanded', 'true');
        adminSidenavOverlay.classList.remove('hidden', 'opacity-0');
        adminSidenavOverlay.classList.add('opacity-100');
        document.body.style.overflow = 'hidden';
        getFocusableElementsAdmin();
        if (firstFocusableElementAdmin) {
            firstFocusableElementAdmin.focus();
        } else {
            adminSidebar.focus();
        }
    }

    function closeAdminSidebar() {
        if (!adminSidebar || !adminSidenavOverlay || !adminSidenavButton) return;
        adminSidebar.classList.add('-translate-x-full');
        adminSidebar.setAttribute('aria-hidden', 'true');
        adminSidenavButton.setAttribute('aria-expanded', 'false');
        adminSidenavOverlay.classList.remove('opacity-100');
        adminSidenavOverlay.classList.add('opacity-0');
        setTimeout(() => {
            adminSidenavOverlay.classList.add('hidden');
        }, 300);
        document.body.style.overflow = '';
        adminSidenavButton.focus();
    }

    if (adminSidenavButton && adminSidebar && adminSidenavOverlay) {
        adminSidenavButton.addEventListener('click', function(event) {
            event.preventDefault();
            const isHidden = adminSidebar.classList.contains('-translate-x-full');
            if (isHidden) {
                openAdminSidebar();
            } else {
                closeAdminSidebar();
            }
        });

        if (closeAdminSidebarButton) {
            closeAdminSidebarButton.addEventListener('click', closeAdminSidebar);
        }
        adminSidenavOverlay.addEventListener('click', closeAdminSidebar);

        document.addEventListener('keydown', function(event) {
            const isMobileView = !adminSidenavOverlay.classList.contains('hidden');
            if (isMobileView && !adminSidebar.classList.contains('-translate-x-full')) {
                if (event.key === 'Escape') {
                    closeAdminSidebar();
                }
                if (event.key === 'Tab') {
                    if (!firstFocusableElementAdmin || !lastFocusableElementAdmin) {
                        getFocusableElementsAdmin();
                    }
                    if (event.shiftKey) {
                        if (document.activeElement === firstFocusableElementAdmin) {
                            lastFocusableElementAdmin.focus();
                            event.preventDefault();
                        }
                    } else {
                        if (document.activeElement === lastFocusableElementAdmin) {
                            firstFocusableElementAdmin.focus();
                            event.preventDefault();
                        }
                    }
                }
            }
        });
    }
});
