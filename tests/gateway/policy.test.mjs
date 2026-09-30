import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ALL_ALLOWED_TOOLS,
  checkRequest,
  compactSchema,
  compactToolDefinition,
  parseAllowedTools,
  rewriteResponse,
} from '../../public/gateway/policy.mjs';

test('default allowlist exposes exactly the five options tools', () => {
  const allowed = parseAllowedTools();
  assert.deepEqual([...allowed], [
    'option_expirations',
    'option_chain',
    'option_positioning_summary',
    'option_surface_summary',
    'option_activity_summary',
  ]);
  assert.equal(ALL_ALLOWED_TOOLS.split(',').length, 5);
});

test('explicit allowlist override is authoritative', () => {
  assert.deepEqual([...parseAllowedTools('option_chain')], ['option_chain']);
});

test('non-allowlisted calls are blocked', () => {
  assert.deepEqual(
    checkRequest(
      { method: 'tools/call', params: { name: 'not_public' } },
      parseAllowedTools(),
    ),
    { error: 'Tool not available on the yfinance connector: not_public' },
  );
});

test('schema compaction preserves contract keys and trims prose', () => {
  const schema = compactSchema({
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    title: 'Example',
    description: 'x'.repeat(300),
    type: 'object',
    properties: {
      expiry: {
        title: 'Expiry',
        description: 'A sufficiently long description '.repeat(10),
        type: 'string',
      },
    },
    required: ['expiry'],
  });

  assert.equal('$schema' in schema, false);
  assert.equal('title' in schema, false);
  assert.equal(schema.type, 'object');
  assert.deepEqual(schema.required, ['expiry']);
  assert.ok(schema.description.length <= 96);
});

test('tool compaction strips outputSchema', () => {
  const tool = compactToolDefinition({
    name: 'option_chain',
    description: 'Long description '.repeat(30),
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: 'object',
      properties: { symbol: { type: 'string' } },
      required: ['symbol'],
    },
    outputSchema: { type: 'object' },
  });

  assert.equal(tool.name, 'option_chain');
  assert.deepEqual(tool.annotations, { readOnlyHint: true });
  assert.equal('outputSchema' in tool, false);
});

test('duplicate structuredContent is removed only when equivalent', () => {
  const message = {
    result: {
      content: [{ type: 'text', text: '{"count":3}' }],
      structuredContent: { count: 3 },
    },
  };
  rewriteResponse(message, {
    allowedTools: parseAllowedTools(),
    compactToolResults: true,
  });
  assert.equal('structuredContent' in message.result, false);
});
