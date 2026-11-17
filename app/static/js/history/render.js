// app/static/js/history/render.js
// Rendering helpers for transcription history panels and workflow UI additions.

function formatApiLabel(apiUsed, apiModel) {
    const mapped = window.API_NAME_MAP_FRONTEND && window.API_NAME_MAP_FRONTEND[apiUsed];
    const base = String(mapped || apiUsed || 'Unknown API').trim();
    const model = String(apiModel || '').trim();
    if (!model) return base;
    // Compare without case, whitespace or a "provider:" prefix so a display
    // name that already is (or contains) the model slug isn't repeated.
    const normalize = (value) => value.replace(/^[a-z0-9_-]+:/i, '').replace(/\s+/g, '').toLowerCase();
    const normBase = normalize(base);
    const normModel = normalize(model);
    if (!normModel || normBase === normModel || normBase.includes(normModel)) {
        return mapped ? base : model;
    }
    return `${base} · ${model}`;
}

window.formatApiLabel = formatApiLabel;

(function initializeHistoryRender(window) {
    const History = window.History;
    const { historyLogger, historyLogPrefix } = History.logger;
    const idsToPollForTitle = History.state.idsToPollForTitle;
    const titlePollAttempts = History.state.titlePollAttempts;

    const { updateHistoryEmptyState } = History.ui;

/**
 * Adds a single transcription item to the history list UI.
 * Handles prepending, removing duplicates, and initializing UI elements.
 * NOTE: This function now ONLY renders the transcription panel. Workflow data is handled separately.
 * It also adds the transcription ID to the title polling list based on the shouldPollTitle flag.
 * @param {object} transcription - The transcription data object (transcription fields ONLY).
 * @param {boolean} canDownload - Whether the user can download transcripts.
 * @param {boolean} canRunWorkflow - Whether the user can run workflows.
 * @param {boolean} [prepend=false] - If true, adds the item to the top of the list.
 * @param {boolean} [shouldPollTitle=false] - If true, adds the item ID to the title polling list.
 * @param {boolean} [hadPendingWorkflow=false] - If true, indicates a workflow was pre-applied.
 */
function addTranscriptionToHistory(transcription, canDownload, canRunWorkflow, prepend = false, shouldPollTitle = false, hadPendingWorkflow = false) {
    if (!transcription || !transcription.id) {
        window.logger.error(historyLogPrefix, "Cannot add transcription to history: missing transcription data or ID.", transcription);
        return;
    }
    const logPrefix = `[HistoryJS:addTranscriptionToHistory:${transcription.id.substring(0, 8)}]`;
    window.logger.debug(logPrefix, "Attempting to add/update history item:", transcription, "Should Poll Title:", shouldPollTitle, "Had Pending WF:", hadPendingWorkflow);

    const historyList = document.getElementById('transcriptionHistory');
    if (!historyList) {
        window.logger.error(logPrefix, "History list element (#transcriptionHistory) not found.");
        return;
    }
    const placeholder = document.getElementById('history-placeholder');

    const existingItem = historyList.querySelector(`li[data-transcription-id="${transcription.id}"]`);
    if (existingItem) {
        window.logger.debug(logPrefix, "Removing existing history item before adding updated one.");
        existingItem.remove();
        idsToPollForTitle.delete(transcription.id); 
        delete titlePollAttempts[transcription.id]; 
    }

    const listItem = document.createElement('li');
    const isPinned = !!transcription.is_pinned;
    listItem.className = 'history-item' + (isPinned ? ' is-pinned' : '');
    listItem.dataset.transcriptionId = transcription.id;
    listItem.dataset.isPinned = isPinned ? 'true' : 'false';
    const hasFullTranscript = typeof transcription.transcription_text === 'string';
    const initialTranscriptText = hasFullTranscript
        ? transcription.transcription_text
        : (transcription.transcription_preview || '');
    listItem.dataset.fullText = initialTranscriptText;
    listItem.dataset.contentLoaded = hasFullTranscript ? 'true' : 'false';
    listItem.dataset.hasMore = transcription.transcription_has_more ? 'true' : 'false';
    listItem.dataset.transcriptionWarning = transcription.has_transcription_warning === true ? 'true' : 'false';
    listItem.dataset.initialPollTitle = shouldPollTitle ? 'true' : 'false';


    if (hadPendingWorkflow && transcription.pending_workflow_prompt_text) {
        listItem.dataset.pendingWorkflowPrompt = transcription.pending_workflow_prompt_text;
        listItem.dataset.pendingWorkflowTitle = transcription.pending_workflow_prompt_title || "Custom Workflow";
        listItem.dataset.pendingWorkflowColor = transcription.pending_workflow_prompt_color || "#ffffff";
        if (transcription.pending_workflow_origin_prompt_id) {
            listItem.dataset.workflowOriginPromptId = transcription.pending_workflow_origin_prompt_id;
        }
        window.logger.debug(logPrefix, "Stored pending workflow details on dataset:", listItem.dataset);
    }


    const apiName = formatApiLabel(transcription.api_used);
    const detectedLanguage = typeof transcription.detected_language === 'string'
        ? transcription.detected_language.trim()
        : '';
    const normalizedLanguage = detectedLanguage.toLowerCase();
    const shouldShowLanguage = detectedLanguage
        && normalizedLanguage !== 'unknown'
        && normalizedLanguage !== 'und';
    const langName = shouldShowLanguage
        ? (window.SUPPORTED_LANGUAGE_MAP?.[detectedLanguage] || capitalizeFirstLetter(detectedLanguage))
        : null;
    const durationMinutes = transcription.audio_length_minutes;
    const formattedDuration = (durationMinutes !== null && durationMinutes !== undefined) ? `${Math.ceil(durationMinutes)} min` : 'N/A';
    const formattedCreatedAt = typeof window.formatDateTime === 'function' ? window.formatDateTime(transcription.created_at) : transcription.created_at;
    const metaSegments = [apiName];
    if (langName) {
        metaSegments.push(langName);
    }
    metaSegments.push(formattedDuration, formattedCreatedAt);
    const metaText = metaSegments.map(segment => window.escapeHtml(segment)).join(' | ');

    const downloadButtonHtml = canDownload ? `
        <button type="button" class="download-btn icon-btn" title="Download Transcript">
            <i class="material-icons text-base">download</i>
        </button>
    ` : '';
    const pinButtonHtml = `
        <button type="button" class="pin-btn icon-btn${isPinned ? ' is-pinned' : ''}" title="${isPinned ? (window.i18n.unpin || 'Unpin') : (window.i18n.pinToTop || 'Pin to top')}">
            <i class="material-icons text-base">push_pin</i>
        </button>
    `;
    
    const historyItemContentClasses = ['history-item-content', 'flex', 'flex-col'];
    
    const transcriptPanelClasses = ['transcript-panel', 'w-full', 'relative', 'p-4'];
    const workflowPanelClasses = ['workflow-panel'];
    
    if (!hadPendingWorkflow) { 
        workflowPanelClasses.push('hidden');
    } else {
        historyItemContentClasses.push('has-active-workflow'); 
    }

    let startWorkflowButtonHtml = '';
    if (canRunWorkflow && !hadPendingWorkflow) {
        startWorkflowButtonHtml = `
            <div class="start-workflow-action text-right mt-1">
                <button type="button" class="start-workflow-btn ui-btn ui-btn--link ui-btn--sm">
                    <i class="material-icons text-base">auto_awesome</i>${window.i18n.startWorkflow || 'Start Workflow'}
                </button>
            </div>
        `;
    }
    
    const initialTitleText = (transcription.generated_title && transcription.title_generation_status === 'success')
                             ? transcription.generated_title
                             : (transcription.filename || 'Unknown Filename');
    const showInitialTitleIcon = transcription.generated_title && transcription.title_generation_status === 'success';
    const hasTranscriptionWarning = transcription.has_transcription_warning === true;
    const transcriptionWarningIconHtml = `<i class="material-icons tiny text-red-600 align-middle ml-1${hasTranscriptionWarning ? '' : ' hidden'}" id="title-warning-icon-${transcription.id}" title="Transcript may be incomplete" aria-label="Transcript may be incomplete">error_outline</i>`;


    listItem.innerHTML = `
        <div class="${historyItemContentClasses.join(' ')}">
            <div class="${transcriptPanelClasses.join(' ')}">
                <div class="flex justify-between items-start gap-4">
                    <div class="flex-grow min-w-0">
                        <div class="title-wrapper">
                            <b id="title-${transcription.id}" class="text-text-strong font-medium min-w-0 break-words leading-tight">
                                ${window.escapeHtml(initialTitleText)}<i class="material-icons tiny text-primary align-middle ml-1 ${showInitialTitleIcon ? '' : 'hidden'}" id="title-icon-${transcription.id}">auto_awesome</i>${transcriptionWarningIconHtml}
                            </b>
                        </div>
                        <p class="meta history-meta">
                            ${metaText}
                            ${transcription.status === 'error' ? '<span class="text-red-600"> (Failed)</span>' : ''}
                        </p>
                    </div>
                    <div class="secondary-content history-item-actions flex-shrink-0 flex gap-0.5">
                        <button type="button" class="copy-btn icon-btn" title="Copy Transcript">
                            <i class="material-icons text-base">content_copy</i>
                        </button>
                        ${downloadButtonHtml}
                        ${pinButtonHtml}
                        <button type="button" class="delete-btn icon-btn icon-btn--danger" title="Delete Transcript">
                            <i class="material-icons text-base">delete</i>
                        </button>
                    </div>
                </div>
                <p class="transcription-text text-sm text-text-muted leading-relaxed mt-2 mb-1"></p>
                ${startWorkflowButtonHtml}
            </div>
            <div class="${workflowPanelClasses.join(' ')}"
                 ${transcription.llm_operation_id ? `data-operation-id="${transcription.llm_operation_id}"` : ''}>
                ${hadPendingWorkflow ? `
                    <div class="flex flex-col items-center justify-center text-text-muted min-h-[100px]">
                      <span class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-primary mb-2"></span>
                      <span>Loading Workflow...</span>
                   </div>` : ''}
            </div>
        </div>
    `;

    const transcriptElement = listItem.querySelector('.transcription-text');
    if (transcriptElement) {
        const fullText = initialTranscriptText;
        const words = fullText.split(/\s+/).filter(Boolean);
        const previewLength = 140;
        if (words.length > previewLength || transcription.transcription_has_more) {
            const truncatedText = words.slice(0, previewLength).join(' ') + '...';
            transcriptElement.textContent = truncatedText;
            transcriptElement.dataset.readMoreState = 'truncated'; 
            let readMoreLink = document.createElement('a');
            readMoreLink.href = '#!';
            readMoreLink.className = 'read-more text-primary hover:text-primary-dark text-sm';
            readMoreLink.style.fontSize = '0.9em'; 
            readMoreLink.style.marginLeft = '0px'; 
            readMoreLink.textContent = window.i18n.readMore || ' Read More';
            transcriptElement.parentNode.insertBefore(readMoreLink, transcriptElement.nextSibling);
        } else {
            transcriptElement.textContent = fullText;
            transcriptElement.dataset.readMoreState = 'full'; 
        }
    }

    if (placeholder) {
        placeholder.style.display = 'none';
    }

    if (prepend) {
        historyList.prepend(listItem); 
        window.logger.debug(logPrefix, "Prepended new history item to the list.");
    } else {
        historyList.appendChild(listItem);
        window.logger.debug(logPrefix, "Appended new history item to the list.");
    }

    if (shouldPollTitle) {
        idsToPollForTitle.add(transcription.id);
        titlePollAttempts[transcription.id] = 0;
        window.logger.debug(logPrefix, `Added ${transcription.id} to title polling list.`);
        if (typeof window.startTitlePolling === 'function') {
            window.startTitlePolling();
        } else {
            window.logger.error(logPrefix, "startTitlePolling function is missing.");
        }
    } else if (prepend && transcription.status === 'finished' && !showInitialTitleIcon) {
        window.logger.debug(logPrefix, `Newly finished job ${transcription.id}, not polling. Making one-time call to fetchTitleStatus.`);
        const pollingModule = window.History.polling;
        if (pollingModule && typeof pollingModule.fetchTitleStatus === 'function') {
            pollingModule.fetchTitleStatus(transcription.id);
        } else {
            window.logger.error(logPrefix, "fetchTitleStatus function is missing.");
        }
    } else {
        window.logger.debug(logPrefix, `Skipping title polling for ${transcription.id} (shouldPollTitle=${shouldPollTitle}, prepend=${prepend}, status=${transcription.status}, showInitialIcon=${showInitialTitleIcon}).`);
    }


    if (hadPendingWorkflow) {
        window.logger.debug(logPrefix, `Pre-applied workflow detected for ${transcription.id}. Initiating workflow status polling.`);
        if (typeof window.Workflow !== 'undefined' && typeof window.Workflow.startWorkflowPollingForTranscription === 'function') {
            Workflow.startWorkflowPollingForTranscription(transcription.id);
        } else {
            window.logger.error(logPrefix, "Workflow.startWorkflowPollingForTranscription function is missing.");
            const workflowPanel = listItem.querySelector(".workflow-panel");
            if (workflowPanel) workflowPanel.innerHTML = '<p class="text-danger text-center">Error: Could not start workflow polling.</p>';
        }
    }
}
window.addTranscriptionToHistory = addTranscriptionToHistory;

function addReadMoreToWorkflowHTML(resultElement) {
    if (!resultElement) return;
    const originalMarkdown = resultElement.dataset.fullText;
    if (!originalMarkdown) return;
    const previewLengthChars = 500;
    if (originalMarkdown.length > previewLengthChars) {
        let breakPoint = originalMarkdown.lastIndexOf(' ', previewLengthChars);
        if (breakPoint === -1 || breakPoint < previewLengthChars / 2) breakPoint = previewLengthChars;
        const truncatedMarkdown = originalMarkdown.substring(0, breakPoint) + '...';
        let fullHtml = '', truncatedHtml = '';
        if (typeof window.renderMarkdownSafe === "function") {
            fullHtml = window.renderMarkdownSafe(originalMarkdown);
            truncatedHtml = window.renderMarkdownSafe(truncatedMarkdown);
        } else { fullHtml = `<pre>${window.escapeHtml(originalMarkdown)}</pre>`; truncatedHtml = `<pre>${window.escapeHtml(truncatedMarkdown)}</pre>`; }
        resultElement.innerHTML = truncatedHtml;
        resultElement.dataset.readMoreState = 'truncated';
        let readMoreLink = resultElement.nextElementSibling;
        if (!readMoreLink || !readMoreLink.classList.contains('read-more-workflow')) {
            readMoreLink = document.createElement('a'); readMoreLink.href = '#!';
            readMoreLink.className = 'read-more-workflow text-primary hover:text-primary-dark text-sm block mt-1.5';
            readMoreLink.style.fontSize = '0.9em'; 
            readMoreLink.style.marginLeft = '0px';
            readMoreLink.style.display = 'block';
            readMoreLink.style.marginTop = '5px';
            resultElement.parentNode.insertBefore(readMoreLink, resultElement.nextSibling);
        }
        readMoreLink.textContent = window.i18n.readMore || ' Read More'; readMoreLink.dataset.fullHtml = fullHtml; readMoreLink.dataset.truncatedHtml = truncatedHtml;
    } else {
        let fullHtml = '';
         if (typeof window.renderMarkdownSafe === 'function') {
            fullHtml = window.renderMarkdownSafe(originalMarkdown);
        } else { fullHtml = `<pre>${window.escapeHtml(originalMarkdown)}</pre>`; }
        resultElement.innerHTML = fullHtml; resultElement.dataset.readMoreState = 'full';
        let existingLink = resultElement.nextElementSibling;
        if (existingLink && existingLink.classList.contains('read-more-workflow')) existingLink.remove();
    }
}
window.addReadMoreToWorkflowHTML = addReadMoreToWorkflowHTML;

function togglePrompt(ellipsisElement) {
    const container = ellipsisElement.closest('.truncated-prompt'); if (!container) return;
    const truncatedPart = container.querySelector('em'); const ellipsis = container.querySelector('.ellipsis'); const fullPromptPart = container.querySelector('.full-prompt');
    if (fullPromptPart.style.display === 'none') { truncatedPart.style.display = 'none'; ellipsis.style.display = 'none'; fullPromptPart.style.display = 'inline'; }
    else { truncatedPart.style.display = 'inline'; ellipsis.style.display = 'inline'; fullPromptPart.style.display = 'none'; }
}
window.togglePrompt = togglePrompt;

function capitalizeFirstLetter(string) { if (!string || typeof string !== 'string') return string || ''; return string.charAt(0).toUpperCase() + string.slice(1); }
window.capitalizeFirstLetter = capitalizeFirstLetter; 


/**
 * Fetches the title status for a single transcription ID.
 * @param {string} transcriptionId
 */

    History.render = { addTranscriptionToHistory, addReadMoreToWorkflowHTML, togglePrompt, capitalizeFirstLetter };
})(window);
