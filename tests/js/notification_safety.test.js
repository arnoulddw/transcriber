const test = require('node:test');
const assert = require('node:assert/strict');

class FakeClassList {
    constructor(element) {
        this.element = element;
    }

    add(...names) {
        const values = new Set(this.element.className.split(/\s+/).filter(Boolean));
        names.forEach(name => values.add(name));
        this.element.className = [...values].join(' ');
    }

    remove(...names) {
        const values = new Set(this.element.className.split(/\s+/).filter(Boolean));
        names.forEach(name => values.delete(name));
        this.element.className = [...values].join(' ');
    }

    toggle(name, force) {
        const values = new Set(this.element.className.split(/\s+/).filter(Boolean));
        const shouldHave = force === undefined ? !values.has(name) : force;
        if (shouldHave) values.add(name);
        else values.delete(name);
        this.element.className = [...values].join(' ');
        return shouldHave;
    }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName.toLowerCase();
        this.children = [];
        this.parentNode = null;
        this.className = '';
        this.classList = new FakeClassList(this);
        this.dataset = {};
        this.attributes = {};
        this.listeners = {};
        this.style = { setProperty() {} };
        this._textContent = '';
        this._innerHTML = null;
    }

    set textContent(value) {
        this._textContent = String(value ?? '');
        this.children = [];
    }

    get textContent() {
        return this._textContent + this.children.map(child => child.textContent).join('');
    }

    set innerHTML(value) {
        this._innerHTML = String(value ?? '');
        this._textContent = '';
        this.children = [];
    }

    get innerHTML() {
        return this._innerHTML;
    }

    appendChild(child) {
        this._textContent = '';
        this.children.push(child);
        child.parentNode = this;
        return child;
    }

    remove() {
        if (!this.parentNode) return;
        this.parentNode.children = this.parentNode.children.filter(child => child !== this);
        this.parentNode = null;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    addEventListener(type, listener) {
        this.listeners[type] = listener;
    }

    dispatchEvent(event) {
        this.listeners[event.type]?.(event);
    }

    matches(selector) {
        const [tag, className] = selector.split('.');
        if (tag && tag !== '' && this.tagName !== tag.toLowerCase()) return false;
        return !className || this.className.split(/\s+/).includes(className);
    }

    querySelector(selector) {
        const parts = selector.trim().split(/\s+/);
        const find = (element, index) => {
            for (const child of element.children) {
                if (child.matches(parts[index])) {
                    if (index === parts.length - 1) return child;
                    const descendant = find(child, index + 1);
                    if (descendant) return descendant;
                }
                const descendant = find(child, index);
                if (descendant) return descendant;
            }
            return null;
        };
        return find(this, 0);
    }
}

const elementsById = new Map();
const notificationContainer = new FakeElement('div');
elementsById.set('notification-container', notificationContainer);
const progressElement = new FakeElement('div');
const progressContainer = new FakeElement('div');
const audioFileElement = new FakeElement('input');
audioFileElement.files = [{}];
elementsById.set('progressActivity', progressElement);
elementsById.set('progressContainer', progressContainer);
elementsById.set('audioFile', audioFileElement);

global.window = {
    APP_DEBUG_MODE: false,
    USER_PERMISSIONS: {},
    logger: {
        scoped: () => ({ debug() {}, info() {}, warn() {}, error() {} }),
    },
};
global.document = {
    body: new FakeElement('body'),
    addEventListener() {},
    createElement: tagName => new FakeElement(tagName),
    getElementById: id => elementsById.get(id) || null,
};
global.requestAnimationFrame = callback => callback();

const {
    showNotification,
    showNotificationWithAction,
} = require('../../app/static/js/main_utils.js');
const {
    updateProgressActivity,
    translateBackendErrorMessage,
    renderActionableError,
} = require('../../app/static/js/main_poll.js');

test('showNotification renders markup-looking messages as text', () => {
    const message = '<img src=x onerror="alert(1)">&lt;literal&gt;';
    const notification = showNotification(message, 'error', 0, false);
    const body = notification.querySelector('.alert-content p');

    assert.equal(body.textContent, message);
    assert.equal(body.innerHTML, null);
});

test('showNotificationWithAction keeps the action structured and text-safe', () => {
    let clicked = false;
    const notification = showNotificationWithAction(
        '<b>Deleted</b>',
        {
            label: '<Undo>',
            className: 'undo-delete-action',
            onClick: () => { clicked = true; },
        },
        'success',
        0,
        false,
    );
    const body = notification.querySelector('.alert-content p');
    const action = notification.querySelector('.undo-delete-action');

    // The action sits inline inside the message text, after a space.
    assert.equal(body.textContent, '<b>Deleted</b> <Undo>');
    assert.equal(action.parentNode, body);
    assert.equal(action.className.split(' ').includes('inline-action'), true);
    assert.equal(action.textContent, '<Undo>');
    action.dispatchEvent({ type: 'click' });
    assert.equal(clicked, true);
});

test('showNotificationWithAction turns the label inside the sentence into the link', () => {
    const notification = showNotificationWithAction(
        'API key needed. Add one in Manage API Keys to use all features.',
        { label: 'Manage API Keys', onClick: () => {} },
        'warning',
        0,
        true,
    );
    const body = notification.querySelector('.alert-content p');
    const action = notification.querySelector('.inline-action');

    // The label appears once: the phrase in the sentence is the action itself.
    assert.equal(body.textContent, 'API key needed. Add one in Manage API Keys to use all features.');
    assert.equal(action.textContent, 'Manage API Keys');
    assert.equal(action.parentNode, body);
});

test('updateProgressActivity renders ordinary progress text without HTML interpretation', () => {
    const message = '<img src=x onerror="alert(1)">';
    updateProgressActivity('info', message);
    const messageElement = progressElement.querySelector('.min-w-0');

    assert.equal(messageElement.textContent, message);
    assert.equal(progressElement.innerHTML, null);
});

test('actionable progress errors retain controls through structured DOM rendering', () => {
    window.USER_PERMISSIONS = {};
    const error = renderActionableError(
        'ERROR: could not decode audio <script>alert(1)</script>',
        { job_id: 'job-123456', status: 'error' },
    );
    updateProgressActivity(error.icon, error, error.iconColorClass);

    const messageElement = progressElement.querySelector('.min-w-0');
    const chooseFileButton = progressElement.querySelector('button');
    const technicalDetails = progressElement.querySelector('code');

    assert.equal(messageElement.textContent.includes('<script>'), true);
    assert.equal(chooseFileButton.textContent, 'Choose another file');
    assert.equal(technicalDetails.textContent.includes('<script>'), true);
    assert.equal(progressElement.innerHTML, null);
});

test('translated errors expose raw text separately from legacy rich markup', () => {
    window.USER_PERMISSIONS = { allow_api_key_management: true };
    const translated = translateBackendErrorMessage('ERROR: Permission denied: <x>');
    const keyError = translateBackendErrorMessage('ERROR: API key not configured');

    assert.equal(translated.messageText.includes('<x>'), true);
    assert.equal(translated.message.includes('&lt;x&gt;'), true);
    assert.equal(keyError.message.includes('<a href="#!"'), true);
});

test('translated API-key actions render as a safe progress button', () => {
    window.USER_PERMISSIONS = { allow_api_key_management: true };
    const translated = translateBackendErrorMessage('ERROR: API key not configured');
    updateProgressActivity(translated.icon, translated, translated.iconColorClass);

    const messageElement = progressElement.querySelector('.min-w-0');
    const actionButton = progressElement.querySelector('button');

    assert.equal(messageElement.textContent.includes('<a '), false);
    assert.equal(actionButton.textContent, 'Manage API Keys');
    assert.equal(actionButton.dataset.transcriptionErrorAction, 'manage-key');
    assert.equal(progressElement.innerHTML, null);
});
