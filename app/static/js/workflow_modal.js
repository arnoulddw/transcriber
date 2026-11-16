// app/static/js/workflow_modal.js
// Handles workflow modal UI, prompt selection, submission, and general UI setup.

const workflowModalLogPrefix = "[WorkflowJS:Modal]";
let isWorkflowModalLoading = false;

// Modal State & Elements
let workflowModal = null;
let workflowModalOverlay = null;
let workflowModalPanel = null;
let workflowModalCloseButtons = [];
let previouslyFocusedElementWorkflow = null;

// --- Start of Utility functions ---
function qs(id) {
  return document.getElementById(id);
}

function createOption(value, text, dataset = {}) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = text;
  Object.keys(dataset).forEach(key => {
    opt.dataset[key] = dataset[key];
  });
  return opt;
}

function createOptgroup(label) {
  const group = document.createElement("optgroup");
  group.label = label;
  return group;
}

function updateSelect(selectElem) {
  window.logger.debug(workflowModalLogPrefix, `Select element '${selectElem.id}' updated with new options (Tailwind/HTML).`);
}

function updatePlaceholders() {
  const isSmallScreen = window.innerWidth < 600;
  document.querySelectorAll("input[data-placeholder-short], textarea[data-placeholder-short]").forEach(input => {
    input.placeholder = isSmallScreen && input.dataset.placeholderShort ? input.dataset.placeholderShort : input.dataset.placeholderLong;
  });
}
// --- End of Utility functions ---

window.Workflow = window.Workflow || {};

// Expose showToast on the Workflow namespace
window.Workflow.showToast = function(message, type = 'info') {
  let duration = 4000;
  if (type === 'error' || type === 'warning') {
    duration = 6000;
  }
  if (typeof window.showNotification === 'function') {
    window.showNotification(message, type, duration, false);
  } else {
    window.logger.warn(workflowModalLogPrefix, "window.showNotification not found. Toast:", type, message);
    alert(`${type.toUpperCase()}: ${message}`);
  }
};


function initializeWorkflowModalElements() {
    workflowModal = qs('workflowModal');
    workflowModalOverlay = qs('workflowModalOverlay');
    workflowModalPanel = qs('workflowModalPanel');
    if (workflowModal) {
        workflowModalCloseButtons = Array.from(workflowModal.querySelectorAll('#workflowModalCloseButtonHeader, #workflowModalCloseButtonFooter'));
    }

    if (!workflowModal || !workflowModalOverlay || !workflowModalPanel) {
        window.logger.warn(workflowModalLogPrefix, "One or more Workflow modal core elements not found.");
        return false;
    }
    return true;
}

function openWorkflowModalDialog() {
    if (!workflowModal || !workflowModalOverlay || !workflowModalPanel) {
        window.logger.error(workflowModalLogPrefix, "Cannot open Workflow modal: core elements missing.");
        return;
    }
    previouslyFocusedElementWorkflow = document.activeElement;

    workflowModal.classList.remove('hidden');
    workflowModalOverlay.classList.remove('hidden');
    workflowModalPanel.classList.remove('hidden');

    void workflowModal.offsetWidth; // Force reflow

    workflowModal.classList.add('opacity-100');
    workflowModalOverlay.classList.add('opacity-100');
    workflowModalPanel.classList.add('opacity-100', 'scale-100');
    workflowModalPanel.classList.remove('opacity-0', 'scale-95');

    workflowModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    const focusableElements = Array.from(
        workflowModalPanel.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        )
    ).filter(el => !el.disabled && !el.closest('.hidden'));

    if (focusableElements.length > 0) {
        focusableElements[0].focus();
    } else {
        workflowModalPanel.focus();
    }
    window.logger.info(workflowModalLogPrefix, "Workflow modal opened (Tailwind).");
}

function closeWorkflowModalDialog() {
    if (!workflowModal || !workflowModalOverlay || !workflowModalPanel) {
        window.logger.error(workflowModalLogPrefix, "Cannot close Workflow modal: core elements missing.");
        return;
    }

    workflowModal.classList.remove('opacity-100');
    workflowModalOverlay.classList.remove('opacity-100');
    workflowModalPanel.classList.remove('opacity-100', 'scale-100');
    workflowModalPanel.classList.add('opacity-0', 'scale-95');

    workflowModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';

    setTimeout(() => {
        workflowModal.classList.add('hidden');
        workflowModalOverlay.classList.add('hidden');
    }, 300);

    if (previouslyFocusedElementWorkflow) {
        previouslyFocusedElementWorkflow.focus();
        previouslyFocusedElementWorkflow = null;
    }
    window.logger.info(workflowModalLogPrefix, "Workflow modal closed (Tailwind).");

    if (workflowModal.dataset.mode === 'pre-apply' && !qs("pendingWorkflowPromptText").value) {
        delete workflowModal.dataset.mode;
        window.logger.debug(workflowModalLogPrefix, "Cleared pre-apply mode from workflow modal as no workflow was set.");
    }
}

async function _openWorkflowModal(transcriptionId) {
  if (isWorkflowModalLoading) {
    window.logger.warn(workflowModalLogPrefix, "Workflow modal is already loading data. Ignoring request.");
    return;
  }
  isWorkflowModalLoading = true;
  const logContext = transcriptionId ? `transcription ID: ${transcriptionId}` : "pre-apply mode";
  window.logger.info(workflowModalLogPrefix, `Opening workflow modal for ${logContext}`);

  const promptSelect = qs("workflowPromptSelect"),
    promptInput = qs("workflowPromptInput"),
    transcriptionIdInput = qs("workflowTranscriptionId"),
    submitBtn = qs("submitWorkflowBtn");

  if (!promptSelect || !promptInput || !transcriptionIdInput || !submitBtn) {
    window.logger.error(workflowModalLogPrefix, "Workflow modal form elements not found.");
    window.Workflow.showToast("Error opening workflow modal.", "error");
    isWorkflowModalLoading = false;
    return;
  }

  promptSelect.value = "";
  promptInput.value = "";
  transcriptionIdInput.value = transcriptionId || "";
  _validateWorkflowPrompt();

  while (promptSelect.options.length > 1) {
    promptSelect.remove(promptSelect.options.length - 1);
  }
  promptSelect.querySelectorAll("optgroup").forEach(group => group.remove());
  window.logger.debug(workflowModalLogPrefix, "Cleared existing options and optgroups.");

  const loadingOption = createOption("", "Loading Workflows...");
  loadingOption.disabled = true;
  loadingOption.id = "loading-workflows-option";
  promptSelect.appendChild(loadingOption);
  updateSelect(promptSelect);

  try {
    const response = await fetch("/api/user/prompts", {
        headers: { Accept: "application/json", "X-CSRFToken": window.csrfToken }
    });

    const existingLoadingOption = qs("loading-workflows-option");
    if (existingLoadingOption) existingLoadingOption.remove();

    if (response.ok) {
      const prompts = await response.json();
      if (prompts && prompts.length > 0) {
        const savedGroup = createOptgroup(window.i18n.yourSavedWorkflows || "Your Saved Workflows");
        prompts.forEach(prompt => {
          const isSystemDefined = prompt.source_template_id;
          const displayTitle = isSystemDefined
            ? (window.i18n.systemDefined || 'System defined - ') + prompt.title
            : prompt.title;
          savedGroup.appendChild(
            createOption(prompt.prompt_text, displayTitle, {
              promptId: prompt.id,
              promptColor: prompt.color || "#ffffff"
            })
          );
        });
        promptSelect.appendChild(savedGroup);
      }
    } else {
      window.logger.error(workflowModalLogPrefix, "Failed to load user workflows:", response.statusText);
      const errorOption = createOption("", "Error loading workflows");
      errorOption.disabled = true;
      promptSelect.appendChild(errorOption);
    }

    updateSelect(promptSelect);
    openWorkflowModalDialog();
  } catch (error) {
    window.logger.error(workflowModalLogPrefix, "Error fetching workflows for modal:", error);
    window.Workflow.showToast("Error loading workflows.", "error");
    const existingLoadingOption = qs("loading-workflows-option");
    if (existingLoadingOption) existingLoadingOption.remove();
    updateSelect(promptSelect);
    openWorkflowModalDialog();
  } finally {
    isWorkflowModalLoading = false;
  }
}
window.Workflow.openWorkflowModal = _openWorkflowModal;

function _handlePromptSelection() {
  const promptSelect = qs("workflowPromptSelect"),
    promptInput = qs("workflowPromptInput"),
    selectedOption = promptSelect.selectedOptions[0],
    selectedValue = selectedOption.value;

  promptInput.value = selectedValue;
  
  if (!selectedValue) {
    promptInput.focus();
  }

  promptInput.style.height = 'auto';
  promptInput.style.height = (promptInput.scrollHeight) + 'px';
  _validateWorkflowPrompt();
}
window.Workflow.handlePromptSelection = _handlePromptSelection;

function _validateWorkflowPrompt() {
  const promptInput = qs("workflowPromptInput"),
    wordCountSpan = qs("workflowPromptWordCount"),
    submitBtn = qs("submitWorkflowBtn");
  if (!promptInput || !wordCountSpan || !submitBtn) return;

  const text = promptInput.value.trim(),
    words = text.match(/\S+/g) || [],
    wordCount = words.length,
    maxWords = 120;

  wordCountSpan.textContent = `${wordCount}/${maxWords} words`;
  if (wordCount > maxWords || wordCount === 0) {
    wordCountSpan.classList.add("text-red-600");
    wordCountSpan.classList.remove("text-gray-500");
    promptInput.classList.add("border-red-500", "focus:border-red-500", "focus:ring-red-500");
    promptInput.classList.remove("border-gray-300", "focus:border-primary", "focus:ring-primary");
    submitBtn.disabled = true;
  } else {
    wordCountSpan.classList.remove("text-red-600");
    wordCountSpan.classList.add("text-gray-500");
    promptInput.classList.remove("border-red-500", "focus:border-red-500", "focus:ring-red-500");
    promptInput.classList.add("border-gray-300", "focus:border-primary", "focus:ring-primary");
    submitBtn.disabled = false;
  }
}
window.Workflow.validateWorkflowPrompt = _validateWorkflowPrompt;

async function _handleSubmitWorkflow() {
    const submitLog = "[WorkflowJS:Modal:handleSubmit]";
    const modalElem = qs("workflowModal");
    const transcriptionIdInput = qs("workflowTranscriptionId");
    const transcriptionId = transcriptionIdInput.value;
    const promptInput = qs("workflowPromptInput");
    const promptSelect = qs("workflowPromptSelect");
    const submitBtn = qs("submitWorkflowBtn");
    const prompt = promptInput.value.trim();

    if (!prompt || submitBtn.disabled) {
        window.Workflow.showToast("Please enter a valid workflow prompt.", "warning");
        return;
    }

    const isPreApplyMode = modalElem.dataset.mode === 'pre-apply';
    const selectedOption = promptSelect.selectedOptions[0];
    const promptTitle = (selectedOption && selectedOption.value === prompt) ? selectedOption.textContent : "Custom Workflow";
    const promptColor = (selectedOption && selectedOption.value === prompt) ? (selectedOption.dataset.promptColor || '#ffffff') : '#ffffff';
    const promptId = (selectedOption && selectedOption.value === prompt) ? (selectedOption.dataset.promptId || null) : null;


    if (isPreApplyMode) {
        window.logger.info(submitLog, `Pre-applying workflow. Title: ${promptTitle}, Color: ${promptColor}, Origin ID: ${promptId}`);
        const pendingTextElem = qs("pendingWorkflowPromptText");
        const pendingTitleElem = qs("pendingWorkflowPromptTitle");
        const pendingColorElem = qs("pendingWorkflowPromptColor");
        const pendingOriginPromptIdElem = qs("pendingWorkflowOriginPromptId");
        const selectedInfoElem = qs("selectedWorkflowInfo");
        const applyWorkflowBtn = qs("applyWorkflowBtn");
        const removeWorkflowBtn = qs("removeWorkflowBtn");


        if (pendingTextElem) pendingTextElem.value = prompt;
        if (pendingTitleElem) pendingTitleElem.value = promptTitle;
        if (pendingColorElem) pendingColorElem.value = promptColor;
        if (pendingOriginPromptIdElem) {
            pendingOriginPromptIdElem.value = promptId || "";
            window.logger.debug(submitLog, `Set pendingWorkflowOriginPromptId to: ${pendingOriginPromptIdElem.value}`);
        }

        if (selectedInfoElem) {
            selectedInfoElem.textContent = `${window.i18n?.startWorkflow || 'Workflow'}: ${promptTitle}`;
            selectedInfoElem.classList.remove('hidden');
            selectedInfoElem.style.backgroundColor = promptColor;
            selectedInfoElem.style.color = typeof window.getTextColorForBackground === 'function'
                ? window.getTextColorForBackground(promptColor)
                : 'black';
        }

        if (applyWorkflowBtn && removeWorkflowBtn) {
            applyWorkflowBtn.classList.add('is-active');
            removeWorkflowBtn.classList.remove('hidden');
        }

        closeWorkflowModalDialog();
        return;
    }

    if (
        window.IS_MULTI_USER
        && typeof window.fetchReadinessData === 'function'
        && typeof window.getUsageQuotaExceededReason === 'function'
    ) {
        try {
            const readinessData = await window.fetchReadinessData();
            const quotaReason = window.getUsageQuotaExceededReason(
                readinessData,
                { workflows: 1 },
            );
            if (quotaReason) {
                window.Workflow.showToast(quotaReason, "warning");
                return;
            }
        } catch (error) {
            window.logger.error(submitLog, "Could not verify workflow usage limits:", error);
            window.Workflow.showToast("Could not verify usage limits. Please try again.", "error");
            return;
        }
    }

    if (!transcriptionId) {
        window.Workflow.showToast("Error: Transcription ID is missing.", "error");
        return;
    }

    const transcriptionItem = document.querySelector(`li[data-transcription-id="${transcriptionId}"]`);
    if (transcriptionItem) {
        transcriptionItem.dataset.workflowPrompt = prompt;
        if (selectedOption && selectedOption.value === prompt) {
            transcriptionItem.dataset.workflowLabel = selectedOption.textContent;
            transcriptionItem.dataset.workflowPromptColor = selectedOption.dataset.promptColor || "#ffffff";
            transcriptionItem.dataset.workflowOriginPromptId = selectedOption.dataset.promptId || "";
        } else {
            transcriptionItem.dataset.workflowLabel = "";
            transcriptionItem.dataset.workflowPromptColor = "#ffffff";
            transcriptionItem.dataset.workflowOriginPromptId = "";
        }
    }

    window.logger.info(submitLog, `Submitting workflow for ${transcriptionId} (PromptID: ${promptId})`);
    const originalButtonHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = 'Submitting... <span class="ml-2 inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span>';


    const historyItem = document.querySelector(`li[data-transcription-id="${transcriptionId}"]`),
        workflowPanel = historyItem?.querySelector(".workflow-panel"),
        startButtonActionDiv = historyItem?.querySelector(".start-workflow-action"),
        contentContainer = historyItem?.querySelector(".history-item-content");

    if (workflowPanel) {
        workflowPanel.className = "workflow-panel flex items-center justify-center min-h-[150px]";
        workflowPanel.innerHTML = `
            <div class="flex flex-col items-center text-gray-500">
              <span class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-primary mb-2"></span>
              <span>Processing Workflow...</span>
           </div>`;
        workflowPanel.style.display = "block";
        if (startButtonActionDiv) startButtonActionDiv.style.display = "none";
        if (contentContainer) contentContainer.classList.add("has-active-workflow");
    }

    closeWorkflowModalDialog();

    try {
        const payload = { prompt };
        if (promptId) payload.prompt_id = promptId;

        const response = await fetch(`/api/transcriptions/${transcriptionId}/workflow`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json",
                "X-CSRFToken": window.csrfToken
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP error ${response.status}`);

        window.Workflow.showToast(data.message || "Workflow started!", "success");
        window.logger.info(submitLog, "Workflow started successfully via API.");

        const operationId = data.operation_id;
        if (operationId && typeof window.Workflow.startWorkflowPolling === 'function') {
            window.Workflow.startWorkflowPolling(transcriptionId, operationId);
        } else {
            window.logger.error(submitLog, "API response successful but missing operation_id or startWorkflowPolling not available.");
            if (workflowPanel) {
                workflowPanel.className = "workflow-panel is-error text-center";
                workflowPanel.innerHTML = `<p class="text-red-700">Error: Could not track workflow status.</p>`;
            }
        }
    } catch (error) {
        window.logger.error(submitLog, "Error starting workflow:", error);
        window.Workflow.showToast(`Error: ${error.message}`, "error");
        if (workflowPanel) {
            workflowPanel.className = "workflow-panel is-error text-center";
            workflowPanel.innerHTML = `<p class="text-red-700">Workflow failed to start.</p>`;
            workflowPanel.style.display = "block";
            if (startButtonActionDiv) startButtonActionDiv.style.display = "block";
            if (contentContainer) contentContainer.classList.remove("has-active-workflow");
        }
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalButtonHtml;
    }
}
window.Workflow.handleSubmitWorkflow = _handleSubmitWorkflow;


document.addEventListener("DOMContentLoaded", function () {
  const logPrefix = "[WorkflowJS:Modal:DOMContentLoaded]";
  if (!initializeWorkflowModalElements()) {
      window.logger.warn(logPrefix, "Workflow modal setup skipped due to missing elements.");
  } else {
      workflowModalCloseButtons.forEach(button => {
          button.addEventListener('click', closeWorkflowModalDialog);
      });
      if (workflowModalOverlay) {
          workflowModalOverlay.addEventListener('click', closeWorkflowModalDialog);
      }
      document.addEventListener('keydown', (event) => {
          if (event.key === 'Escape' && workflowModal && !workflowModal.classList.contains('hidden')) {
              closeWorkflowModalDialog();
          }
          if (event.key === 'Tab' && workflowModal && !workflowModal.classList.contains('hidden')) {
                const focusableElements = Array.from(
                    workflowModalPanel.querySelectorAll(
                        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                    )
                ).filter(el => !el.disabled && !el.closest('.hidden'));

                if (focusableElements.length === 0) return;

                const firstFocusable = focusableElements[0];
                const lastFocusable = focusableElements[focusableElements.length - 1];

                if (event.shiftKey) {
                    if (document.activeElement === firstFocusable) {
                        lastFocusable.focus();
                        event.preventDefault();
                    }
                } else {
                    if (document.activeElement === lastFocusable) {
                        firstFocusable.focus();
                        event.preventDefault();
                    }
                }
            }
      });
  }

  const historyList = qs("transcriptionHistory");
  if (historyList) {
    historyList.addEventListener("click", function (event) {
      const startButton = event.target.closest(".start-workflow-btn");
      if (startButton) {
        event.preventDefault();
        const transcriptionItem = startButton.closest("li[data-transcription-id]");
        const transcriptionId = transcriptionItem?.dataset.transcriptionId;
        if (transcriptionId) {
          const workflowPanel = transcriptionItem.querySelector(".workflow-panel");
          const hasExistingResult =
            workflowPanel &&
            workflowPanel.style.display !== "none" &&
            workflowPanel.querySelector(".workflow-result-text, .text-red-700");
          if (hasExistingResult) {
            if (
              !confirm(
                "A workflow result already exists for this transcription. Starting a new workflow will overwrite the previous result. Do you want to continue?"
              )
            ) {
              window.logger.info(logPrefix, "Workflow start cancelled by user due to existing result.");
              return;
            }
            window.logger.info(logPrefix, "User confirmed overwriting existing workflow result.");
          }
          if (workflowModal) delete workflowModal.dataset.mode;
          window.Workflow.openWorkflowModal(transcriptionId);
        } else {
          window.logger.error(logPrefix, "Could not find transcription ID for workflow button.");
          window.Workflow.showToast("Error: Could not identify transcription.", "error");
        }
      }
    });
    window.logger.debug(logPrefix, "Workflow start button listener attached to history list.");
  }

  const promptSelect = qs("workflowPromptSelect");
  if (promptSelect) {
    promptSelect.addEventListener("change", window.Workflow.handlePromptSelection);
    window.logger.debug(logPrefix, "Workflow select listener attached.");
  }
  const promptInput = qs("workflowPromptInput");
  if (promptInput) {
    promptInput.addEventListener("input", window.Workflow.validateWorkflowPrompt);
    window.logger.debug(logPrefix, "Workflow input listener attached.");
  }
  const submitBtn = qs("submitWorkflowBtn");
  if (submitBtn) {
    submitBtn.addEventListener("click", window.Workflow.handleSubmitWorkflow);
    window.logger.debug(logPrefix, "Workflow submit listener attached.");
  }

  updatePlaceholders();
  if (typeof window.checkTranscribeButtonState === 'function') window.checkTranscribeButtonState(); else window.logger.error(logPrefix, "checkTranscribeButtonState function not found.");
  if (typeof window.validateContextPrompt === 'function') {
      const contextPromptElem = qs("contextPrompt");
      if (contextPromptElem) {
          contextPromptElem.addEventListener("input", window.validateContextPrompt);
          window.validateContextPrompt();
      }
  } else { window.logger.error(logPrefix, "validateContextPrompt function not found."); }

  if (typeof window.applyPillStyles === "function") window.applyPillStyles("#transcriptionHistory .prompt-label-pill"); else window.logger.error(logPrefix, "applyPillStyles function not found.");
  if (typeof window.addReadMoreToWorkflowHTML === "function") {
    document.querySelectorAll("#transcriptionHistory .workflow-result-text").forEach(el => window.addReadMoreToWorkflowHTML(el));
  } else { window.logger.error(logPrefix, "addReadMoreToWorkflowHTML function not found."); }
});
