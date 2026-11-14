import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { pathToFileURL, fileURLToPath } from "node:url"
import { isEvidence, recordEvidence, claimSuggestion } from "../dist/onboarding.js"

const fixture = fileURLToPath(new URL("./bridge-fixture.mjs", import.meta.url))
const dist = fileURLToPath(new URL("../dist/", import.meta.url))
function fakeGlobal() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "sro-onboarding-"))
  const config = path.join(root, "config", "opencode")
  const plugin = path.join(config, "plugins", "sparseread")
  fs.mkdirSync(plugin, { recursive: true })
  fs.cpSync(dist, plugin, { recursive: true })
  fs.writeFileSync(path.join(plugin, "package.json"), '{"type":"module"}')
  fs.writeFileSync(path.join(plugin, "global.json"), '{"global":true}')
  fs.symlinkSync(fileURLToPath(new URL("../node_modules", import.meta.url)), path.join(plugin, "node_modules"))
  fs.writeFileSync(path.join(config, "sparseread.json"), JSON.stringify({ policy: "advisory", mode: "auto" }))
  return { root, config, plugin, state: path.join(config, "sparseread", "onboarding") }
}

test("advisory onboarding counts only successful nonempty evidence", () => {
  const yes = { evidence_pack: { error: "", evidence: [{ text: " evidence " }] } }
  assert.equal(isEvidence(yes), true)
  for (const value of [null, {}, { evidence_pack: { evidence: [] } }, { evidence_pack: { evidence: [{ text: " " }] } }, { evidence_pack: { error: "stale", evidence: [{ text: "x" }] } }, { evidence_pack: { adapter_guard: "ready", evidence: [{ text: "x" }] } }, { evidence_pack: { next_action: { guard: "ready" }, evidence: [{ text: "x" }] } }]) assert.equal(isEvidence(value), false)
})

test("one-time claim is durable and limited to advisory after 24 elapsed hours", () => {
  const { config, plugin, state } = fakeGlobal()
  recordEvidence(plugin, 1000)
  recordEvidence(plugin, 2000)
  assert.equal(JSON.parse(fs.readFileSync(path.join(state, "first-use.json"))).firstUse, 1000)
  assert.equal(fs.statSync(path.join(state, "first-use.json")).mode & 0o777, 0o600)
  assert.equal(claimSuggestion(plugin, 1000 + 86400000 - 1), undefined)
  fs.writeFileSync(path.join(config, "sparseread.json"), JSON.stringify({ policy: "auto" }))
  assert.equal(claimSuggestion(plugin, 1000 + 86400000), undefined)
  fs.writeFileSync(path.join(config, "sparseread.json"), JSON.stringify({ policy: "advisory", unrelated: "x".repeat(5000) }))
  assert.equal(typeof claimSuggestion(plugin, 1000 + 86400000), "function")
  assert.equal(fs.statSync(path.join(state, "suggested")).mode & 0o777, 0o600)
  assert.equal(claimSuggestion(plugin, 1000 + 90000000), undefined)
})

test("global live event toast and state failure leave reading intact", async t => {
  const { root, config, plugin, state } = fakeGlobal()
  const workspace = path.join(root, "workspace")
  fs.mkdirSync(workspace)
  const executable = path.join(config, "sparseread", "runtime", "opencode", "bin", "python")
  fs.mkdirSync(path.dirname(executable), { recursive: true })
  fs.writeFileSync(executable, `#!/bin/sh\nexec '${process.execPath}' '${fixture}' '${root}/bridge.log'\n`, { mode: 0o700 })
  const server = (await import(pathToFileURL(path.join(plugin, "v2.js")))).default
  const client = (await import(pathToFileURL(path.join(plugin, "tui.js")))).default
  const tools = new Map(), notifications = []
  const registration = () => ({ dispose: async () => {} })
  const ctx = {
    options: {}, session: { get: async () => ({ location: { directory: workspace } }), hook: async () => registration() },
    tool: { transform: async fn => { fn({ add: info => tools.set(info.name, info), update: () => {} }); return registration() }, hook: async () => registration() },
    permission: { assert: async () => {} },
    event: { subscribe: ({ signal }) => ({ async *[Symbol.asyncIterator]() { await new Promise(resolve => signal.addEventListener("abort", resolve, { once: true })) } }) },
  }
  const cleanup = await server.setup(ctx)
  let handler
  const off = client.setup({ data: { on: (_type, cb) => { handler = cb; return () => {} } }, ui: { toast: { show: item => notifications.push(item) } } })
  t.after(async () => { off(); await cleanup() })
  const invoke = goal => tools.get("sro_read").execute({ target: { path: "fixture.txt" }, mode: "focus", hint: { goal } }, { sessionID: "s", messageID: "m", id: "c", agent: "a" })
  for (const goal of ["empty", "error", "guard"]) assert.equal((await invoke(goal)).metadata.sparsereadAdvisoryEvidence, undefined)
  assert.equal(fs.existsSync(state), false)
  let result = await invoke("ok")
  assert.equal(result.metadata.sparsereadAdvisoryEvidence, true)
  handler({ data: { sessionID: "s", metadata: result.metadata } })
  assert.equal(notifications.length, 0)
  fs.writeFileSync(path.join(state, "first-use.json"), JSON.stringify({ firstUse: Date.now() - 86401000 }))
  result = await invoke("ok")
  handler({ data: { sessionID: "s", metadata: result.metadata } })
  assert.equal(notifications.length, 1)
  assert.match(notifications[0].message, /--sparseread-mode auto/)
  handler({ data: { sessionID: "s", metadata: result.metadata } })
  assert.equal(notifications.length, 1)
  fs.unlinkSync(path.join(state, "suggested"))
  fs.writeFileSync(path.join(config, "sparseread.json"), JSON.stringify({ policy: "auto", mode: "auto" }))
  result = await invoke("ok")
  assert.equal(result.metadata.sparsereadAdvisoryEvidence, undefined)
  handler({ data: { sessionID: "s", metadata: { sparsereadAdvisoryEvidence: true } } })
  assert.equal(notifications.length, 1)
  fs.writeFileSync(path.join(config, "sparseread.json"), JSON.stringify({ policy: "advisory", mode: "auto" }))
  fs.rmSync(state, { recursive: true })
  fs.symlinkSync(workspace, state)
  result = await invoke("ok")
  assert.equal(result.output.evidence_pack.evidence[0].text, "fixture evidence")
  assert.equal(fs.existsSync(path.join(workspace, "first-use.json")), false)
})
