// app/static/js/main_actions.js
// Handles transcription submission and cancellation actions.

let jobApiName = null;
let jobFilename = null;
let currentJobIdForStop = null;
window.cancellationRequestedForJobId = null;

let expectedTimes = { upload: 0, processing: 0, transcription: 0, total: 0 };
let progressBoundaries = { upload: 0, processing: 0, transcriptionStart: 0 };

const mainActionsLogPrefix = "[MainActionsJS]";
const actionsLogger = window.logger.scoped("MainActionsJS");
const expectedLogger = window.logger.scoped("MainActionsJS:calculateExpected");
const stopLogger = window.logger.scoped("MainActionsJS:handleStopTranscription");

const timeFormulas = {
    'gpt-transcribe': {
        'no_split': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 1 + l * 0.05, transcription: (l) => 2 + l * 0.2 },
        'parallel': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 1.5 },
        'series':   { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 3.5 }
    },
    'gpt-4o-transcribe': {
        'no_split': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 1 + l * 0.05, transcription: (l) => 2 + l * 0.2 },
        'parallel': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 1.5 },
        'series':   { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 3.5 }
    },
    'whisper': {
        'no_split': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 1 + l * 0.05, transcription: (l) => 2 + l * 0.2 },
        'parallel': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 1.5 },
        'series':   { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 3.5 }
    },
    'assemblyai': {
        'no_split': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 1 + l * 0.05, transcription: (l) => 3 + l * 0.7 },
        'parallel': { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 6 + l * 0.8 },
        'series':   { upload: (s) => 0.5 + s * 0.1, processing: (l) => 2 + l * 0.1,  transcription: (l) => 5 + l * 8.3 }
    }
};

function setProgressBarWidth(progressBarElement, value) {
    if (!progressBarElement) {
        return;
    }
    const normalizedValue = typeof value === 'number' ? `${value}%` : value;
    progressBarElement.style.setProperty('--progress', normalizedValue);
}

function calculateExpectedProgressData(apiChoice, fileSizeMB, audioLengthMin, scenario) {
    const formulas = timeFormulas[apiChoice]?.[scenario];

    if (!formulas) {
        expectedLogger.error(`No time formulas found for API '${apiChoice}' and scenario '${scenario}'. Using defaults.`);
        expectedTimes = { upload: 5, processing: 5, transcription: 60, total: 70 };
        progressBoundaries = { upload: 7, processing: 14, transcriptionStart: 14 };
        return;
    }

    const size = typeof fileSizeMB === 'number' ? fileSizeMB : 0;
    const length = typeof audioLengthMin === 'number' ? audioLengthMin : 0;

    expectedTimes.upload = formulas.upload(size);
    expectedTimes.processing = formulas.processing(length);
    expectedTimes.transcription = formulas.transcription(length);
    expectedTimes.total = expectedTimes.upload + expectedTimes.processing + expectedTimes.transcription;

    if (expectedTimes.total <= 0) {
        expectedLogger.warn(`Calculated total expected time is zero or negative (${expectedTimes.total}s). Forcing minimum thresholds.`);
        expectedTimes.total = 1;
        if (expectedTimes.upload <= 0) expectedTimes.upload = 0.2;
        if (expectedTimes.processing <= 0) expectedTimes.processing = 0.2;
        if (expectedTimes.transcription <= 0) expectedTimes.transcription = 0.6;
    }

    progressBoundaries.upload = Math.round((expectedTimes.upload / expectedTimes.total) * 100);
    progressBoundaries.processing = Math.round(((expectedTimes.upload + expectedTimes.processing) / expectedTimes.total) * 100);
    progressBoundaries.transcriptionStart = progressBoundaries.processing;

    progressBoundaries.upload = Math.max(1, Math.min(progressBoundaries.upload, 90));
    if (progressBoundaries.upload < 95) {
        progressBoundaries.processing = Math.max(progressBoundaries.upload + 1, Math.min(progressBoundaries.processing, 95));
    } else {
        progressBoundaries.processing = progressBoundaries.upload;
    }
    progressBoundaries.transcriptionStart = progressBoundaries.processing;

    expectedLogger.debug("Expected timings computed.", {
        apiChoice,
        scenario,
        sizeMB: Number(size.toFixed(2)),
        lengthMinutes: Number(length.toFixed(2)),
        expectedTimes: {
            upload: Number(expectedTimes.upload.toFixed(2)),
            processing: Number(expectedTimes.processing.toFixed(2)),
            transcription: Number(expectedTimes.transcription.toFixed(2)),
            total: Number(expectedTimes.total.toFixed(2))
        },
        progressBoundaries: { ...progressBoundaries }
    });
}

async function refreshCsrfToken() {
    const response = await fetch('/api/csrf-token', {
        method: 'GET',
        cache: 'no-store',
        headers: { 'Accept': 'application/json' }
    });

    if (response.status === 401) {
        throw new Error('Authentication required (401)');
    }
    if (!response.ok) {
        throw new Error(`Unable to refresh session security token (${response.status})`, {
            cause: { code: 'CSRF_REFRESH_FAILED' }
        });
    }

    const data = await response.json();
    if (!data.csrf_token) {
        throw new Error('Unable to refresh session security token', {
            cause: { code: 'CSRF_REFRESH_FAILED' }
        });
    }

    window.csrfToken = data.csrf_token;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        csrfMeta.setAttribute('content', data.csrf_token);
    }
    return data.csrf_token;
}

async function submitTranscriptionRequest(formData, apiChoice, retryOnCsrfFailure = true) {
    const response = await fetch('/api/transcribe', {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': window.csrfToken,
            'Accept': 'application/json',
            'X-Transcription-Provider': apiChoice
        }
    });

    if (response.status === 401) throw new Error('Authentication required (401)');

    const parseErrorData = async (fallback) => response.json().catch(() => fallback);

    if (response.status === 400) {
        const errData = await parseErrorData({ error: 'Request failed with status 400' });
        if (errData.code === 'CSRF_TOKEN_INVALID' && retryOnCsrfFailure) {
            actionsLogger.info("Refreshing expired CSRF token before retrying transcription request.");
            await refreshCsrfToken();
            return submitTranscriptionRequest(formData, apiChoice, false);
        }
        throw new Error(errData.error || 'Request failed with status 400', { cause: errData });
    }

    if (response.status === 403 || response.status === 413) {
        const errData = await parseErrorData({ error: `Request failed with status ${response.status}` });
        errData.code = errData.code || (response.status === 413 ? 'SIZE_LIMIT_EXCEEDED' : 'PERMISSION_DENIED');
        throw new Error(errData.error || `Request forbidden (${response.status})`, { cause: errData });
    }

    if (response.status === 429) {
        const errData = await parseErrorData({ error: 'You have submitted too many transcription jobs recently. Please try again in an hour.' });
        throw new Error(errData.error || 'Rate limit exceeded', { cause: { code: 'RATE_LIMIT_EXCEEDED' } });
    }

    if (!response.ok) {
        const errData = await parseErrorData({ error: `HTTP error! Status: ${response.status}` });
        throw new Error(errData.error || `HTTP error! Status: ${response.status}`, { cause: errData });
    }

    return response.json();
}

async function handleTranscribeSubmit() {
    const apiSelect = document.getElementById('apiSelect');
    const fileInput = document.getElementById('audioFile');
    const contextPromptInput = document.getElementById('contextPrompt');

    actionsLogger.info("Transcribe button clicked.", {
        api: apiSelect ? apiSelect.value : null,
        hasFileSelected: Boolean(fileInput && fileInput.files && fileInput.files.length > 0)
    });

    if (typeof window.checkTranscribeButtonState !== 'function') {
        actionsLogger.error("checkTranscribeButtonState function not found.");
        window.showNotification('Error: Cannot verify readiness.', 'error', 4000, false);
        return;
    }

    const canProceed = await window.checkTranscribeButtonState();
    if (!canProceed) {
        actionsLogger.warn("Transcription submission blocked by frontend readiness check.");
        const statusSpan = document.getElementById('transcribeBtnStatus');
        const statusText = statusSpan ? statusSpan.textContent.trim() : '';

        // If there's a specific error message under the button (e.g., word count), show it.
        // Otherwise, show a generic message. The API key error is now handled by the main banner.
        if (statusText) {
            window.showNotification(statusText, 'warning', 4000, false);
        } else {
            // This case now primarily covers the API key missing scenario, where the banner is already visible.
            // We can show a less intrusive, short-lived toast to prompt the user to look at the banner.
            const apiKeyNotification = document.getElementById('api-key-notification');
            if (apiKeyNotification) {
                window.showNotification('Please resolve the issues noted above.', 'warning', 3000, false);
            } else {
                window.showNotification('Cannot start transcription. Please check requirements.', 'warning', 4000, false);
            }
        }
        return;
    }

    const form = document.getElementById('transcription-form');
    const languageSelect = document.getElementById('languageSelect');
    const transcribeBtn = document.getElementById('transcribeBtn');
    const stopBtn = document.getElementById('stopBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressPercentage = document.getElementById('progressPercentage');
    const statusSpan = document.getElementById('transcribeBtnStatus');

    const pendingWorkflowPromptTextElem = document.getElementById('pendingWorkflowPromptText');
    const pendingWorkflowPromptTitleElem = document.getElementById('pendingWorkflowPromptTitle');
    const pendingWorkflowPromptColorElem = document.getElementById('pendingWorkflowPromptColor');


    if (typeof window.resetPollingState === 'function') {
        window.resetPollingState();
    } else {
        actionsLogger.error("resetPollingState function not found.");
        if (window.currentPollIntervalId) { clearInterval(window.currentPollIntervalId); window.currentPollIntervalId = null; }
    }
    statusSpan.innerHTML = '';
    window.cancellationRequestedForJobId = null;

    const file = fileInput.files[0];
    if (!file) {
        window.showNotification('Please select an audio file.', 'error', 4000, false);
        return;
    }

    transcribeBtn.disabled = true;
    transcribeBtn.innerHTML = 'PROCESSING...';
    stopBtn.classList.remove('hidden');
    stopBtn.disabled = false;
    stopBtn.innerHTML = '<i class="material-icons text-base">close</i><span>Stop</span>';

    progressContainer.style.display = 'block';
    setProgressBarWidth(progressBar, 0);
    progressPercentage.textContent = '0%';
    jobFilename = file.name;
    jobApiName = window.API_NAME_MAP_FRONTEND[apiSelect.value] || apiSelect.value;

    if (typeof window.updateProgressActivity === 'function') {
        window.updateProgressActivity('cloud_upload', `Uploading audio for ${jobApiName}...`);
    } else {
        actionsLogger.error("updateProgressActivity function not found.");
    }

    const formData = new FormData(form);

    if (pendingWorkflowPromptTextElem && pendingWorkflowPromptTextElem.value) {
        formData.append('pending_workflow_prompt_text', pendingWorkflowPromptTextElem.value);
        if (pendingWorkflowPromptTitleElem && pendingWorkflowPromptTitleElem.value) {
            formData.append('pending_workflow_prompt_title', pendingWorkflowPromptTitleElem.value);
        }
        if (pendingWorkflowPromptColorElem && pendingWorkflowPromptColorElem.value) {
            formData.append('pending_workflow_prompt_color', pendingWorkflowPromptColorElem.value);
        }
        actionsLogger.debug("Appending pending workflow data to submission.");
    }


    actionsLogger.info("Submitting transcription request via Fetch...", {
        api: apiSelect.value,
        filename: file.name,
        hasWorkflow: Boolean(pendingWorkflowPromptTextElem && pendingWorkflowPromptTextElem.value)
    });
    submitTranscriptionRequest(formData, apiSelect.value)
    .then(data => {
        if (data.job_id) {
            actionsLogger.info("Transcription job started successfully.", { jobId: data.job_id });
            currentJobIdForStop = data.job_id;
            window.showNotification(data.message || 'Transcription job started.', 'success', 4000, false);

            const apiChoice = apiSelect.value;
            const fileSizeMB = file.size / (1024 * 1024);
            const audioLengthMin = data.audio_length_minutes || 0;
            const contextProvided = contextPromptInput && contextPromptInput.value.trim() !== '';
            let scenario = 'no_split';
            const threshold = typeof LARGE_FILE_THRESHOLD_MB !== 'undefined' ? LARGE_FILE_THRESHOLD_MB : 25;
            if (fileSizeMB > threshold) {
                scenario = contextProvided ? 'series' : 'parallel';
            }
            calculateExpectedProgressData(apiChoice, fileSizeMB, audioLengthMin, scenario);

            if (typeof window.pollProgress === 'function') {
                window.pollProgress(data.job_id);
            } else {
                 actionsLogger.error("pollProgress function not found. Cannot poll for status.");
                 window.showNotification('Error: Could not start progress polling.', 'error', 4000, false);
                 if (typeof window.resetTranscribeUI === 'function') {
                     window.resetTranscribeUI(true, true);
                 }
            }
        } else {
            throw new Error("Received success response but no Job ID.");
        }
    })
    .catch(error => {
        actionsLogger.error('Error starting transcription.', error);
        const errorMessage = error.message || "An unknown error occurred.";
        const errorCode = error.cause?.code;

        if (errorCode === 'SIZE_LIMIT_EXCEEDED' || errorCode === 'COUNT_LIMIT_EXCEEDED' || errorCode === 'TIME_LIMIT_EXCEEDED') {
            window.showNotification(errorMessage, 'error', 6000, true);
        } else if (errorCode !== 'PERMISSION_DENIED') {
            window.showNotification(`Error: ${errorMessage}`, 'error', 8000, false);
        }

        let translatedError = { message: `Error: ${errorMessage}`, messageText: `Error: ${errorMessage}`, icon: 'error', iconColorClass: 'text-red-600' };
        if (typeof window.renderActionableError === 'function') {
            translatedError = window.renderActionableError(errorMessage, {
                status: 'error',
                api_used: apiSelect?.value,
                filename: file?.name,
            });
        } else if (typeof window.translateBackendErrorMessage === 'function') {
            translatedError = window.translateBackendErrorMessage(`ERROR: ${errorMessage}`);
        } else {
            actionsLogger.warn("Error presentation helpers not found.");
        }
        if (typeof window.updateProgressActivity === 'function') {
             window.updateProgressActivity(translatedError.icon, translatedError, translatedError.iconColorClass);
        }

        if (typeof window.setJobFinishedOrErrored === 'function') {
            window.setJobFinishedOrErrored(true);
        } else {
            window.jobIsFinishedOrErrored = true;
        }
        if (typeof window.resetTranscribeUI === 'function') {
            window.resetTranscribeUI(true, true);
        } else {
             const transcribeBtn = document.getElementById('transcribeBtn');
             if (transcribeBtn) {
                 transcribeBtn.disabled = false;
                 transcribeBtn.innerHTML = 'TRANSCRIBE <i class="material-icons right">send</i>';
             }
             if (typeof window.checkTranscribeButtonState === 'function') {
                window.checkTranscribeButtonState();
             }
        }

        if (errorMessage.includes('Authentication required')) {
            setTimeout(() => { window.location.href = '/login'; }, 2000);
        }
    })
    .finally(() => {
        if (pendingWorkflowPromptTextElem) pendingWorkflowPromptTextElem.value = "";
        if (pendingWorkflowPromptTitleElem) pendingWorkflowPromptTitleElem.value = "";
        if (pendingWorkflowPromptColorElem) pendingWorkflowPromptColorElem.value = "";
        const selectedInfoElem = document.getElementById('selectedWorkflowInfo');
        if (selectedInfoElem) {
            selectedInfoElem.textContent = '';
            selectedInfoElem.classList.add('hidden');
            selectedInfoElem.style.backgroundColor = '';
            selectedInfoElem.style.color = '';
        }
        actionsLogger.debug("Cleared pending workflow fields from main form.");
    });
}
window.handleTranscribeSubmit = handleTranscribeSubmit;

async function handleStopTranscription() {
    const stopBtn = document.getElementById('stopBtn');
    if (!stopBtn || stopBtn.disabled) {
        stopLogger.warn("Stop button not found or already disabled.");
        return;
    }
    if (!currentJobIdForStop) {
        stopLogger.error("No current job ID found to stop.");
        window.showNotification('Error: Cannot determine which job to stop.', 'error', 4000, false);
        return;
    }

    const jobIdToCancel = currentJobIdForStop;
    stopLogger.info("Stop requested.", { jobId: jobIdToCancel });
    stopBtn.disabled = true;
    stopBtn.innerHTML = '<span class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-current border-r-transparent"></span><span>Cancelling...</span>';

    if (typeof window.updateProgressActivity === 'function') {
        window.updateProgressActivity('cancel', 'Requesting cancellation...', 'text-warning');
    } else {
        stopLogger.error("updateProgressActivity function not found.");
    }

    try {
        const response = await fetch(`/api/transcribe/${jobIdToCancel}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': window.csrfToken, 'Accept': 'application/json' }
        });

        if (response.ok) {
            const data = await response.json();
            stopLogger.info("Cancellation request acknowledged by server.", { jobId: jobIdToCancel, message: data.message });
            window.cancellationRequestedForJobId = jobIdToCancel;
            if (typeof window.updateProgressActivity === 'function') {
                window.updateProgressActivity('cancel', 'Cancellation requested. Waiting for process to stop...', 'text-warning');
            }
             window.showNotification('Cancellation requested. Processing will stop.', 'success', 4000, false);

            setTimeout(() => {
                if (window.currentJobId === jobIdToCancel && window.cancellationRequestedForJobId === jobIdToCancel) {
                    stopLogger.warn("Frontend forcing UI to cancelled state after timeout.", { jobId: jobIdToCancel });
                    if (typeof window.updateProgressActivity === 'function') {
                        window.updateProgressActivity('cancel', 'Transcription cancelled by user.', 'text-warning');
                    }
                    if (typeof window.resetTranscribeUI === 'function') {
                        window.resetTranscribeUI(true, false);
                        setTimeout(() => {
                            const progressContainer = document.getElementById('progressContainer');
                            if (progressContainer && window.currentJobId === jobIdToCancel) {
                                progressContainer.style.display = 'none';
                            }
                        }, 3000);
                    }
                    if (typeof window.resetPollingState === 'function') {
                        window.resetPollingState();
                    }
                } else {
                    stopLogger.debug("Cancellation timeout expired but job already settled.", { jobId: jobIdToCancel });
                }
            }, 5000);

        } else {
            let errorMsg = `Failed to request cancellation (Status: ${response.status})`;
            try { const errData = await response.json(); errorMsg = errData.error || errorMsg; } catch (e) {}
            stopLogger.error("Cancellation request failed.", { jobId: jobIdToCancel, error: errorMsg });
            window.showNotification(`Error: ${errorMsg}`, 'error', 5000, false);
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="material-icons text-base">close</i><span>Stop</span>';
        }
    } catch (error) {
        stopLogger.error("Network error requesting cancellation.", error);
        window.showNotification('Network error trying to stop transcription.', 'error', 4000, false);
        stopBtn.disabled = false;
        stopBtn.innerHTML = '<i class="material-icons text-base">close</i><span>Stop</span>';
    }
}
window.handleStopTranscription = handleStopTranscription;

actionsLogger.info("Action handlers loaded.");
