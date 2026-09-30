import assert from 'node:assert/strict';
import test from 'node:test';

import { loadConfig } from '../../public/gateway/gateway.mjs';
import { compactSchema } from '../../public/gateway/policy.mjs';

const validEnv = {
  ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com',
  ACCESS_AUD: 'aud-123',
  ACCESS_ALLOWED_EMAILS: 'user@example.com',
};

test('Cloudflare mode accepts only one cloudflareaccess.com team label', () => {
  for (const domain of [
    'https://example.cloudflareaccess.com',
    'example.cloudflareaccess.com/evil',
    'example.invalid',
    'sub.example.cloudflareaccess.com',
  ]) {
    assert.throws(
      () => loadConfig({ ...validEnv, ACCESS_TEAM_DOMAIN: domain }),
      /single Cloudflare Access team domain/,
    );
  }
});

test('schema compaction preserves __proto__ as data without prototype mutation', () => {
  const input = JSON.parse('{"type":"object","__proto__":{"description":"data"}}');
  const compacted = compactSchema(input);
  assert.equal(Object.getPrototypeOf(compacted), Object.prototype);
  assert.equal(Object.hasOwn(compacted, '__proto__'), true);
});
