// app/static/js/history/actions.js
// Undo handling, downloads, and destructive history actions.

(function initializeHistoryActions(window) {
    const History = window.History;
    const { historyLogPrefix } = History.logger;
    const idsToPollForTitle = History.state.idsToPollForTitle;
    const titlePollAttempts = History.state.titlePollAttempts;
    const deletedTranscriptionUndoData = History.state.deletedTranscriptionUndoData;
    const { UNDO_NOTIFICATION_DURATION_MS } = History.constants;
    const { updateHistoryEmptyState, animateHistoryItemRemoval } = History.ui;

function handleUndoRestore(transcriptionId, undoData, notification, undoButton, logPrefix) {
    if (!undoData || !undoData.undoActive || undoData.undoInFlight) {
        window.logger.debug(logPrefix, "Undo not available or already in progress.");
        return;
    }

    undoData.undoInFlight = true;
    if (undoButton) {
        undoButton.disabled = true;
        undoButton.classList.add('pointer-events-none', 'opacity-60', 'cursor-not-allowed');
        undoButton.textContent = window.i18n?.restoring || 'Restoring...';
    }

    fetch(`/api/transcriptions/${transcriptionId}/restore`, { method: 'POST', headers: { 'X-CSRFToken': window.csrfToken } })
    .then(response => {
        if (!response.ok) {
            return response.json()
                .catch(() => ({ error: `HTTP error! Status: ${response.status}` }))
                .then(errData => { throw new Error(errData.error || `HTTP error! Status: ${response.status}`); });
        }
        return response.json();
    })
    .then(data => {
        const historyList = undoData.parent || document.getElementById('transcriptionHistory');
        if (!historyList) {
            window.logger.error(logPrefix, "History list element missing during undo restore.");
        } else if (undoData.clone) {
            const placeholder = document.getElementById('history-placeholder');
            if (placeholder) { placeholder.remove(); }

            let anchor = null;
            if (undoData.nextSiblingId) {
                anchor = historyList.querySelector(`li[data-transcription-id="${undoData.nextSiblingId}"]`);
            }

            if (anchor) {
                historyList.insertBefore(undoData.clone, anchor);
            } else {
                historyList.appendChild(undoData.clone);
            }

            requestAnimationFrame(() => {
                undoData.clone.style.opacity = '0';
                undoData.clone.style.transform = 'translateY(8px)';
                undoData.clone.style.transition = 'opacity 250ms ease, transform 250ms ease';
                requestAnimationFrame(() => {
                    undoData.clone.style.opacity = '1';
                    undoData.clone.style.transform = 'translateY(0)';
                });
            });
        }

        updateHistoryEmptyState();

        if (undoData.shouldRestoreTitlePolling) {
            idsToPollForTitle.add(transcriptionId);
            if (typeof titlePollAttempts[transcriptionId] === 'undefined') {
                titlePollAttempts[transcriptionId] = 0;
            }
            if (typeof window.startTitlePolling === 'function') {
                window.startTitlePolling();
            } else {
                window.logger.error(logPrefix, "startTitlePolling function is missing.");
            }
        }

        undoData.undoActive = false;
        if (undoData.expiryTimer) { clearTimeout(undoData.expiryTimer); }
        deletedTranscriptionUndoData.delete(transcriptionId);

        if (notification) {
            const messageEl = notification.querySelector('.alert-content p');
            if (messageEl) {
                messageEl.textContent = data.message || 'Transcription restored.';
            }
            const undoAction = notification.querySelector('.undo-delete-action');
            if (undoAction) { undoAction.remove(); }
        }

        window.logger.info(logPrefix, "Undo restore completed.");
    })
    .catch(error => {
        undoData.undoInFlight = false;
        if (undoButton) {
            undoButton.disabled = false;
            undoButton.classList.remove('pointer-events-none', 'opacity-60', 'cursor-not-allowed');
            undoButton.textContent = window.i18n?.undo || 'Undo';
        }
        window.logger.error(logPrefix, 'Error restoring transcription during undo:', error);
        window.showNotification(`Error restoring transcription: ${error?.message || 'Unknown error'}`, 'error', 5000, false);
    });
}

function logDownload(transcriptionId) {
    const logPrefix = `[HistoryJS:logDownload:${transcriptionId}]`; window.logger.debug(logPrefix, "Logging download...");
    fetch(`/api/transcriptions/${transcriptionId}/log_download`, { method: 'POST', headers: { 'X-CSRFToken': window.csrfToken, 'Accept': 'application/json' } })
    .then(response => { if (!response.ok) { response.json().then(errData => { window.logger.error(logPrefix, `Failed to log download (${response.status}):`, errData.error || 'Unknown error'); }).catch(() => { window.logger.error(logPrefix, `Failed to log download (${response.status}) and couldn't parse error response.`); }); } else { window.logger.debug(logPrefix, "Download logged successfully."); } })
    .catch(error => { window.logger.error(logPrefix, "Network error logging download:", error); });
}
window.logDownload = logDownload;

function downloadTranscription(transcriptionId, text, baseFilename) {
  if (!text) { 
    window.showNotification('Nothing to download!', 'warning', 3000, false);
    return; 
  }
  const filename = `${baseFilename || 'transcription'}.txt`; const element = document.createElement('a');
  const fileContent = text || ""; const blob = new Blob([fileContent], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob); element.setAttribute('href', url); element.setAttribute('download', filename);
  element.style.display = 'none'; document.body.appendChild(element); element.click(); document.body.removeChild(element); URL.revokeObjectURL(url);
  window.logger.debug(historyLogPrefix, `Download triggered for ${filename}`); window.logDownload(transcriptionId);
}
window.downloadTranscription = downloadTranscription;

function handleClearAll() {
    if (confirm('Are you sure you want to clear your entire transcription history?\nThis action cannot be undone.')) {
        window.logger.info(historyLogPrefix, "Clear All confirmed. Sending request...");
        fetch('/api/transcriptions/clear', { method: 'DELETE', headers: { 'X-CSRFToken': window.csrfToken } })
        .then(response => { if (!response.ok) { return response.json().catch(() => ({ error: `HTTP error! Status: ${response.status}` })).then(errData => { throw new Error(errData.error || `HTTP error! Status: ${response.status}`); }); } return response.json(); })
        .then(data => {
            window.showNotification(data.message || 'History cleared successfully.', 'success', 4000, false);
            window.logger.info(historyLogPrefix, "History cleared successfully via API.");
            const historyList = document.getElementById('transcriptionHistory'); const clearAllBtn = document.getElementById('clearAllBtn');
            if (historyList) { historyList.innerHTML = '<li class="py-4 text-center text-gray-500" id="history-placeholder">No transcriptions found.</li>'; } 
            if (clearAllBtn) clearAllBtn.style.display = 'none';
            const paginationContainer = document.querySelector('.pagination-container'); if (paginationContainer) paginationContainer.remove();
        })
        .catch(error => { 
            window.logger.error(historyLogPrefix, 'Error clearing transcriptions:', error); 
            window.showNotification(`Error clearing history: ${error.message}`, 'error', 5000, false);
        });
    } else { window.logger.debug(historyLogPrefix, "Clear All cancelled by user."); }
}
window.handleClearAll = handleClearAll;

function deleteTranscription(transcriptionId, transcriptionItemElement) {
    const logPrefix = `[HistoryJS:deleteTranscription:${transcriptionId}]`;
    window.logger.debug(logPrefix, "Delete requested.");

    if (!transcriptionItemElement) {
        window.logger.error(logPrefix, "No list item element provided for deletion.");
        return;
    }

    const historyList = transcriptionItemElement.parentElement;
    const nextSibling = transcriptionItemElement.nextElementSibling;
    const nextSiblingId = nextSibling && nextSibling.dataset ? nextSibling.dataset.transcriptionId || null : null;
    const shouldRestoreTitlePolling = transcriptionItemElement.dataset.pollTitle === 'true' || transcriptionItemElement.dataset.initialPollTitle === 'true';

    const listItemClone = transcriptionItemElement.cloneNode(true);
    if (listItemClone) {
        listItemClone.removeAttribute('style');
    }

    const deleteButton = transcriptionItemElement.querySelector('.delete-btn');
    let originalDeleteIcon = null;
    if (deleteButton) {
        deleteButton.disabled = true;
        deleteButton.setAttribute('aria-disabled', 'true');
        deleteButton.classList.add('opacity-60', 'pointer-events-none', 'cursor-not-allowed');
        originalDeleteIcon = deleteButton.querySelector('.material-icons');
        if (originalDeleteIcon) {
            originalDeleteIcon.dataset.originalIcon = originalDeleteIcon.textContent;
            originalDeleteIcon.textContent = 'hourglass_top';
            originalDeleteIcon.classList.add('animate-spin');
        }
    }

    fetch(`/api/transcriptions/${transcriptionId}`, { method: 'DELETE', headers: { 'X-CSRFToken': window.csrfToken } })
    .then(response => {
        if (!response.ok) {
            return response.json()
                .catch(() => ({ error: `HTTP error! Status: ${response.status}` }))
                .then(errData => { throw new Error(errData.error || `HTTP error! Status: ${response.status}`); });
        }
        return response.json();
    })
    .then(data => {
        window.logger.info(logPrefix, "Deletion successful via API.");
        idsToPollForTitle.delete(transcriptionId);
        delete titlePollAttempts[transcriptionId];

        const undoData = {
            clone: listItemClone,
            parent: historyList,
            nextSiblingId,
            shouldRestoreTitlePolling,
            undoActive: true,
            undoInFlight: false,
            notification: null,
            expiryTimer: null
        };

        deletedTranscriptionUndoData.set(transcriptionId, undoData);

        animateHistoryItemRemoval(transcriptionItemElement, () => {
            transcriptionItemElement.remove();
            updateHistoryEmptyState();
        });

        let undoButton = null;
        const notification = window.showNotificationWithAction(
            data.message || 'Transcription deleted.',
            {
                label: window.i18n?.undo || 'Undo',
                className: 'undo-delete-action',
                onClick: event => {
                    event.preventDefault();
                    handleUndoRestore(transcriptionId, undoData, notification, undoButton, logPrefix);
                },
            },
            'success',
            UNDO_NOTIFICATION_DURATION_MS,
            false,
        );
        undoData.notification = notification;

        if (notification) {
            undoButton = notification.querySelector('.undo-delete-action');
            if (undoButton) {
                undoData.expiryTimer = setTimeout(() => {
                    if (undoButton) {
                        undoButton.disabled = true;
                        undoButton.classList.add('pointer-events-none', 'opacity-60', 'cursor-not-allowed');
                    }
                    undoData.undoActive = false;
                    deletedTranscriptionUndoData.delete(transcriptionId);
                }, UNDO_NOTIFICATION_DURATION_MS + 400);
            } else {
                undoData.undoActive = false;
                deletedTranscriptionUndoData.delete(transcriptionId);
            }
        } else {
            undoData.undoActive = false;
            deletedTranscriptionUndoData.delete(transcriptionId);
            window.logger.warn(logPrefix, "Notification container missing; undo not available.");
        }
    })
    .catch(error => {
        window.logger.error(historyLogPrefix, 'Error deleting transcription:', error);
        window.showNotification(`Error deleting: ${error?.message || 'Unknown error'}`, 'error', 5000, false);
        if (deleteButton) {
            deleteButton.disabled = false;
            deleteButton.removeAttribute('aria-disabled');
            deleteButton.classList.remove('opacity-60', 'pointer-events-none', 'cursor-not-allowed');
            if (originalDeleteIcon && originalDeleteIcon.dataset.originalIcon) {
                originalDeleteIcon.textContent = originalDeleteIcon.dataset.originalIcon;
                delete originalDeleteIcon.dataset.originalIcon;
            }
            if (originalDeleteIcon) {
                originalDeleteIcon.classList.remove('animate-spin');
            }
        }
    });
}
window.deleteTranscription = deleteTranscription;

function togglePin(transcriptionId, transcriptionItemElement) {
    const logPrefix = `[HistoryJS:togglePin:${transcriptionId ? transcriptionId.substring(0, 8) : 'unknown'}]`;
    window.logger.debug(logPrefix, "Pin toggle requested.");

    const pinButton = transcriptionItemElement?.querySelector('.pin-btn');
    if (pinButton) {
        pinButton.disabled = true;
        pinButton.classList.add('opacity-60', 'pointer-events-none', 'cursor-not-allowed');
    }

    fetch(`/api/transcriptions/${transcriptionId}/toggle_pin`, {
        method: 'POST',
        headers: { 'X-CSRFToken': window.csrfToken }
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
        window.logger.info(logPrefix, `Pin toggled. New state: ${data.is_pinned}`);
        window.location.reload();
    })
    .catch(error => {
        window.logger.error(logPrefix, 'Error toggling pin:', error);
        if (pinButton) {
            pinButton.disabled = false;
            pinButton.classList.remove('opacity-60', 'pointer-events-none', 'cursor-not-allowed');
        }
        window.showNotification(
            `Error: ${error?.message || 'Unknown error'}`,
            'error', 5000, false
        );
    });
}
window.togglePin = togglePin;

    History.actions = { handleUndoRestore, logDownload, downloadTranscription, handleClearAll, deleteTranscription, togglePin };
})(window);
