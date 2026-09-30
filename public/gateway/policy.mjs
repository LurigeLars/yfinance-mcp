import fs from 'node:fs';
import { isDeepStrictEqual } from 'node:util';

export const ALL_ALLOWED_TOOLS = [
  'option_expirations',
  'option_chain',
  'option_positioning_summary',
  'option_surface_summary',
  'option_activity_summary',
  'option_greeks',
  'option_risk_map',
  'option_scenario',
].join(',');

export function parseAllowedTools(value) {
  const selected = value || ALL_ALLOWED_TOOLS;
  return new Set(selected.split(',').map(item => item.trim()).filter(Boolean));
}

export function loadInstructions() {
  try {
    return fs.readFileSync(new URL('./instructions.md', import.meta.url), 'utf8').trim() || null;
  } catch {
    return null;
  }
}

function compactText(value, maxChars) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxChars) return text;
  const firstSentence = text.match(/^.*?[.!?](?:\s|$)/)?.[0]?.trim();
  if (firstSentence && firstSentence.length <= maxChars) return firstSentence;
  return text.slice(0, Math.max(1, maxChars - 1)).trimEnd() + '…';
}

export function compactSchema(value) {
  if (Array.isArray(value)) return value.map(compactSchema);
  if (!value || typeof value !== 'object') return value;

  const entries = [];
  for (const [key, item] of Object.entries(value)) {
    if (key === '$schema' || key === 'title' || key === 'examples') continue;
    entries.push([
      key,
      key === 'description' ? compactText(item, 96) : compactSchema(item),
    ]);
  }
  return Object.fromEntries(entries);
}

export function compactToolDefinition(tool) {
  if (!tool || typeof tool !== 'object') return tool;
  const out = { ...tool };
  if (out.description) out.description = compactText(out.description, 180);
  if (out.inputSchema) out.inputSchema = compactSchema(out.inputSchema);
  delete out.outputSchema;
  return out;
}

function hasEquivalentTextAndStructuredResult(result) {
  if (!Array.isArray(result?.content) || result.content.length !== 1) return false;
  if (result?.structuredContent === undefined) return false;
  const item = result.content[0];
  if (item?.type !== 'text' || typeof item.text !== 'string') return false;

  try {
    return isDeepStrictEqual(JSON.parse(item.text), result.structuredContent);
  } catch {
    return false;
  }
}

export function rewriteResponse(message, { allowedTools, compactToolResults = false }) {
  if (!message || typeof message !== 'object') return message;

  if (compactToolResults && hasEquivalentTextAndStructuredResult(message.result)) {
    delete message.result.structuredContent;
  }

  if (message.result?.tools) {
    message.result.tools = message.result.tools
      .filter(tool => allowedTools.has(tool.name))
      .map(compactToolDefinition);
  }

  if (message.result?.serverInfo) {
    const instructions = loadInstructions();
    if (instructions) message.result.instructions = instructions;
  }

  return message;
}

export function checkRequest(message, allowedTools) {
  if (message?.method !== 'tools/call') return {};
  if (!allowedTools.has(message.params?.name)) {
    return { error: `Tool not available on the yfinance connector: ${message.params?.name}` };
  }
  return {};
}

export const rpcError = (id, message) => ({
  jsonrpc: '2.0',
  id: id ?? null,
  error: { code: -32601, message },
});
