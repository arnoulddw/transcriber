// app/static/js/history/filters.js
// Transcription History filters: Filters toggle, chip dropdowns, the duration
// range popover and the rows-per-page selector. Filtering and paging happen on
// the server; this script only opens menus and builds the URLs to navigate to.
(function (root) {
    'use strict';

    const DURATION_MAX = 180;
    const DURATION_STEP = 5;
    // Filters that a change of page size or filter must keep.
    const FILTER_PARAMS = ['date', 'model', 'lang', 'dur_min', 'dur_max', 'workflow'];

    function formatDuration(minutes, max) {
        const top = max || DURATION_MAX;
        const m = Number(minutes) || 0;
        if (m >= top) return Math.floor(top / 60) + ' h+';
        if (m < 60) return m + ' min';
        const h = Math.floor(m / 60);
        const r = m % 60;
        return h + ' h' + (r ? ' ' + r : '');
    }

    // Chip text for a duration range: null means "Any".
    function durationLabel(min, max, top) {
        const limit = top || DURATION_MAX;
        const lo = Number(min) || 0;
        const hi = max === null || max === undefined || max === '' ? limit : Number(max);
        if (lo <= 0 && hi >= limit) return null;
        if (lo <= 0) return 'Under ' + formatDuration(hi, limit);
        if (hi >= limit) return 'Over ' + formatDuration(lo, limit);
        return formatDuration(lo, limit) + ' – ' + formatDuration(hi, limit);
    }

    // Keep the two thumbs at least one step apart; `moved` is 'min' or 'max'.
    function clampRange(min, max, moved, top, step) {
        const limit = top || DURATION_MAX;
        const gap = step || DURATION_STEP;
        let lo = Math.max(0, Math.min(limit, Number(min) || 0));
        let hi = Math.max(0, Math.min(limit, Number(max) || 0));
        if (lo > hi - gap) {
            if (moved === 'min') lo = Math.max(0, hi - gap);
            else hi = Math.min(limit, lo + gap);
            if (lo > hi - gap) lo = Math.max(0, hi - gap);
        }
        return { min: lo, max: hi };
    }

    // URL search string with `changes` applied; null/undefined removes a key.
    // Any change resets to page 1 unless `page` is part of the change.
    function buildHistorySearch(search, changes) {
        const params = new URLSearchParams(search || '');
        if (!Object.prototype.hasOwnProperty.call(changes, 'page')) params.delete('page');
        Object.keys(changes).forEach(function (key) {
            const value = changes[key];
            if (value === null || value === undefined || value === '') params.delete(key);
            else params.set(key, String(value));
        });
        const out = params.toString();
        return out ? '?' + out : '';
    }

    function durationChanges(min, max, top) {
        const limit = top || DURATION_MAX;
        return {
            dur_min: Number(min) > 0 ? Number(min) : null,
            dur_max: Number(max) < limit ? Number(max) : null,
        };
    }

    // Filter params of the current page, for the history search request.
    function activeFilterParams(search) {
        const params = new URLSearchParams(search || '');
        const out = new URLSearchParams();
        FILTER_PARAMS.forEach(function (key) {
            const value = params.get(key);
            if (value) out.set(key, value);
        });
        return out;
    }

    const api = {
        DURATION_MAX,
        DURATION_STEP,
        FILTER_PARAMS,
        formatDuration,
        durationLabel,
        clampRange,
        buildHistorySearch,
        durationChanges,
        activeFilterParams,
    };

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (!root || !root.document) return;

    const History = root.History || (root.History = {});
    History.filters = api;

    function navigate(changes) {
        root.location.assign(
            root.location.pathname + buildHistorySearch(root.location.search, changes) + '#history'
        );
    }

    function init() {
        const doc = root.document;
        const toggle = doc.getElementById('historyFiltersToggle');
        const row = doc.getElementById('historyFilters');
        if (!toggle || !row) return;

        toggle.addEventListener('click', function () {
            const open = row.hidden;
            row.hidden = !open;
            toggle.setAttribute('aria-expanded', String(open));
            if (!open) closeAll();
        });

        // --- Chip dropdowns and the duration popover ---
        const triggers = Array.prototype.slice.call(row.querySelectorAll('[data-filter-trigger]'));

        function closeAll(except) {
            triggers.forEach(function (trigger) {
                if (trigger === except) return;
                const pop = doc.getElementById(trigger.getAttribute('aria-controls'));
                if (pop) pop.hidden = true;
                trigger.setAttribute('aria-expanded', 'false');
            });
        }

        triggers.forEach(function (trigger) {
            const pop = doc.getElementById(trigger.getAttribute('aria-controls'));
            if (!pop) return;
            trigger.addEventListener('click', function (event) {
                event.stopPropagation();
                const open = pop.hidden;
                closeAll(trigger);
                pop.hidden = !open;
                trigger.setAttribute('aria-expanded', String(open));
                if (open) {
                    const first = pop.querySelector('[aria-checked="true"], a, input');
                    if (first) first.focus();
                }
            });
            pop.addEventListener('click', function (event) { event.stopPropagation(); });
            pop.addEventListener('keydown', function (event) {
                if (event.key === 'Escape') {
                    pop.hidden = true;
                    trigger.setAttribute('aria-expanded', 'false');
                    trigger.focus();
                }
            });
        });
        doc.addEventListener('click', function () { closeAll(); });
        doc.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closeAll();
        });

        // --- Duration range slider ---
        const durPop = doc.getElementById('historyDurationPop');
        if (durPop) {
            const lo = doc.getElementById('historyDurMin');
            const hi = doc.getElementById('historyDurMax');
            const fill = doc.getElementById('historyDurFill');
            const readout = doc.getElementById('historyDurReadout');
            const top = Number(hi.max) || DURATION_MAX;
            const step = Number(hi.step) || DURATION_STEP;

            function draw(moved) {
                const range = clampRange(lo.value, hi.value, moved, top, step);
                lo.value = range.min;
                hi.value = range.max;
                const a = range.min / top;
                const z = range.max / top;
                fill.style.left = 'calc(' + a + ' * (100% - 20px) + 10px)';
                fill.style.width = 'calc(' + (z - a) + ' * (100% - 20px))';
                readout.textContent = formatDuration(range.min, top) + ' – ' + formatDuration(range.max, top);
                lo.setAttribute('aria-valuetext', formatDuration(range.min, top));
                hi.setAttribute('aria-valuetext', formatDuration(range.max, top));
            }
            lo.addEventListener('input', function () { draw('min'); });
            hi.addEventListener('input', function () { draw('max'); });
            doc.getElementById('historyDurApply').addEventListener('click', function () {
                navigate(durationChanges(lo.value, hi.value, top));
            });
            doc.getElementById('historyDurReset').addEventListener('click', function () {
                lo.value = 0;
                hi.value = top;
                draw('max');
            });
            draw('max');
        }

        // --- Rows per page ---
        const perPage = doc.getElementById('historyPerPage');
        if (perPage) {
            perPage.addEventListener('change', function () {
                navigate({ per_page: perPage.value });
            });
        }
    }

    if (root.document.readyState === 'loading') {
        root.document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})(typeof window !== 'undefined' ? window : undefined);
