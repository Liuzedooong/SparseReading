import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import plugin from "../dist/v2.js"

const fixture = fileURLToPath(new URL("./bridge-fixture.mjs", import.meta.url))
test("V2 tools authorize original source and retain host results per session", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sro-v2-"))
  const log = path.join(root, "bridge.log")
  process.env.SRO_FAKE_SECRET = "must-not-inherit"
  const tools = new Map(), hooks = new Map(), permissions = [], disposed = []
  const registration = () => ({ dispose: async () => disposed.push(true) })
  const ctx = {
    options: { policy: "auto", bridgeCommand: [process.execPath, fixture, log] },
    location: { directory: "/wrong-plugin-location" },
    session: { get: async () => ({ location: { directory: root } }), hook: async (name, fn) => { hooks.set(`session.${name}`, fn); return registration() } },
    tool: { transform: async fn => { fn({ add: info => tools.set(info.name, info), update: () => {} }); return registration() }, hook: async (name, fn) => { hooks.set(name, fn); return registration() } },
    permission: { assert: async input => { permissions.push(input) } },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await plugin.setup(ctx)
  t.after(async () => { await cleanup(); delete process.env.SRO_FAKE_SECRET })
  assert.equal(tools.size, 5)
  for (const info of tools.values()) assert.equal(info.options.codemode, false)
  const context = { sessionID: "session-a", messageID: "message-a", id: "call-a", agent: "agent" }
  const result = await tools.get("sro_preview").execute({ path: "document.txt" }, context)
  assert.equal(result.output.artifact_id, "test")
  assert.equal(permissions[0].action, "read")
  assert.deepEqual(permissions[0].resources, ["document.txt"])
  assert.deepEqual(permissions[0].source, { type: "tool", messageID: "message-a", id: "call-a" })
  const bounded = { ...context, tool: "read", input: { path: "document.txt", offset: 100, limit: 1 } }
  await hooks.get("execute.before")(bounded)
  assert.equal(bounded.input.path, "document.txt")
  const before = { ...context, tool: "read", input: { path: "document.txt" } }
  await hooks.get("execute.before")(before)
  assert.match(before.input.path, /reminders/)
  const another = { ...context, id: "call-b", tool: "read", input: { path: "document-two.txt" } }
  await hooks.get("execute.before")(another)
  assert.notEqual(another.input.path, before.input.path)
  assert.equal(fs.existsSync(another.input.path), true)
  assert.equal(before.input.offset, undefined)
  assert.equal(before.input.limit, undefined)
  const after = { ...context, tool: "read", input: {}, status: "completed", result: { metadata: { truncated: true }, output: { value: 1 }, content: [{ type: "file", uri: "file:///x", mime: "image/png" }] } }
  await hooks.get("execute.after")(after)
  assert.equal(after.result.content[0].uri, "file:///x")
  assert.deepEqual(after.result.output, { value: 1 })
  assert.equal(after.result.content[1].type, "text")
  const error = { ...context, tool: "read", status: "error", error: { message: "bad" } }
  await hooks.get("execute.after")(error)
  assert.equal(error.status, "error")
  const calls = fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse)
  const preview = calls.find(x => x.method === "preview")
  assert.equal(calls.some(x => x.sawSecret), false)
  assert.equal(preview.params.path, path.join(fs.realpathSync(root), "document.txt"))
  assert.equal(preview.params.manifest_token, "token")
  assert.equal(preview.params.context.tool_call_id, "call-a")
})

test("permission denial and remote workspaces never reach the reader", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sro-deny-"))
  const log = path.join(root, "bridge.log")
  const tools = new Map()
  let remote = false
  const registration = () => ({ dispose: async () => {} })
  const ctx = {
    options: { bridgeCommand: [process.execPath, fixture, log] },
    session: { get: async () => ({ location: { directory: root, ...(remote ? { workspaceID: "remote" } : {}) } }), hook: async () => registration() },
    tool: { transform: async fn => { fn({ add: info => tools.set(info.name, info), update: () => {} }); return registration() }, hook: async () => registration() },
    permission: { assert: async () => { throw new Error("read denied") } },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await plugin.setup(ctx)
  t.after(async () => { await cleanup() })
  const c = { sessionID: "session-a", messageID: "message-a", id: "call-a", agent: "agent" }
  await assert.rejects(tools.get("sro_preview").execute({ path: "secret.txt" }, c), /read denied/)
  const calls = fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse) : []
  assert.equal(calls.some(x => x.method === "preview"), false)
  remote = true
  await assert.rejects(tools.get("sro_preview").execute({ path: "secret.txt" }, { ...c, sessionID: "remote" }), /remote or unknown workspace/)
})

test("unsafe reminder symlink leaves the native operation untouched", async t => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sro-link-")))
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "sro-outside-"))
  fs.mkdirSync(path.join(root, ".opencode", ".sparseread"), { recursive: true })
  fs.symlinkSync(outside, path.join(root, ".opencode", ".sparseread", "reminders"))
  const hooks = new Map()
  const registration = () => ({ dispose: async () => {} })
  const ctx = {
    options: { policy: "auto", bridgeCommand: [process.execPath, fixture, path.join(root, "log")] },
    session: { get: async () => ({ location: { directory: root } }), hook: async () => registration() },
    tool: { transform: async fn => { fn({ add: () => {}, update: () => {} }); return registration() }, hook: async (name, fn) => { hooks.set(name, fn); return registration() } },
    permission: { assert: async () => {} },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await plugin.setup(ctx)
  t.after(cleanup)
  const before = { sessionID: "session", messageID: "message", id: "call", agent: "agent", tool: "read", input: { path: "document.txt" } }
  await hooks.get("execute.before")(before)
  assert.equal(before.input.path, "document.txt")
  assert.deepEqual(fs.readdirSync(outside), [])
})

test("bridge recovers after malformed output, crash, and timeout", async t => {
  const { SparseReadBridge } = await import("../dist/.sparseread-transport/transport.js")
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sro-transport-"))
  const bridge = new SparseReadBridge(process.execPath, [fixture, path.join(root, "log")], root, true, 150)
  t.after(() => bridge.shutdown())
  for (const method of ["malformed", "crash", "hang"]) {
    await assert.rejects(bridge.request(method), /shut down|exited|timed out/)
    assert.equal((await bridge.request("version")).protocol_version, "1.0")
  }
})

test("collection root and every child are checked before reading", async t => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sro-collection-")))
  const log = path.join(root, "bridge.log")
  fs.mkdirSync(path.join(root, "collection"))
  const checked = [], tools = new Map()
  const registration = () => ({ dispose: async () => {} })
  const ctx = {
    options: { bridgeCommand: [process.execPath, fixture, log] },
    session: { get: async () => ({ location: { directory: root } }), hook: async () => registration() },
    tool: { transform: async fn => { fn({ add: info => tools.set(info.name, info), update: () => {} }); return registration() }, hook: async () => registration() },
    permission: { assert: async input => { checked.push(...input.resources); if (input.resources.includes("collection/blocked.txt")) throw new Error("child denied") } },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await plugin.setup(ctx)
  t.after(cleanup)
  await assert.rejects(tools.get("sro_preview").execute({ path: "collection" }, { sessionID: "s", messageID: "m", id: "c", agent: "a" }), /child denied/)
  assert.deepEqual(checked, ["collection", "collection/blocked.txt"])
  const calls = fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse)
  assert.equal(calls.some(call => call.method === "preview"), false)
})

test("global V2 ignores project commands and runs an isolated interpreter from managed directory", async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sro-global-"))
  const pluginDir = path.join(root, "config", "opencode", "plugins", "sparseread")
  const workspace = path.join(root, "workspace")
  fs.mkdirSync(pluginDir, { recursive: true })
  fs.mkdirSync(path.join(workspace, ".opencode"), { recursive: true })
  fs.cpSync(new URL("../dist/", import.meta.url), pluginDir, { recursive: true })
  fs.writeFileSync(path.join(pluginDir, "package.json"), '{"type":"module"}')
  fs.writeFileSync(path.join(pluginDir, "global.json"), '{"global":true}')
  fs.symlinkSync(fileURLToPath(new URL("../node_modules", import.meta.url)), path.join(pluginDir, "node_modules"))
  const log = path.join(root, "bridge.log"), invocation = path.join(root, "invocation")
  const executable = path.join(root, "config", "opencode", "sparseread", "runtime", "opencode", "bin", "python")
  fs.mkdirSync(path.dirname(executable), { recursive: true })
  fs.writeFileSync(executable, `#!/bin/sh\npwd > '${invocation}'\nprintf '%s\\n' "$@" >> '${invocation}'\nexec '${process.execPath}' '${fixture}' '${log}'\n`, { mode: 0o700 })
  fs.writeFileSync(path.join(root, "config", "opencode", "sparseread.json"), JSON.stringify({ bridgeCommand: ["/malicious-global-setting"], policy: "observe", mode: "auto" }))
  fs.writeFileSync(path.join(workspace, ".opencode", "sparseread.json"), JSON.stringify({ bridgeCommand: ["/malicious"], bridgeModule: "malicious", projectRoot: "/malicious" }))
  const globalPlugin = (await import(new URL(`file://${path.join(pluginDir, "v2.js")}`))).default
  const tools = new Map()
  const registration = () => ({ dispose: async () => {} })
  const ctx = {
    options: { bridgeCommand: ["/malicious-option"] },
    session: { get: async () => ({ location: { directory: workspace } }), hook: async () => registration() },
    tool: { transform: async fn => { fn({ add: info => tools.set(info.name, info), update: () => {} }); return registration() }, hook: async () => registration() },
    permission: { assert: async () => {} },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await globalPlugin.setup(ctx)
  t.after(cleanup)
  await tools.get("sro_preview").execute({ path: "data.txt" }, { sessionID: "s", messageID: "m", id: "c", agent: "a" })
  const argv = fs.readFileSync(invocation, "utf8").trim().split("\n")
  assert.equal(fs.realpathSync(argv[0]), fs.realpathSync(pluginDir))
  assert.deepEqual(argv.slice(1, 4), ["-I", "-m", "sparseread_opencode.bridge"])
  assert.equal(argv[argv.indexOf("--workspace") + 1], fs.realpathSync(workspace))
  const preview = fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse).find(x => x.method === "preview")
  assert.equal(preview.params.path, path.join(fs.realpathSync(workspace), "data.txt"))
  const managedConfig = path.join(root, "config", "opencode", "sparseread.json")
  fs.unlinkSync(managedConfig)
  await assert.rejects(tools.get("sro_preview").execute({ path: "data.txt" }, { sessionID: "missing-config", messageID: "m", id: "c", agent: "a" }), /Missing managed global SparseRead config/)
  fs.writeFileSync(managedConfig, JSON.stringify({ policy: "observe", mode: "auto" }))
  fs.unlinkSync(executable)
  await assert.rejects(tools.get("sro_preview").execute({ path: "data.txt" }, { sessionID: "missing-runtime", messageID: "m", id: "c", agent: "a" }), /Missing managed global SparseRead runtime/)
})
