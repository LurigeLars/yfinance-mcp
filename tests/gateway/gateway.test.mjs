import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import test from 'node:test';

import {
  buildUpstreamHeaders,
  createAccessVerifier,
  createGatewayServer,
  isAllowedPath,
  loadConfig,
} from '../../public/gateway/gateway.mjs';

const validEnv = {
  ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com',
  ACCESS_AUD: 'aud-123',
  ACCESS_ALLOWED_EMAILS: 'user@example.com',
};

test('gateway fails closed without Access configuration', () => {
  assert.throws(() => loadConfig({}), /ACCESS_TEAM_DOMAIN/);
  assert.throws(
    () => loadConfig({ ACCESS_TEAM_DOMAIN: 'example.cloudflareaccess.com' }),
    /ACCESS_AUD/,
  );
});

test('gateway uses the dedicated yfinance upstream', () => {
  const config = loadConfig(validEnv);
  assert.equal(config.upstreamPort, 8772);
  assert.equal(config.upstreamPath, '/mcp');
  assert.equal(config.port, 8080);
});

test('only the MCP path is accepted', () => {
  assert.equal(isAllowedPath('/mcp'), true);
  assert.equal(isAllowedPath('/mcp?session=1'), true);
  assert.equal(isAllowedPath('/'), false);
  assert.equal(isAllowedPath('/mcp/extra'), false);
});

test('client and Cloudflare credentials are stripped upstream', () => {
  const config = loadConfig(validEnv);
  const headers = buildUpstreamHeaders({
    authorization: 'Bearer secret',
    cookie: 'session=secret',
    'cf-access-jwt-assertion': 'jwt',
    'cf-authorization-token': 'token',
    'x-securitytoken': 'attacker',
    'mcp-session-id': 'keep-me',
    accept: 'application/json',
  }, config, 12);

  for (const name of [
    'authorization',
    'cookie',
    'cf-access-jwt-assertion',
    'cf-authorization-token',
    'x-securitytoken',
  ]) {
    assert.equal(name in headers, false, name);
  }
  assert.equal(headers.host, 'localhost:8772');
  assert.equal(headers['mcp-session-id'], 'keep-me');
});

function makeJwt(privateKey, kid, claims) {
  const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid }))
    .toString('base64url');
  const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
  const data = `${header}.${payload}`;
  const signature = crypto.sign('RSA-SHA256', Buffer.from(data), privateKey)
    .toString('base64url');
  return `${data}.${signature}`;
}

test('a failing certs endpoint is fetched at most once per 30 seconds', async () => {
  let calls = 0;
  const fetchImpl = async () => { calls += 1; return { ok: false, status: 503 }; };
  const verify = createAccessVerifier(loadConfig(validEnv), fetchImpl);
  const { privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const token = makeJwt(privateKey, 'k', { aud: ['aud-123'] });
  for (let i = 0; i < 5; i++) assert.equal((await verify(token)).ok, false);
  assert.equal(calls, 1);
});

test('Access verifier checks signature, audience, issuer and allowed email', async () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const kid = 'test-key';
  const jwk = publicKey.export({ format: 'jwk' });
  Object.assign(jwk, { kid, alg: 'RS256', use: 'sig' });

  const fetchImpl = async () => ({ ok: true, json: async () => ({ keys: [jwk] }) });
  const verify = createAccessVerifier(loadConfig(validEnv), fetchImpl);
  const now = Math.floor(Date.now() / 1000);
  const base = {
    aud: ['aud-123'],
    iss: 'https://example.cloudflareaccess.com',
    email: 'USER@example.com',
    exp: now + 300,
  };

  assert.deepEqual(
    await verify(makeJwt(privateKey, kid, base)),
    { ok: true, email: 'user@example.com' },
  );
  assert.equal(
    (await verify(makeJwt(privateKey, kid, { ...base, aud: ['wrong'] }))).ok,
    false,
  );
  assert.equal(
    (await verify(makeJwt(privateKey, kid, { ...base, email: 'other@example.com' }))).ok,
    false,
  );
});

test('gateway filters tools and blocks unknown calls before upstream', async t => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const kid = 'e2e-key';
  const jwk = publicKey.export({ format: 'jwk' });
  Object.assign(jwk, { kid, alg: 'RS256', use: 'sig' });

  let upstreamCalls = 0;
  const received = [];
  const upstream = http.createServer(async (req, res) => {
    upstreamCalls += 1;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    received.push({ request, headers: req.headers });
    const response = request.method === 'server/discover'
      ? { jsonrpc: '2.0', id: request.id, result: {
          supportedVersions: ['2026-07-28'], capabilities: { tools: {} },
          instructions: 'Upstream instructions',
        } }
      : request.method === 'tools/list'
      ? {
          jsonrpc: '2.0',
          id: request.id,
          result: {
            tools: [
              {
                name: 'option_chain',
                description: 'Allowed '.repeat(40),
                inputSchema: { type: 'object' },
                outputSchema: { type: 'object' },
              },
              {
                name: 'not_public',
                description: 'Blocked',
                inputSchema: { type: 'object' },
              },
            ],
          },
        }
      : { jsonrpc: '2.0', id: request.id, result: {} };
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(response));
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  t.after(() => upstream.close());

  const fetchImpl = async () => ({ ok: true, json: async () => ({ keys: [jwk] }) });
  const gatewayServer = createGatewayServer({
    ...validEnv,
    UPSTREAM_HOST: '127.0.0.1',
    UPSTREAM_PORT: String(upstream.address().port),
  }, { fetch: fetchImpl });
  await new Promise(resolve => gatewayServer.listen(0, '127.0.0.1', resolve));
  t.after(() => gatewayServer.close());

  const now = Math.floor(Date.now() / 1000);
  const token = makeJwt(privateKey, kid, {
    aud: ['aud-123'],
    iss: 'https://example.cloudflareaccess.com',
    email: 'user@example.com',
    exp: now + 300,
  });
  const url = `http://127.0.0.1:${gatewayServer.address().port}/mcp`;

  const modernMeta = { 'io.modelcontextprotocol/protocolVersion': '2026-07-28' };
  const modernHeaders = {
    'content-type': 'application/json',
    'cf-access-jwt-assertion': token,
    'mcp-protocol-version': '2026-07-28',
  };
  const discover = await fetch(url, {
    method: 'POST',
    headers: { ...modernHeaders, 'mcp-method': 'server/discover' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 0, method: 'server/discover', params: { _meta: modernMeta },
    }),
  });
  const discovered = await discover.json();
  assert.deepEqual(discovered.result.supportedVersions, ['2026-07-28']);
  assert.notEqual(discovered.result.instructions, 'Upstream instructions');
  assert.ok(discovered.result.instructions);
  assert.deepEqual(received[0].request.params._meta, modernMeta);
  assert.equal(received[0].headers['mcp-method'], 'server/discover');
  assert.equal(received[0].headers['mcp-protocol-version'], '2026-07-28');
  assert.equal(received[0].headers['mcp-session-id'], undefined);
  assert.equal(received[0].headers['cf-access-jwt-assertion'], undefined);

  const listed = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'cf-access-jwt-assertion': token,
    },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
  });
  const listedBody = await listed.json();
  assert.deepEqual(listedBody.result.tools.map(tool => tool.name), ['option_chain']);
  assert.equal('outputSchema' in listedBody.result.tools[0], false);
  assert.equal(upstreamCalls, 2);

  const blocked = await fetch(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'cf-access-jwt-assertion': token,
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 2,
      method: 'tools/call',
      params: { name: 'not_public', arguments: {} },
    }),
  });
  const blockedBody = await blocked.json();
  assert.equal(blockedBody.error.code, -32601);
  assert.equal(upstreamCalls, 2);
  const modernBlocked = await fetch(url, {
    method: 'POST',
    headers: { ...modernHeaders, 'mcp-method': 'tools/call', 'mcp-name': 'not_public' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 3, method: 'tools/call',
      params: { name: 'not_public', arguments: {}, _meta: modernMeta },
    }),
  });
  assert.equal((await modernBlocked.json()).error.code, -32601);
  assert.equal(upstreamCalls, 2);
});


test('concurrent cold Access verifications share one certificate fetch', async () => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const kid = 'shared-key';
  const jwk = { ...publicKey.export({ format: 'jwk' }), kid };
  const claims = { aud: ['aud-123'], iss: 'https://example.cloudflareaccess.com',
    email: 'user@example.com', exp: Math.floor(Date.now() / 1000) + 300 };
  const token = makeJwt(privateKey, kid, claims);
  let calls = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const verify = createAccessVerifier(loadConfig(validEnv), async () => {
    calls += 1;
    await gate;
    return { ok: true, json: async () => ({ keys: [jwk] }) };
  });
  const pending = Array.from({ length: 8 }, () => verify(token));
  assert.equal(calls, 1);
  release();
  assert.ok((await Promise.all(pending)).every(result => result.ok));
  assert.equal(calls, 1);
});

test('failed Access refresh is throttled, expired keys are denied, and recovery works', async t => {
  const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const kid = 'test-key';
  const jwk = { ...publicKey.export({ format: 'jwk' }), kid };
  let now = Date.now();
  t.mock.method(Date, 'now', () => now);
  const token = makeJwt(privateKey, kid, { aud: ['aud-123'],
    iss: 'https://example.cloudflareaccess.com', email: 'user@example.com',
    exp: Math.floor(now / 1000) + 7200 });
  let calls = 0;
  let unavailable = false;
  const verify = createAccessVerifier(loadConfig(validEnv), async () => {
    calls += 1;
    return unavailable ? { ok: false, status: 503 }
      : { ok: true, json: async () => ({ keys: [jwk] }) };
  });
  assert.equal((await verify(token)).ok, true);
  now += 3_600_001;
  unavailable = true;
  assert.equal((await verify(token)).ok, false);
  assert.equal((await verify(token)).ok, false);
  assert.equal(calls, 2);
  now += 30_000;
  unavailable = false;
  assert.equal((await verify(token)).ok, true);
  assert.equal(calls, 3);
});
