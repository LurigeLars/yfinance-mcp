// Authenticated reverse proxy for the host-side yfinance MCP Streamable HTTP endpoint.
// Responsibilities: validate Cloudflare Access JWTs, expose only an explicit public
// tool allowlist, compact tool schemas for model context, strip client credentials,
// and enforce small request/rate limits. Node standard library only.
import http from 'node:http';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import {
  parseAllowedTools,
  checkRequest,
  rewriteResponse,
  rpcError,
} from './policy.mjs';

export function isLoopbackAddress(value) {
  const address = String(value ?? '').trim().toLowerCase();
  return address === '127.0.0.1'
    || address === '::1'
    || address === '::ffff:127.0.0.1';
}

function isLoopbackHost(value) {
  const host = String(value ?? '').trim().toLowerCase();
  return host === '127.0.0.1' || host === 'localhost' || host === '::1';
}

export function loadConfig(env = process.env) {
  const mode = String(env.GATEWAY_MODE ?? 'cloudflare').trim().toLowerCase();
  if (!['cloudflare', 'local'].includes(mode)) {
    throw new Error('GATEWAY_MODE must be cloudflare or local');
  }

  const accessTeamDomain = String(env.ACCESS_TEAM_DOMAIN ?? '').trim().toLowerCase();
  const accessAud = String(env.ACCESS_AUD ?? '').trim();
  const allowedEmails = new Set(
    String(env.ACCESS_ALLOWED_EMAILS ?? '')
      .split(',')
      .map(value => value.trim().toLowerCase())
      .filter(Boolean),
  );

  if (mode === 'cloudflare') {
    if (!accessTeamDomain) throw new Error('ACCESS_TEAM_DOMAIN is required');
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/.test(accessTeamDomain)) {
      throw new Error('ACCESS_TEAM_DOMAIN must be a single Cloudflare Access team domain');
    }
    if (!accessAud) throw new Error('ACCESS_AUD is required');
    if (allowedEmails.size === 0) throw new Error('ACCESS_ALLOWED_EMAILS must contain at least one address');
  }

  const upstreamHost = env.UPSTREAM_HOST ?? (mode === 'local' ? '127.0.0.1' : 'host.docker.internal');
  const bindHost = env.BIND_HOST ?? (mode === 'local' ? '127.0.0.1' : '0.0.0.0');
  if (mode === 'local') {
    if (!isLoopbackHost(bindHost)) throw new Error('local gateway BIND_HOST must be loopback');
    if (!isLoopbackHost(upstreamHost)) throw new Error('local gateway UPSTREAM_HOST must be loopback');
  }

  const upstreamPort = Number(env.UPSTREAM_PORT ?? 8772);
  const port = Number(env.PORT ?? (mode === 'local' ? 8773 : 8080));
  const ratePerMin = Number(env.RATE_PER_MIN ?? (mode === 'local' ? 600 : 120));
  const maxBodyBytes = Number(env.MAX_BODY_BYTES ?? (2 * 1024 * 1024));

  for (const [name, value] of [
    ['UPSTREAM_PORT', upstreamPort],
    ['PORT', port],
    ['RATE_PER_MIN', ratePerMin],
    ['MAX_BODY_BYTES', maxBodyBytes],
  ]) {
    if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`);
  }

  return {
    mode,
    accessTeamDomain,
    accessAud,
    allowedEmails,
    allowedTools: parseAllowedTools(env.ALLOWED_TOOLS),
    accessIssuer: accessTeamDomain ? `https://${accessTeamDomain}` : null,
    bindHost,
    upstreamHost,
    upstreamPort,
    upstreamPath: env.UPSTREAM_PATH ?? '/mcp',
    upstreamHostHeader: env.UPSTREAM_HOST_HEADER ?? 'localhost',
    port,
    ratePerMin,
    maxBodyBytes,
  };
}

export function isAllowedPath(url) {
  try {
    return new URL(url ?? '/', 'http://gateway.invalid').pathname === '/mcp';
  } catch {
    return false;
  }
}

export function buildUpstreamHeaders(headers, config, bodyLength = null) {
  const out = { ...headers, host: `${config.upstreamHostHeader}:${config.upstreamPort}` };

  for (const name of [
    'authorization',
    'cookie',
    'x-securitytoken',
    'cf-access-jwt-assertion',
    'cf-authorization-token',
    'cf-connecting-ip',
    'cf-ipcountry',
    'cf-ray',
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-proto',
    'origin',
    'referer',
    'content-length',
  ]) {
    delete out[name];
  }

  if (bodyLength !== null) out['content-length'] = String(bodyLength);
  return out;
}

function b64json(segment) {
  return JSON.parse(Buffer.from(segment, 'base64url').toString('utf8'));
}

export function createAccessVerifier(config, fetchImpl = fetch) {
  const cache = { keys: new Map(), fetchedAt: 0 };

  async function accessKey(kid) {
    const now = Date.now();
    const stale = cache.fetchedAt === 0 || now - cache.fetchedAt > 3_600_000;
    const missingAndRefreshable = !cache.keys.has(kid) && (cache.fetchedAt === 0 || now - cache.fetchedAt > 30_000);

    if (stale || missingAndRefreshable) {
      // ACCESS_TEAM_DOMAIN is constrained to one *.cloudflareaccess.com team label.
      // codeql[js/request-forgery]
      const response = await fetchImpl(`${config.accessIssuer}/cdn-cgi/access/certs`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(`certs HTTP ${response.status}`);
      const { keys = [] } = await response.json();
      cache.keys = new Map(
        keys.map(key => [key.kid, crypto.createPublicKey({ key, format: 'jwk' })]),
      );
      cache.fetchedAt = now;
    }

    return cache.keys.get(kid);
  }

  return async token => {
    const parts = String(token ?? '').split('.');
    if (parts.length !== 3) return { ok: false, reason: 'missing token' };

    try {
      const header = b64json(parts[0]);
      const claims = b64json(parts[1]);

      if (header.alg !== 'RS256') return { ok: false, reason: `alg ${header.alg}` };
      if (!header.kid) return { ok: false, reason: 'missing kid' };

      const key = await accessKey(header.kid);
      if (!key) return { ok: false, reason: 'unknown kid' };

      const valid = crypto.verify(
        'RSA-SHA256',
        Buffer.from(`${parts[0]}.${parts[1]}`),
        key,
        Buffer.from(parts[2], 'base64url'),
      );
      if (!valid) return { ok: false, reason: 'bad signature' };

      const now = Date.now() / 1000;
      const audiences = [claims.aud].flat();
      if (!audiences.includes(config.accessAud)) return { ok: false, reason: 'wrong audience' };
      if (claims.iss !== config.accessIssuer) return { ok: false, reason: 'wrong issuer' };
      if (typeof claims.exp !== 'number' || claims.exp < now - 30) return { ok: false, reason: 'expired' };
      if (typeof claims.nbf === 'number' && claims.nbf > now + 30) return { ok: false, reason: 'not yet valid' };

      const email = String(claims.email ?? '').toLowerCase();
      if (!config.allowedEmails.has(email)) {
        return { ok: false, reason: `email not allowed: ${email || '(none)'}` };
      }

      return { ok: true, email };
    } catch (error) {
      return { ok: false, reason: `verify error: ${error.message}` };
    }
  };
}

function send(res, status, body = '') {
  res.writeHead(status, {
    'content-type': 'text/plain; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(body);
}

function sendJson(res, obj) {
  res.writeHead(200, {
    'content-type': 'application/json',
    'cache-control': 'no-store',
  });
  res.end(JSON.stringify(obj));
}

async function readBody(req, maxBodyBytes) {
  const chunks = [];
  let bytes = 0;

  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += buffer.length;
    if (bytes > maxBodyBytes) throw Object.assign(new Error('request body too large'), { status: 413 });
    chunks.push(buffer);
  }

  return bytes ? Buffer.concat(chunks) : null;
}

function rewriteJsonText(text, ctx) {
  try {
    const parsed = JSON.parse(text);
    const rewritten = Array.isArray(parsed)
      ? parsed.map(message => rewriteResponse(message, ctx))
      : rewriteResponse(parsed, ctx);
    return JSON.stringify(rewritten);
  } catch {
    return text;
  }
}

function rewriteSseLine(line, ctx) {
  if (!line.startsWith('data:')) return line;
  const raw = line.slice(5).trimStart();
  const rewritten = rewriteJsonText(raw, ctx);
  return rewritten === raw ? line : `data: ${rewritten}`;
}

function forward(req, res, body, config, ctx = null) {
  const headers = buildUpstreamHeaders(req.headers, config, body ? body.length : null);

  const upstream = http.request(
    {
      host: config.upstreamHost,
      port: config.upstreamPort,
      method: req.method,
      path: config.upstreamPath,
      headers,
    },
    upstreamResponse => {
      if (!ctx) {
        res.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
        upstreamResponse.pipe(res);
        return;
      }

      const responseHeaders = { ...upstreamResponse.headers };
      delete responseHeaders['content-length'];

      if ((upstreamResponse.headers['content-type'] ?? '').includes('text/event-stream')) {
        res.writeHead(upstreamResponse.statusCode ?? 502, responseHeaders);
        let pending = '';
        upstreamResponse.setEncoding('utf8');
        upstreamResponse.on('data', chunk => {
          pending += chunk;
          const lines = pending.split('\n');
          pending = lines.pop();
          if (lines.length) {
            res.write(lines.map(line => rewriteSseLine(line, ctx)).join('\n') + '\n');
          }
        });
        upstreamResponse.on('end', () => {
          res.end(pending ? rewriteSseLine(pending, ctx) : undefined);
        });
        return;
      }

      const chunks = [];
      upstreamResponse.on('data', chunk => chunks.push(chunk));
      upstreamResponse.on('end', () => {
        const out = Buffer.from(rewriteJsonText(Buffer.concat(chunks).toString('utf8'), ctx));
        delete responseHeaders['transfer-encoding'];
        responseHeaders['content-length'] = String(out.length);
        res.writeHead(upstreamResponse.statusCode ?? 502, responseHeaders);
        res.end(out);
      });
    },
  );

  upstream.on('error', error => {
    console.warn('upstream error', JSON.stringify(String(error.code ?? error.message)));
    if (!res.headersSent) send(res, 502, 'upstream unavailable');
    else res.destroy();
  });

  res.on('close', () => {
    if (!res.writableFinished) upstream.destroy();
  });

  upstream.end(body ?? undefined);
}

export function createGatewayServer(env = process.env, dependencies = {}) {
  const config = loadConfig(env);
  const verifyAccessJwt = config.mode === 'cloudflare'
    ? createAccessVerifier(config, dependencies.fetch ?? fetch)
    : null;
  const windows = new Map();

  function rateLimited(key) {
    const now = Date.now();
    const current = windows.get(key);
    if (!current || now - current.start >= 60_000) {
      windows.set(key, { start: now, count: 1 });
      return false;
    }
    current.count += 1;
    return current.count > config.ratePerMin;
  }

  const cleanup = setInterval(() => {
    const now = Date.now();
    for (const [key, window] of windows) {
      if (now - window.start >= 60_000) windows.delete(key);
    }
  }, 60_000);
  cleanup.unref();

  return http.createServer(async (req, res) => {
    try {
      if (!isAllowedPath(req.url)) return send(res, 404);
      if (!['GET', 'POST', 'DELETE'].includes(req.method ?? '')) {
        res.setHeader('allow', 'GET, POST, DELETE');
        return send(res, 405, 'method not allowed');
      }

      let identity;
      if (config.mode === 'local') {
        if (!isLoopbackAddress(req.socket.remoteAddress)) {
          console.warn('local gateway denied non-loopback client');
          return send(res, 403, 'forbidden');
        }
        identity = { ok: true, email: 'local' };
      } else {
        identity = await verifyAccessJwt(req.headers['cf-access-jwt-assertion']);
        if (!identity.ok) {
          console.warn('access denied');
          return send(res, 403, 'forbidden');
        }
      }

      if (rateLimited(identity.email)) return send(res, 429, 'rate limited');

      const body = req.method === 'POST' ? await readBody(req, config.maxBodyBytes) : null;
      let ctx = null;

      if (body) {
        let messages;
        try {
          messages = [JSON.parse(body.toString('utf8'))].flat();
        } catch {
          return send(res, 400, 'invalid json');
        }

        for (const message of messages) {
          const verdict = checkRequest(message, config.allowedTools);
          if (verdict.error) {
            console.warn(`blocked tool ${message?.params?.name}`);
            return sendJson(res, rpcError(message.id, verdict.error));
          }

          if (
            message?.method === 'tools/list'
            || message?.method === 'initialize'
            || message?.method === 'tools/call'
          ) {
            ctx = { allowedTools: config.allowedTools, compactToolResults: true };
          }
        }
      }

      console.log(`${new Date().toISOString()} authenticated ${req.method} /mcp`);
      forward(req, res, body, config, ctx);
    } catch (error) {
      const status = Number(error?.status) || 500;
      if (status >= 500) console.warn(error?.stack ?? error);
      send(res, status, status === 413 ? 'request body too large' : 'gateway error');
    }
  });
}

export async function startGateway(env = process.env) {
  const config = loadConfig(env);
  const server = createGatewayServer(env);
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(config.port, config.bindHost, resolve);
  });
  const auth = config.mode === 'cloudflare' ? 'Access JWT required' : 'loopback-only';
  console.log(`gateway listening on ${config.bindHost}:${config.port}; ${auth}; upstream ${config.upstreamHost}:${config.upstreamPort}${config.upstreamPath}; tools ${config.allowedTools.size}`);
  return server;
}

const invokedDirectly = process.argv[1]
  && import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  startGateway().catch(error => {
    console.error(error?.stack ?? error);
    process.exit(1);
  });
}
