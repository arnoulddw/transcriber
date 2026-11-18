/* app/static/js/access_settings.js */
/* User Settings modal: General/Access tabs plus the Password & sign-in and Team mode actions. */

(function () {
    'use strict';

    const LOG = '[AccessSettings]';
    const log = (level, ...args) => (window.logger && window.logger[level] ? window.logger[level](LOG, ...args) : null);
    const notify = (message, type) => {
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type, type === 'error' ? 6000 : 4000, false);
        }
    };

    // ----- Tabs ------------------------------------------------------------

    function selectProfileTab(name, focus) {
        const tabs = Array.from(document.querySelectorAll('[data-profile-tab]'));
        tabs.forEach((tab) => {
            const active = tab.dataset.profileTab === name;
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
            tab.tabIndex = active ? 0 : -1;
            const panel = document.getElementById(tab.getAttribute('aria-controls'));
            if (panel) panel.classList.toggle('hidden', !active);
            if (active && focus) tab.focus();
        });
    }
    window.selectProfileTab = selectProfileTab;

    function initTabs() {
        const tabs = Array.from(document.querySelectorAll('[data-profile-tab]'));
        tabs.forEach((tab, index) => {
            tab.addEventListener('click', () => selectProfileTab(tab.dataset.profileTab, false));
            tab.addEventListener('keydown', (event) => {
                if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
                event.preventDefault();
                const step = event.key === 'ArrowRight' ? 1 : -1;
                const next = tabs[(index + step + tabs.length) % tabs.length];
                selectProfileTab(next.dataset.profileTab, true);
            });
        });
    }

    // Links elsewhere (e.g. the Admin panel) can open Settings on the Access tab.
    function openAccessFromHash() {
        if (window.location.hash !== '#settings-access') return;
        const trigger = document.getElementById('profileSettingsBtn') || document.getElementById('profileSettingsBtnMobile');
        if (trigger) trigger.click();
        selectProfileTab('access', false);
        history.replaceState(null, '', window.location.pathname + window.location.search);
    }

    // ----- Show / hide helpers ---------------------------------------------

    function setRevealed(targetId, show) {
        const target = document.getElementById(targetId);
        if (!target) return;
        target.classList.toggle('hidden', !show);
        document.querySelectorAll(`[data-access-reveal="${targetId}"]`).forEach((btn) => {
            btn.setAttribute('aria-expanded', show ? 'true' : 'false');
            btn.classList.toggle('hidden', show);
        });
        if (show) {
            const first = target.querySelector('input:not([type=hidden]):not([disabled]), button');
            if (first) first.focus();
        } else {
            clearErrors(target);
            if (target.tagName === 'FORM') target.reset();
            showTeamStep(target, 1);
            const opener = document.querySelector(`[data-access-reveal="${targetId}"]`);
            if (opener) opener.focus();
        }
    }

    function initRevealButtons() {
        document.querySelectorAll('[data-access-reveal]').forEach((btn) => {
            btn.addEventListener('click', () => setRevealed(btn.dataset.accessReveal, true));
        });
        document.querySelectorAll('[data-access-hide]').forEach((btn) => {
            btn.addEventListener('click', () => setRevealed(btn.dataset.accessHide, false));
        });
    }

    // ----- Errors ------------------------------------------------------------

    function clearErrors(form) {
        form.querySelectorAll('[data-error-for]').forEach((el) => { el.textContent = ''; });
        form.querySelectorAll('[aria-invalid]').forEach((el) => el.removeAttribute('aria-invalid'));
    }

    function showErrors(form, errors, fallback) {
        let shown = false;
        Object.entries(errors || {}).forEach(([field, messages]) => {
            const slot = form.querySelector(`[data-error-for="${field}"]`);
            const text = Array.isArray(messages) ? messages.join(' ') : String(messages);
            if (slot) {
                slot.textContent = text;
                shown = true;
            }
            const input = form.querySelector(`[name="${field}"]`);
            if (input) input.setAttribute('aria-invalid', 'true');
        });
        if (!shown && fallback) {
            const formSlot = form.querySelector('[data-error-for="_form"]');
            if (formSlot) formSlot.textContent = fallback;
        }
        if (fallback) notify(fallback, 'warning');
    }

    // ----- Requests ----------------------------------------------------------

    async function send(method, url, body) {
        const response = await fetch(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': window.csrfToken,
            },
            body: JSON.stringify(body || {}),
        });
        let data = {};
        try { data = await response.json(); } catch (e) { data = {}; }
        return { ok: response.ok, data };
    }

    async function submitForm(form, method, url, body, { reload = true } = {}) {
        clearErrors(form);
        const buttons = Array.from(form.querySelectorAll('button[type=submit]'));
        buttons.forEach((b) => { b.disabled = true; });
        try {
            const { ok, data } = await send(method, url, body);
            if (!ok) {
                showErrors(form, data.errors, data.error || 'Something went wrong. Please try again.');
                // Send the user back to the step that holds the failing field.
                const firstField = Object.keys(data.errors || {})[0];
                if (firstField && form.querySelector(`[data-team-step="1"] [name="${firstField}"]`)) {
                    showTeamStep(form, 1);
                }
                return false;
            }
            notify(data.message || 'Saved.', 'success');
            if (reload) setTimeout(() => window.location.reload(), 900);
            return true;
        } catch (error) {
            log('error', 'Request failed', error);
            showErrors(form, null, 'Could not reach the server. Please try again.');
            return false;
        } finally {
            buttons.forEach((b) => { b.disabled = false; });
        }
    }

    const value = (form, name) => {
        const input = form.querySelector(`[name="${name}"]`);
        return input ? input.value : undefined;
    };

    // ----- Team mode steps ---------------------------------------------------

    function showTeamStep(form, step) {
        if (!form || form.dataset.accessForm !== 'enable-team') return;
        form.querySelectorAll('[data-team-step]').forEach((el) => {
            const hasStepOne = form.dataset.hasStepOne === 'true';
            const visibleStep = hasStepOne ? step : 2;
            el.classList.toggle('hidden', String(visibleStep) !== el.dataset.teamStep);
        });
    }

    function validateStepOne(form) {
        clearErrors(form);
        const errors = {};
        const email = form.querySelector('[name="email"]');
        if (email && !email.value.trim()) errors.email = ['Email is required for team mode.'];
        else if (email && !email.checkValidity()) errors.email = ['Please enter a valid email address.'];
        const password = form.querySelector('[name="password"]');
        const confirm = form.querySelector('[name="confirm_password"]');
        if (password && password.value.length < 8) errors.password = ['Password must be at least 8 characters long.'];
        else if (password && confirm && password.value !== confirm.value) errors.confirm_password = ['Passwords do not match.'];
        if (Object.keys(errors).length) {
            showErrors(form, errors, null);
            return false;
        }
        return true;
    }

    // ----- Wire up forms -----------------------------------------------------

    function initForms() {
        document.querySelectorAll('form[data-access-form]').forEach((form) => {
            const kind = form.dataset.accessForm;

            if (kind === 'enable-team') {
                const next = form.querySelector('[data-team-next]');
                const back = form.querySelector('[data-team-back]');
                if (next) next.addEventListener('click', () => { if (validateStepOne(form)) showTeamStep(form, 2); });
                if (back) back.addEventListener('click', () => showTeamStep(form, 1));
            }

            form.addEventListener('submit', (event) => {
                event.preventDefault();
                if (kind === 'set-password') {
                    const body = { password: value(form, 'password'), confirm_password: value(form, 'confirm_password') };
                    if (value(form, 'username') !== undefined) body.username = value(form, 'username');
                    if (value(form, 'email') !== undefined) body.email = value(form, 'email');
                    submitForm(form, 'POST', '/api/access/password', body);
                } else if (kind === 'remove-password') {
                    submitForm(form, 'DELETE', '/api/access/password', { current_password: value(form, 'current_password') });
                } else if (kind === 'enable-team') {
                    if (form.dataset.hasStepOne === 'true' && !validateStepOne(form)) {
                        showTeamStep(form, 1);
                        return;
                    }
                    const registration = form.querySelector('[name="allow_registration"]');
                    const body = { enabled: true, allow_registration: registration ? registration.checked : true };
                    ['email', 'password', 'confirm_password'].forEach((name) => {
                        if (value(form, name) !== undefined) body[name] = value(form, name);
                    });
                    submitForm(form, 'POST', '/api/access/team-mode', body);
                } else if (kind === 'disable-team') {
                    submitForm(form, 'POST', '/api/access/team-mode', { enabled: false, current_password: value(form, 'current_password') });
                }
            });
        });

        const registrationToggle = document.getElementById('accessRegistrationToggle');
        if (registrationToggle) {
            registrationToggle.addEventListener('change', async () => {
                const allowed = registrationToggle.checked;
                registrationToggle.disabled = true;
                try {
                    const { ok, data } = await send('POST', '/api/access/registration', { allowed });
                    if (!ok) {
                        registrationToggle.checked = !allowed;
                        notify(data.error || 'Could not change sign-ups.', 'error');
                    } else {
                        notify(data.message, 'success');
                    }
                } catch (error) {
                    registrationToggle.checked = !allowed;
                    notify('Could not reach the server. Please try again.', 'error');
                } finally {
                    registrationToggle.disabled = false;
                }
            });
        }

        const changeToggle = document.getElementById('changePasswordToggleBtn');
        const changeSection = document.getElementById('changePasswordSection');
        if (changeToggle && changeSection) {
            changeToggle.addEventListener('click', () => {
                changeToggle.setAttribute('aria-expanded', changeSection.classList.contains('hidden') ? 'false' : 'true');
            });
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (!document.getElementById('profileModal')) return;
        initTabs();
        initRevealButtons();
        initForms();
        openAccessFromHash();
        window.addEventListener('hashchange', openAccessFromHash);
    });
})();
