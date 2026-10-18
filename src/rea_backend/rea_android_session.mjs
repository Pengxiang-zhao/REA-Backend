#!/usr/bin/env node
// Project-local REA MCP client. JSONL stdin keeps a loaded APK session reusable.
// Each request and complete response is saved before a compact status is printed.
import { mkdir, readdir, readFile, writeFile, appendFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createInterface } from 'node:readline';

// The Python package carries this bridge; Node dependencies remain optional.
// Override their location when invoking REA-Backend outside the checkout.
const root = process.cwd();
const modules = resolve(process.env.REA_NODE_MODULES ?? 'node_modules');
const entrypoint = resolve(process.env.REA_ENTRYPOINT ?? resolve(modules, 'rea-agents/scripts/rea.mjs'));
let Client, StdioClientTransport;
try {
  ({ Client } = await import(pathToFileURL(resolve(modules, '@modelcontextprotocol/client/dist/index.mjs')).href));
  ({ StdioClientTransport } = await import(pathToFileURL(resolve(modules, '@modelcontextprotocol/client/dist/stdio.mjs')).href));
} catch (error) {
  throw new Error('REA MCP dependencies missing. Set REA_NODE_MODULES to an installed node_modules directory; see docs/getting-started.md.', { cause: error });
}
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const output = resolve(process.argv[2] ?? `artifacts/rea/session-${stamp}`);
const requestsFile = process.argv[3] === '--requests' ? process.argv[4] : undefined;
const allowedTools = new Set([
  'inspect_android_package', 'search_android_classes', 'inspect_android_class',
  'inspect_android_method', 'trace_android_references',
]);
if (process.argv.length > 3 && (!requestsFile || process.argv.length !== 5)) {
  throw new Error('Usage: rea_android_session.mjs [output-directory] [--requests requests.jsonl]');
}
await mkdir(output, { recursive: true });
if ((await readdir(output)).length) throw new Error(`Refusing to overwrite evidence in ${output}; choose a new output directory.`);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [entrypoint, 'mcp'],
  cwd: root,
  env: Object.fromEntries(Object.entries(process.env).filter(([, v]) => v !== undefined)),
  stderr: 'pipe',
});
let stderrWrites = Promise.resolve();
transport.stderr?.on('data', chunk => {
  stderrWrites = stderrWrites.then(() => appendFile(resolve(output, 'server.stderr.log'), chunk));
});
const bridge = { name: 'rea-backend-android-evidence', version: '0.3.0' };
const client = new Client(bridge);
// Record selected invocation facts and the actual MCP handshake version. The
// ambient environment is inherited by the child but is never persisted here.
const metadata = {
  schema_version: 1, bridge, started_at: new Date().toISOString(),
  invocation: { command: process.execPath, args: [entrypoint, 'mcp'] },
  connection_status: 'connecting', server: null, requests: [],
};
const saveMetadata = () => writeFile(resolve(output, 'session-metadata.json'), JSON.stringify(metadata, null, 2));
const transportFailure = error => ({
  name: error instanceof Error ? error.name : 'UnknownThrownValue',
  message: error instanceof Error ? error.message : String(error),
  ...(typeof error?.code === 'string' || typeof error?.code === 'number' ? { code: error.code } : {}),
});
let input;
let sequence = 0;
await saveMetadata();
try {
  await client.connect(transport, { timeout: 30_000 });
  metadata.connection_status = 'connected';
  metadata.server = client.getServerVersion() ?? null;
  await saveMetadata();
  const catalog = await client.listTools();
  const androidTools = catalog.tools.filter(t => t.name.includes('android'));
  await writeFile(resolve(output, 'android-tools.json'), JSON.stringify(androidTools, null, 2));
  console.log(JSON.stringify({ ready: true, output, tools: androidTools.map(t => t.name) }));
  // Batch requests are read after the handshake; no stdin timing race in pipelines.
  const lines = requestsFile
    ? (await readFile(resolve(requestsFile), 'utf8')).split(/\r?\n/)
    : (input = createInterface({ input: process.stdin, terminal: false }));
  for await (const line of lines) {
    if (!line.trim()) continue;
    if (line.trim() === 'exit') break;
    const request = JSON.parse(line);
    if (!request || typeof request !== 'object' || Array.isArray(request)
        || !allowedTools.has(request.name) || !request.arguments
        || typeof request.arguments !== 'object' || Array.isArray(request.arguments)) {
      throw new Error('Expected a read-only Android analysis tool and an arguments object.');
    }
    const name = `${String(++sequence).padStart(3, '0')}-${request.name}`;
    const started = performance.now();
    await writeFile(resolve(output, `${name}.request.json`), JSON.stringify(request, null, 2));
    const requestRecord = { request_file: `${name}.request.json`, response_file: `${name}.json`,
      name: request.name, arguments: request.arguments ?? {}, status: 'pending' };
    metadata.requests.push(requestRecord);
    await saveMetadata();
    let result;
    try {
      result = await client.callTool(request, { timeout: 150_000 });
      requestRecord.status = result.isError === true ? 'mcp_error' : 'mcp_success';
    } catch (error) {
      result = { isError: true, transport_error: transportFailure(error) };
      requestRecord.status = 'transport_error';
    }
    await writeFile(resolve(output, `${name}.json`), JSON.stringify(result, null, 2));
    const seconds = (performance.now() - started) / 1000;
    await writeFile(resolve(output, `${name}.timing.json`), JSON.stringify({ seconds }, null, 2));
    requestRecord.seconds = seconds;
    requestRecord.received_is_error = result.isError ?? null;
    await saveMetadata();
    console.log(JSON.stringify({ file: `${name}.json`, seconds, status: requestRecord.status,
      isError: result.isError ?? false }));
  }
  metadata.session_status = 'requests-finished';
} catch (error) {
  metadata.session_status = 'failed';
  metadata.failure = transportFailure(error);
  throw error;
} finally {
  input?.close();
  try {
    await client.close();
    metadata.connection_status = 'closed';
  } catch (error) {
    metadata.connection_status = 'close-failed';
    metadata.close_failure = transportFailure(error);
  } finally {
    metadata.finished_at = new Date().toISOString();
    await stderrWrites;
    await saveMetadata();
  }
}
