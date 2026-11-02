const assert = require('node:assert/strict');
const test = require('node:test');
const crypto = require('node:crypto');
const cases = require('./layout_contract.json');
const {layoutResult} = require('./helpers.cjs');

test('chart layout and original-object mutations match the pre-refactor contract', () => {
  for (const {options, hash} of cases) {
    const result = layoutResult(options);
    const actual = crypto.createHash('sha256').update(JSON.stringify(result)).digest('hex');
    assert.equal(actual, hash, JSON.stringify({options, result}));
  }
});
