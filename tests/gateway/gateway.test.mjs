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
  const upstream = http.createServer(async (req, res) => {
    upstreamCalls += 1;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    const response = request.method === 'tools/list'
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
  assert.equal(upstreamCalls, 1);

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
  assert.equal(upstreamCalls, 1);
});
