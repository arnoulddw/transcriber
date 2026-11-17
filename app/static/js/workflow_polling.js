// app/static/js/workflow_polling.js
// Handles polling for workflow status and UI updates.

const workflowPollingLogPrefix = "[WorkflowJS:Polling]"; // Changed log prefix

// Polling State
let workflowPollIntervalId = null;
let currentPollingOperationId = null;
let currentPollingTranscriptionId = null;
const WORKFLOW_POLL_INTERVAL_MS = 2500;

// Meta Polling State (for pre-applied workflows)
let metaPollIntervalId = null;
let currentMetaPollingTranscriptionId = null;
const META_POLL_INTERVAL_MS = 2000;
const MAX_META_POLL_ATTEMPTS = 15;
let metaPollAttempts = 0;

window.Workflow = window.Workflow || {};

// Utility function (qs) might be needed if not globally available from workflow_modal.js
// For now, assume qs is globally available or defined in workflow_modal.js
// If not, it should be defined here or passed around.
// function qs(id) { return document.getElementById(id); }


function _startWorkflowPolling(transcriptionId, operationId) {
  const pollLog = `${workflowPollingLogPrefix}:Op${operationId}`;
  window.logger.info(pollLog, `Starting polling for transcription ${transcriptionId}`);
  _stopWorkflowPolling(); // Call local version
  currentPollingOperationId = operationId;
  currentPollingTranscriptionId = transcriptionId;
  _pollWorkflowStatus(); // Call local version
  workflowPollIntervalId = setInterval(_pollWorkflowStatus, WORKFLOW_POLL_INTERVAL_MS);
}
window.Workflow.startWorkflowPolling = _startWorkflowPolling;


async function _pollWorkflowStatus() {
  if (!currentPollingOperationId || !currentPollingTranscriptionId) {
    window.logger.warn(workflowPollingLogPrefix, "Polling attempted without operation/transcription ID. Stopping poll.");
    _stopWorkflowPolling(); // Call local version
    return;
  }
  const opId = currentPollingOperationId,
    transcriptionId = currentPollingTranscriptionId,
    pollLog = `${workflowPollingLogPrefix}:Op${opId}`;
  window.logger.debug(pollLog, "Polling status...");
  try {
    const response = await fetch(`/api/llm/operations/${opId}/status`, {
      method: "GET",
      headers: { Accept: "application/json", "X-CSRFToken": window.csrfToken }
    });
    if (!response.ok) {
      const errorStatus = response.status;
      window.logger.warn(pollLog, `Polling failed (${errorStatus}). Stopping poll.`);
      _stopWorkflowPolling(); // Call local version
      _updateWorkflowPanel(transcriptionId, { status: "error", error: `Workflow status check failed (${errorStatus}).`, operation_id: opId }); // Call local version
      return;
    }
    const data = await response.json();
    window.logger.debug(pollLog, "Received status:", data.status);
    _updateWorkflowPanel(transcriptionId, data); // Call local version
    if (data.status === "finished" || data.status === "error") {
      window.logger.info(pollLog, `Polling stopped. Final status: ${data.status}`);
      _stopWorkflowPolling(); // Call local version
    }
  } catch (error) {
    window.logger.error(pollLog, "Error during polling request:", error);
    // Optionally, implement retry logic or stop polling on persistent errors
  }
}
window.Workflow.pollWorkflowStatus = _pollWorkflowStatus; // Expose if needed for manual calls, though unlikely

function _stopWorkflowPolling() {
    if (workflowPollIntervalId) {
        clearInterval(workflowPollIntervalId);
        workflowPollIntervalId = null;
        window.logger.debug(workflowPollingLogPrefix, `Main polling stopped for OpID: ${currentPollingOperationId}`);
    }
    currentPollingOperationId = null;
    currentPollingTranscriptionId = null;
    _stopMetaPolling(); // Call local version
}
window.Workflow.stopWorkflowPolling = _stopWorkflowPolling;

function _updateWorkflowPanel(transcriptionId, operationData) {
  const opIdForLog = operationData.operation_id || currentPollingOperationId || "UnknownOp";
  const updateLog = `[WorkflowJS:Polling:UpdatePanel:Op${opIdForLog}:Tr${transcriptionId.substring(0,8)}]`; // Adjusted log prefix
  const historyItem = document.querySelector(`li[data-transcription-id="${transcriptionId}"]`);

  if (!historyItem) {
    window.logger.error(updateLog, `Could not find history item for transcription ID ${transcriptionId}`);
    return;
  }
  const workflowPanel = historyItem.querySelector(".workflow-panel"),
    startButtonActionDiv = historyItem.querySelector(".start-workflow-action"),
    contentContainer = historyItem.querySelector(".history-item-content");

  if (!workflowPanel) {
    window.logger.error(updateLog, `Could not find workflow panel within history item ${transcriptionId}`);
    return;
  }
  workflowPanel.innerHTML = ""; // Clear previous content
  // Reset classes to base state, then add specifics
  workflowPanel.className = "workflow-panel";


  const opId = operationData.operation_id;
  if (opId) {
    workflowPanel.dataset.operationId = opId;
  } else {
    delete workflowPanel.dataset.operationId;
    window.logger.warn(updateLog, "Operation ID missing in operationData. Panel actions might not work correctly.");
  }

  const status = operationData.status;
  if (status === "pending" || status === "processing") {
    workflowPanel.classList.remove('pb-11'); 
    workflowPanel.classList.add("flex", "items-center", "justify-center", "min-h-[150px]");
    // MODIFICATION: Added justify-center and h-full to the inner div
    workflowPanel.innerHTML = `
          <div class="flex flex-col items-center justify-center h-full text-text-muted">
            <span class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-primary mb-2"></span>
            <span>Processing Workflow...</span>
          </div>`;
    workflowPanel.style.display = "block"; 
    if (contentContainer) contentContainer.classList.add("has-active-workflow");
  } else if (status === "finished") {
    workflowPanel.classList.remove("flex", "items-center", "justify-center", "min-h-[150px]");
    // Finished: base lilac panel styling applies

    const resultText = operationData.result || "[Empty Result]";
    const ranAt = operationData.completed_at || operationData.llm_operation_ran_at; 
    let displayPromptText = operationData.input_text;
    let displayPromptTitle = null;
    let displayPromptColor = "#ffffff"; 

    const originPromptId = historyItem.dataset.workflowOriginPromptId;
    if (originPromptId) {
        const promptSelectElem = document.getElementById("workflowPromptSelect"); 
        if (promptSelectElem) {
            const matchingOption = Array.from(promptSelectElem.options).find(opt => opt.dataset.promptId === originPromptId);
            if (matchingOption) {
                displayPromptTitle = matchingOption.textContent;
                displayPromptColor = matchingOption.dataset.promptColor || "#ffffff";
            }
        }
    }
    if (!displayPromptTitle && historyItem) {
        if (!displayPromptText && historyItem.dataset.pendingWorkflowPrompt) displayPromptText = historyItem.dataset.pendingWorkflowPrompt;
        if (historyItem.dataset.pendingWorkflowTitle) displayPromptTitle = historyItem.dataset.pendingWorkflowTitle;
        if (historyItem.dataset.pendingWorkflowColor) displayPromptColor = historyItem.dataset.pendingWorkflowColor;
        if (historyItem.dataset.workflowPrompt && !displayPromptText) displayPromptText = historyItem.dataset.workflowPrompt;
        if (historyItem.dataset.workflowLabel && !displayPromptTitle) displayPromptTitle = historyItem.dataset.workflowLabel;
        if (historyItem.dataset.workflowPromptColor && displayPromptColor === "#ffffff") displayPromptColor = historyItem.dataset.workflowPromptColor;
    }
    displayPromptText = displayPromptText || "[Prompt not available]";

    const canDownload = window.USER_PERMISSIONS?.allow_download_transcript ?? true;
    const downloadButtonHtml = canDownload
        ? `<button class="download-workflow-btn icon-btn" title="Download result"><i class="material-icons text-base">download</i></button>`
        : "";
    let resultHtml = "";
    if (typeof window.renderMarkdownSafe === "function") {
      resultHtml = window.renderMarkdownSafe(resultText);
    } else {
      resultHtml = `<pre class="whitespace-pre-wrap break-words">${window.escapeHtml(resultText)}</pre>`;
    }
    workflowPanel.innerHTML = `
          <div class="flex justify-between items-start gap-4 mb-0">
              <div class="panel-title">
                <i class="material-icons text-lg">auto_awesome</i>${window.i18n.workflowResult || 'Workflow result'}
              </div>
              <div class="workflow-actions flex-shrink-0 flex gap-0.5">
                <button class="edit-workflow-btn icon-btn" title="Edit result"><i class="material-icons text-base">edit</i></button>
                <button class="copy-workflow-btn icon-btn" title="Copy result"><i class="material-icons text-base">content_copy</i></button>
                ${downloadButtonHtml}
                <button class="delete-workflow-btn icon-btn icon-btn--danger" title="Delete result"><i class="material-icons text-base">delete</i></button>
              </div>
          </div>
          <div class="workflow-meta mt-1 mb-2 text-xs text-text-muted leading-snug">
            Ran: ${window.formatDateTime(ranAt).replace(",", "") || "-"} |
            ${
              displayPromptTitle
                ? `Workflow Label: <span class="prompt-label-pill inline-block px-2 py-0.5 rounded-full text-xs font-medium ml-1 align-middle overflow-hidden text-ellipsis whitespace-nowrap max-w-[60%]" data-background-color="${window.escapeHtml(displayPromptColor)}">${window.escapeHtml(displayPromptTitle)}</span>`
                : `Prompt: <span class="custom-prompt-preview italic">${window.escapeHtml(displayPromptText.substring(0, 80))}...</span>`
            }
          </div>
          <div class="workflow-result-text text-sm text-text-strong leading-relaxed break-words" data-full-text="${window.escapeHtml(resultText)}">
            ${resultHtml}
          </div>`;
    workflowPanel.style.display = "block";
    if (contentContainer) contentContainer.classList.add("has-active-workflow");

    if (typeof window.applyPillStyles === "function") {
      window.applyPillStyles(".prompt-label-pill", workflowPanel);
    }
    if (typeof window.addReadMoreToWorkflowHTML === "function") {
      window.addReadMoreToWorkflowHTML(workflowPanel.querySelector(".workflow-result-text"));
    }
  } else if (status === "error") {
    workflowPanel.classList.remove("flex", "items-center", "justify-center", "min-h-[150px]");
    workflowPanel.classList.add("is-error");

    const ranAt = operationData.completed_at || operationData.llm_operation_ran_at || operationData.created_at;
    let displayPromptText = operationData.input_text;
    let displayPromptTitle = null;
    let displayPromptColor = "#ffffff";

    const originPromptId = historyItem.dataset.workflowOriginPromptId;
     if (originPromptId) {
        const promptSelectElem = document.getElementById("workflowPromptSelect");
        if (promptSelectElem) {
            const matchingOption = Array.from(promptSelectElem.options).find(opt => opt.dataset.promptId === originPromptId);
            if (matchingOption) {
                displayPromptTitle = matchingOption.textContent;
                displayPromptColor = matchingOption.dataset.promptColor || "#ffffff";
            }
        }
    }
     if (!displayPromptTitle && historyItem) {
        if (!displayPromptText && historyItem.dataset.pendingWorkflowPrompt) displayPromptText = historyItem.dataset.pendingWorkflowPrompt;
        if (historyItem.dataset.pendingWorkflowTitle) displayPromptTitle = historyItem.dataset.pendingWorkflowTitle;
        if (historyItem.dataset.pendingWorkflowColor) displayPromptColor = historyItem.dataset.pendingWorkflowColor;
        if (historyItem.dataset.workflowPrompt && !displayPromptText) displayPromptText = historyItem.dataset.workflowPrompt;
        if (historyItem.dataset.workflowLabel && !displayPromptTitle) displayPromptTitle = historyItem.dataset.workflowLabel;
        if (historyItem.dataset.workflowPromptColor && displayPromptColor === "#ffffff") displayPromptColor = historyItem.dataset.workflowPromptColor;
    }
    displayPromptText = displayPromptText || "[Prompt not available]";
    const errorMsg = operationData.error || operationData.llm_operation_error || "An unknown workflow error occurred.";

    workflowPanel.innerHTML = `
          <div class="flex justify-between items-start gap-4 mb-0">
              <div class="panel-title">
                <i class="material-icons text-lg">error_outline</i>${window.i18n.workflowError || 'Workflow Error'}
              </div>
              <div class="workflow-actions flex-shrink-0 flex gap-0.5">
                <button class="delete-workflow-btn icon-btn icon-btn--danger" title="Delete result"><i class="material-icons text-base">delete</i></button>
              </div>
          </div>
          <div class="workflow-meta mt-1 mb-2 text-xs text-text-muted leading-snug">
            Attempted: ${window.formatDateTime(ranAt).replace(",", "") || "-"} |
            ${
              displayPromptTitle
                ? `Workflow Label: <span class="prompt-label-pill inline-block px-2 py-0.5 rounded-full text-xs font-medium ml-1 align-middle overflow-hidden text-ellipsis whitespace-nowrap max-w-[60%]" data-background-color="${window.escapeHtml(displayPromptColor)}">${window.escapeHtml(displayPromptTitle)}</span>`
                : `Prompt: <span class="custom-prompt-preview italic">${window.escapeHtml(displayPromptText.substring(0, 80))}...</span>`
            }
          </div>
          <div class="workflow-result-text text-sm text-danger leading-relaxed whitespace-pre-wrap break-words">${window.escapeHtml(errorMsg)}</div>`;
    workflowPanel.style.display = "block";
    if (contentContainer) contentContainer.classList.add("has-active-workflow");

    if (typeof window.applyPillStyles === "function") {
      window.applyPillStyles(".prompt-label-pill", workflowPanel);
    }
  } else { 
    workflowPanel.innerHTML = ""; 
    workflowPanel.style.display = "none"; 
    workflowPanel.className = "workflow-panel hidden"; 
    if (startButtonActionDiv) startButtonActionDiv.style.display = "block"; 
    if (contentContainer) contentContainer.classList.remove("has-active-workflow");
  }
}
window.Workflow.updateWorkflowPanel = _updateWorkflowPanel;


function _startWorkflowPollingForTranscription(transcriptionId) {
    const metaPollLog = `[WorkflowJS:Polling:MetaPoll:Tr${transcriptionId.substring(0,8)}]`; 
    window.logger.info(metaPollLog, "Starting meta-polling for operation_id.");

    _stopMetaPolling(); 
    currentMetaPollingTranscriptionId = transcriptionId;
    metaPollAttempts = 0;

    _fetchOperationIdAndStartPolling(); 

    metaPollIntervalId = setInterval(_fetchOperationIdAndStartPolling, META_POLL_INTERVAL_MS);
}
window.Workflow.startWorkflowPollingForTranscription = _startWorkflowPollingForTranscription;

function _stopMetaPolling() {
    if (metaPollIntervalId) {
        clearInterval(metaPollIntervalId);
        metaPollIntervalId = null;
        window.logger.debug(workflowPollingLogPrefix, `Meta-polling stopped for TrID: ${currentMetaPollingTranscriptionId}`);
    }
    currentMetaPollingTranscriptionId = null;
    metaPollAttempts = 0;
}
window.Workflow.stopMetaPolling = _stopMetaPolling;

async function _fetchOperationIdAndStartPolling() {
    if (!currentMetaPollingTranscriptionId) {
        _stopMetaPolling(); 
        return;
    }

    const transcriptionId = currentMetaPollingTranscriptionId;
    const metaPollLog = `[WorkflowJS:Polling:MetaPoll:Tr${transcriptionId.substring(0,8)}]`; 
    metaPollAttempts++;

    window.logger.debug(metaPollLog, `Attempt ${metaPollAttempts} to fetch operation_id.`);

    try {
        const response = await fetch(`/api/transcriptions/${transcriptionId}/workflow-details`, {
            method: "GET",
            headers: { Accept: "application/json", "X-CSRFToken": window.csrfToken }
        });

        if (!response.ok) {
            window.logger.warn(metaPollLog, `Failed to fetch workflow details (${response.status}).`);
            if (metaPollAttempts >= MAX_META_POLL_ATTEMPTS || response.status === 404) {
                _stopMetaPolling(); 
                _updateWorkflowPanel(transcriptionId, { status: "error", error: "Could not retrieve workflow details." }); 
            }
            return;
        }

        const data = await response.json();
        const operationId = data.llm_operation_id;
        const operationStatusOnTranscription = data.llm_operation_status;

        if (operationId) {
            window.logger.info(metaPollLog, `Found operation_id: ${operationId}, status on transcript: ${operationStatusOnTranscription}.`);
            _stopMetaPolling(); 

            if (operationStatusOnTranscription === 'finished' || operationStatusOnTranscription === 'error') {
                window.logger.debug(metaPollLog, "Workflow status on transcription is terminal. Fetching full LLMOperation details.");
                const opResponse = await fetch(`/api/llm/operations/${operationId}/status`, {
                    method: "GET",
                    headers: { Accept: "application/json", "X-CSRFToken": window.csrfToken }
                });
                if (opResponse.ok) {
                    const opData = await opResponse.json();
                    _updateWorkflowPanel(transcriptionId, opData); 
                } else {
                     window.logger.warn(metaPollLog, `Failed to fetch full LLMOperation details for OpID ${operationId}. Using data from transcription record.`);
                     _updateWorkflowPanel(transcriptionId, { 
                        status: operationStatusOnTranscription,
                        error: data.llm_operation_error,
                        result: data.llm_operation_result,
                        operation_id: operationId,
                        completed_at: data.llm_operation_ran_at, 
                        input_text: data.pending_workflow_prompt_text 
                     });
                }
            } else {
                window.logger.debug(metaPollLog, "Workflow status on transcription is not terminal. Starting main poll for LLMOperation.");
                window.Workflow.startWorkflowPolling(transcriptionId, operationId); 
            }
        } else if (metaPollAttempts >= MAX_META_POLL_ATTEMPTS) {
            window.logger.warn(metaPollLog, "Max meta-poll attempts reached. Operation ID not found.");
            _stopMetaPolling(); 
            _updateWorkflowPanel(transcriptionId, { status: "error", error: "Workflow did not start or details are unavailable." }); 
        }

    } catch (error) {
        window.logger.error(metaPollLog, "Error during meta-polling:", error);
        if (metaPollAttempts >= MAX_META_POLL_ATTEMPTS) {
            _stopMetaPolling(); 
            _updateWorkflowPanel(transcriptionId, { status: "error", error: "Error checking workflow status." }); 
        }
    }
}
window.Workflow.fetchOperationIdAndStartPolling = _fetchOperationIdAndStartPolling;