const test = require('node:test');
const assert = require('node:assert/strict');

const {
    formatDuration,
    durationLabel,
    clampRange,
    buildHistorySearch,
    durationChanges,
    activeFilterParams,
} = require('../../app/static/js/history/filters.js');

test('formats slider stops as minutes, hours and the open-ended top', () => {
    assert.equal(formatDuration(0), '0 min');
    assert.equal(formatDuration(45), '45 min');
    assert.equal(formatDuration(60), '1 h');
    assert.equal(formatDuration(95), '1 h 35');
    assert.equal(formatDuration(180), '3 h+');
});

test('duration chip reads Under, Over, a range, or nothing for the full range', () => {
    assert.equal(durationLabel(0, 180), null);
    assert.equal(durationLabel(0, 60), 'Under 1 h');
    assert.equal(durationLabel(30, 180), 'Over 30 min');
    assert.equal(durationLabel(10, 60), '10 min – 1 h');
});

test('thumbs stay one step apart and the moved thumb gives way', () => {
    assert.deepEqual(clampRange(60, 40, 'min'), { min: 35, max: 40 });
    assert.deepEqual(clampRange(60, 40, 'max'), { min: 60, max: 65 });
    assert.deepEqual(clampRange(180, 180, 'min'), { min: 175, max: 180 });
    assert.deepEqual(clampRange(0, 0, 'max'), { min: 0, max: 5 });
});

test('changing a filter keeps the others and resets to page 1', () => {
    const search = '?date=30d&model=whisper&page=4&per_page=25';
    assert.equal(buildHistorySearch(search, { lang: 'fr' }), '?date=30d&model=whisper&per_page=25&lang=fr');
    assert.equal(buildHistorySearch(search, { model: null }), '?date=30d&per_page=25');
    assert.equal(buildHistorySearch('', {}), '');
});

test('a page change keeps the page parameter', () => {
    assert.equal(buildHistorySearch('?date=7d', { page: 3 }), '?date=7d&page=3');
});

test('full-range duration clears both bounds', () => {
    assert.deepEqual(durationChanges(0, 180), { dur_min: null, dur_max: null });
    assert.deepEqual(durationChanges(10, 180), { dur_min: 10, dur_max: null });
    assert.deepEqual(durationChanges(0, 60), { dur_min: null, dur_max: 60 });
});

test('search only forwards filter parameters', () => {
    const params = activeFilterParams('?date=7d&page=2&per_page=50&workflow=Summary&q=old');
    assert.equal(params.toString(), 'date=7d&workflow=Summary');
});
