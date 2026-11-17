// app/static/js/history/search.js
// Handles debounced AJAX search for the transcription history list.
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        const searchInput = document.getElementById('historySearch');
        if (!searchInput) return;

        const historyList = document.getElementById('transcriptionHistory');
        const clearBtn = document.getElementById('historySearchClear');
        const statusEl = document.getElementById('searchStatus');
        const paginationContainer = document.querySelector('.pagination-container');

        let debounceTimer = null;
        let originalContent = null;

        function saveOriginal() {
            if (originalContent === null) {
                originalContent = {
                    listHTML: historyList.innerHTML,
                    paginationEl: paginationContainer ? paginationContainer.cloneNode(true) : null,
                };
            }
        }

        function restoreOriginal() {
            if (!originalContent) return;
            historyList.innerHTML = originalContent.listHTML;
            const currentPagination = document.querySelector('.pagination-container');
            if (currentPagination && originalContent.paginationEl) {
                currentPagination.replaceWith(originalContent.paginationEl.cloneNode(true));
            } else if (!currentPagination && originalContent.paginationEl) {
                historyList.parentNode.appendChild(originalContent.paginationEl.cloneNode(true));
            }
            if (typeof window.applyPillStyles === 'function') {
                window.applyPillStyles('#transcriptionHistory .prompt-label-pill');
            }
            if (typeof window.addReadMoreToWorkflowHTML === 'function') {
                document.querySelectorAll('#transcriptionHistory .workflow-result-text').forEach(function (el) {
                    if (el.dataset.fullText) window.addReadMoreToWorkflowHTML(el);
                });
            }
            originalContent = null;
            statusEl.textContent = '';
            statusEl.classList.add('hidden');
        }

        async function doSearch(query) {
            const canDownload = window.USER_PERMISSIONS && window.USER_PERMISSIONS.allow_download_transcript || false;
            const canRunWorkflow = window.USER_PERMISSIONS && window.USER_PERMISSIONS.allow_workflows || false;

            historyList.innerHTML = '<li class="py-8 flex justify-center"><span class="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-primary"></span></li>';
            const currentPagination = document.querySelector('.pagination-container');
            if (currentPagination) currentPagination.classList.add('hidden');

            try {
                // Search within the filters applied to the page (date, model, ...).
                const params = window.History && window.History.filters
                    ? window.History.filters.activeFilterParams(window.location.search)
                    : new URLSearchParams();
                params.set('q', query);
                const resp = await fetch(
                    '/api/transcriptions/search?' + params.toString(),
                    { headers: { 'X-CSRFToken': window.csrfToken || '' } }
                );
                if (!resp.ok) throw new Error('Search request failed');
                const data = await resp.json();

                historyList.innerHTML = '';

                if (!data.items || data.items.length === 0) {
                    const escapedQuery = typeof window.escapeHtml === 'function'
                        ? window.escapeHtml(query)
                        : query.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
                    historyList.innerHTML =
                        '<li class="py-8 text-center text-text-muted" id="history-placeholder">' +
                        '<i class="material-icons text-3xl mb-2 block">search_off</i>' +
                        (window.i18n && window.i18n.noResultsFor
                            ? window.i18n.noResultsFor + ' &ldquo;' + escapedQuery + '&rdquo;'
                            : 'No transcriptions matched &ldquo;' + escapedQuery + '&rdquo;.') +
                        '</li>';
                    statusEl.textContent = '';
                    statusEl.classList.add('hidden');
                } else {
                    data.items.forEach(function (item) {
                        window.addTranscriptionToHistory(item, canDownload, canRunWorkflow, false, false, false);
                    });
                    statusEl.textContent = data.total === 1 ? '1 result' : data.total + ' results';
                    statusEl.classList.remove('hidden');
                }
            } catch (err) {
                historyList.innerHTML = '<li class="py-4 text-center text-red-600">Search failed. Please try again.</li>';
                const currentPaginationAfterError = document.querySelector('.pagination-container');
                if (currentPaginationAfterError) currentPaginationAfterError.classList.remove('hidden');
            }
        }

        searchInput.addEventListener('input', function () {
            const query = searchInput.value.trim();
            if (clearBtn) clearBtn.classList.toggle('hidden', !query);

            clearTimeout(debounceTimer);
            if (!query) {
                restoreOriginal();
                return;
            }
            saveOriginal();
            debounceTimer = setTimeout(function () { doSearch(query); }, 350);
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                searchInput.value = '';
                clearBtn.classList.add('hidden');
                restoreOriginal();
                searchInput.focus();
            });
        }
    });
})();
