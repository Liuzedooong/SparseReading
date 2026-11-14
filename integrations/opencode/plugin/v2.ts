import * as Plugin from "@opencode/plugin/promise/plugin"
import { closeSync, constants, existsSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, statSync, unlinkSync, writeFileSync } from "node:fs"
import { randomUUID } from "node:crypto"
import path from "node:path"
import { SparseReadBridge } from "./.sparseread-transport/transport.js"

type Obj = Record<string, any>
const object = (x: unknown): x is Obj => typeof x === "object" && x !== null && !Array.isArray(x)
const str = { type: "string" }
const target = { type: "object", properties: { path: str, artifact_id: str }, anyOf: [{ required: ["path"] }, { required: ["artifact_id"] }] }
const episode = { type: "object", properties: { relation: { type: "string", enum: ["new", "continue", "switch", "unknown"] }, goal: { type: "string", enum: ["selective_read", "cross_file_evidence", "structured_compute", "edit_or_execute", "full_fidelity", "unknown"] }, coverage: { type: "string", enum: ["selective", "exhaustive", "unknown"] }, summary: str } }
const hint = { type: "object", additionalProperties: true, properties: { goal: str, needles: { type: "array", items: str }, want: { type: "string", enum: ["fact", "count", "verbatim", "table", "schema", "list"] }, scope: { type: "string", enum: ["new", "narrow", "expand", "verify"] }, artifact: str, type_hint: { type: "string", enum: ["auto", "pdf", "text", "csv", "xlsx", "json", "yaml", "xml", "mixed", "collection"] }, must_keep: { type: "array", items: str }, slots: { type: "array", items: { type: "object", properties: { id: str, question: str }, required: ["id", "question"] } } } }
const schemas: Record<string, Obj> = {
  preview: { type: "object", properties: { path: str, artifact_id: str, target, episode_hint: episode }, anyOf: [{ required: ["path"] }, { required: ["artifact_id"] }, { required: ["target"] }] },
  read: { type: "object", properties: { target, mode: { type: "string", enum: ["scout", "focus", "collect", "refine", "verify"] }, hint, episode_hint: episode }, required: ["target", "mode", "hint"] },
  raw: { type: "object", properties: { raw_ref: str, range: { type: "object", additionalProperties: true }, selector: str }, required: ["raw_ref"] },
  card: { type: "object", properties: { path: str }, required: ["path"] },
  trace: { type: "object", properties: {} },
}
const descriptions: Record<string, string> = {
  preview: "Start a SparseRead episode by previewing a supported document, including card metadata and raw reference.",
  read: "Read targeted evidence from a source path or preview artifact using scout, focus, collect, refine, or verify.",
  raw: "Retrieve original content behind a raw_ref when preview is insufficient.",
  card: "Return a SparseRead FileCard for a source path.",
  trace: "Return SparseRead and native tool trace for this session.",
}
const instruction = "SparseRead is available for long documents and selective evidence work. Start with sro_preview, then use sro_read for targeted evidence when needed. Native tools remain appropriate for small files, source editing, execution, and exact computation."
const canonical = (p: string) => { try { return realpathSync.native(p) } catch { return path.resolve(p) } }
const within = (root: string, file: string) => { const r = path.relative(root, file); return r === "" || (!r.startsWith(`..${path.sep}`) && r !== ".." && !path.isAbsolute(r)) }
const contextFor = (c: any) => {
  if (!c.sessionID || !c.messageID || !c.id) throw new Error("SparseRead requires session, message and tool call IDs")
  return { conversation_id: String(c.sessionID), turn_id: String(c.messageID), message_id: String(c.messageID), tool_call_id: String(c.id) }
}
function config(root: string, options: Obj): Obj {
  let disk: Obj = {}
  const file = path.join(root, ".opencode", "sparseread.json")
  if (existsSync(file)) { const parsed = JSON.parse(readFileSync(file, "utf8")); if (!object(parsed)) throw new Error("Invalid SparseRead config"); disk = parsed }
  return { ...disk, ...options }
}
function prefix(value: unknown, python: string): string[] {
  if (Array.isArray(value) && value.length && value.every(v => typeof v === "string")) return value
  if (typeof value === "string" && value.trim()) {
    if (value.trim().startsWith("[")) { const parsed = JSON.parse(value); if (!Array.isArray(parsed) || !parsed.length || parsed.some(v => typeof v !== "string")) throw new Error("Invalid bridge command"); return parsed }
    return value.trim().split(/\s+/)
  }
  return [python]
}

export default Plugin.define({
  id: "sparseread",
  async setup(ctx) {
    const sessions = new Map<string, { root: string; bridge: SparseReadBridge; policy: string; events: Obj[]; lifecycle: Set<string> }>()
    const pending = new Map<string, Promise<Awaited<ReturnType<typeof createRuntime>>>>()
    const registrations: Array<{ dispose(): Promise<void> }> = []
    const reminders = new Map<string, string>()
    const abort = new AbortController()
    function removeReminder(id: string) {
      const file = reminders.get(id)
      reminders.delete(id)
      if (file) try { unlinkSync(file) } catch { /* already removed */ }
    }
    function createReminder(root: string, message: string) {
      let dir = root
      for (const part of [".opencode", ".sparseread", "reminders"]) {
        dir = path.join(dir, part)
        try { mkdirSync(dir, { mode: 0o700 }) } catch (error: any) { if (error?.code !== "EEXIST") throw error }
        const stat = lstatSync(dir)
        if (!stat.isDirectory() || stat.isSymbolicLink() || !within(root, canonical(dir))) throw new Error("Unsafe reminder directory")
      }
      const file = path.join(dir, `${randomUUID()}.txt`)
      const fd = openSync(file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0), 0o600)
      try { writeFileSync(fd, message, "utf8") } finally { closeSync(fd) }
      return file
    }
    async function createRuntime(c: any) {
      if (!c.sessionID) throw new Error("SparseRead requires a session ID")
      const id = String(c.sessionID)
      const session: any = await ctx.session.get({ sessionID: c.sessionID } as any)
      const location = session?.location ?? session?.data?.location
      if (!location || typeof location.directory !== "string" || location.workspaceID) throw new Error("SparseRead local bridge cannot access this remote or unknown workspace; use native tools")
      const root = canonical(location.directory)
      const previous = sessions.get(id)
      if (previous?.root === root) return previous
      if (previous) { previous.bridge.shutdown(); sessions.delete(id) }
      const settings = config(root, ctx.options as Obj)
      const python = String(settings.python ?? process.env.SPARSEREAD_PYTHON ?? "python3")
      const cmd = prefix(settings.bridgeCommand ?? process.env.SPARSEREAD_BRIDGE_COMMAND, python)
      const bridge = new SparseReadBridge(cmd[0], [...cmd.slice(1), "-m", String(settings.bridgeModule ?? "sparseread_opencode.bridge"), "--workspace", root, "--mode", String(settings.mode ?? process.env.SPARSEREAD_MODE ?? "auto")], String(settings.projectRoot ?? root), true)
      const value = { root, bridge, policy: String(settings.policy ?? process.env.SPARSEREAD_POLICY ?? "observe"), events: [] as Obj[], lifecycle: new Set<string>() }
      sessions.set(id, value)
      return value
    }
    async function runtime(c: any) {
      if (!c.sessionID) throw new Error("SparseRead requires a session ID")
      const id = String(c.sessionID)
      const existing = pending.get(id)
      if (existing) return existing
      const task = createRuntime(c)
      pending.set(id, task)
      try { return await task } finally { pending.delete(id) }
    }
    function normalize(args: Obj, root: string): Obj {
      const copy = { ...args }
      if (typeof copy.path === "string") copy.path = path.resolve(root, copy.path)
      if (object(copy.target) && typeof copy.target.path === "string") copy.target = { ...copy.target, path: path.resolve(root, copy.target.path) }
      return copy
    }
    async function authorize(rt: Awaited<ReturnType<typeof runtime>>, args: Obj, c: any): Promise<string> {
      const context = contextFor(c)
      const source = args.raw_ref ? { raw_ref: args.raw_ref } : { target: args.target ?? (args.path ? { path: args.path } : { artifact_id: args.artifact_id }) }
      const origin = { sessionID: c.sessionID, agent: c.agent, source: { type: "tool" as const, messageID: String(c.messageID), id: String(c.id) } }
      const approved = new Set<string>()
      async function assertPath(file: string, directory?: boolean) {
        if (approved.has(file)) return
        if (directory === undefined) { try { directory = statSync(file).isDirectory() } catch { directory = false } }
        const isInternal = within(rt.root, file)
        const resource = (isInternal ? path.relative(rt.root, file) || "." : file).replaceAll("\\", "/")
        if (!isInternal) {
          const glob = path.join(directory ? file : path.dirname(file), "*").replaceAll("\\", "/")
          await ctx.permission.assert({ ...origin, action: "external_directory", resources: [glob], save: [glob] } as any)
        }
        await ctx.permission.assert({ ...origin, action: "read", resources: [resource], save: ["*"] } as any)
        approved.add(file)
      }
      if ("target" in source && typeof source.target?.path === "string") {
        let directory = false
        try { directory = statSync(source.target.path).isDirectory() } catch { /* host will report missing path */ }
        await assertPath(source.target.path, directory)
      }
      const manifest = await rt.bridge.request("source_manifest", { ...source, context }, c.signal)
      if (!manifest?.complete || !Array.isArray(manifest.paths) || !manifest.manifest_token) throw new Error("SparseRead cannot safely authorize this source; use native tools")
      const paths = [...new Set<string>(manifest.paths.flatMap((p: Obj) => [p.path, p.canonical_path]).filter((p: unknown): p is string => typeof p === "string"))]
      if (!paths.length) throw new Error("SparseRead source manifest is empty; use native tools")
      if (typeof manifest.root === "string") await assertPath(manifest.root, manifest.kind === "collection")
      for (const file of paths) await assertPath(file)
      return manifest.manifest_token
    }
    const execute = (method: string) => async (input: unknown, c: any) => {
      const rt = await runtime(c)
      const args = normalize(object(input) ? input : {}, rt.root)
      const context = contextFor(c)
      const token = method === "trace" ? undefined : await authorize(rt, args, c)
      const result = await rt.bridge.request(method, { ...args, context, ...(token ? { manifest_token: token } : {}) }, c.signal)
      const output = method === "trace" ? { ...result, native_events: rt.events } : result
      return { content: JSON.stringify(output), output, metadata: { sparseread: true, method } }
    }
    registrations.push(await ctx.tool.transform(editor => {
      for (const method of Object.keys(schemas)) editor.add({ name: `sro_${method}`, input: schemas[method] as any, output: { type: "object", additionalProperties: true }, description: descriptions[method], options: { codemode: false }, execute: execute(method) } as any)
      for (const name of ["read", "grep", "shell"]) editor.update(name, tool => { if (!tool.description.includes("SparseRead:")) tool.description += `\nSparseRead: ${instruction}` })
    }))
    registrations.push(await ctx.session.hook("context", async event => {
      const rt = await runtime(event).catch(() => undefined)
      if (rt && rt.policy !== "native") event.system.push({ type: "text", text: instruction })
    }))
    registrations.push(await ctx.tool.hook("execute.before", async event => {
      if (!["read", "grep", "shell"].includes(event.tool) || !object(event.input)) return
      const rt = await runtime(event).catch(() => undefined)
      if (!rt) return
      const args = event.input
      rt.events.push({ phase: "before", tool: event.tool, id: event.id, args: { ...args } }); if (rt.events.length > 200) rt.events.shift()
      await rt.bridge.request("native_event", { phase: "before", tool: event.tool, params: args, context: contextFor(event) }).catch(() => undefined)
      if (!["auto", "enforce", "block"].includes(rt.policy)) return
      if (event.tool === "read" && (args.offset !== undefined || args.limit !== undefined)) return
      let candidate: string | undefined
      if (event.tool === "read" || event.tool === "grep") candidate = typeof args.path === "string" ? args.path : undefined
      else if (typeof args.command === "string" && /\b(cat|less|more|pdftotext|grep|rg|cp|rsync)\b/.test(args.command)) candidate = args.command.match(/(?:^|\s)([./A-Za-z0-9_\-][^\s'"|;&<>]+\.(?:pdf|txt|md|csv|tsv|xlsx|json|yaml|yml|xml|log))(?=\s|$)/i)?.[1]
      if (!candidate) return
      const workdir = event.tool === "shell" && typeof args.workdir === "string" ? path.resolve(rt.root, args.workdir) : rt.root
      const absolute = path.resolve(workdir, candidate)
      let token: string
      try { token = await authorize(rt, { path: absolute }, event) } catch { return }
      const decision = await rt.bridge.request("decide", { path: absolute, context: contextFor(event), manifest_token: token }, (event as any).signal).catch(() => undefined)
      const gate = decision?.opencode_gate
      const block = event.tool === "read" ? gate?.block_native_read : event.tool === "grep" ? gate?.block_native_search : gate?.block_native_exec_dump
      if (block !== true) return
      const message = `SparseRead: call sro_preview with ${JSON.stringify({ path: absolute })}, then use sro_read for targeted evidence.\n`
      let file = ""
      if (event.tool !== "shell") {
        try {
          file = createReminder(rt.root, message)
          await ctx.permission.assert({ sessionID: event.sessionID, agent: event.agent, action: "read", resources: [path.relative(rt.root, file).replaceAll("\\", "/")], save: ["*"], source: { type: "tool", messageID: String(event.messageID), id: String(event.id) } } as any)
          reminders.set(`${event.sessionID}:${event.id}`, file)
        } catch { if (file) try { unlinkSync(file) } catch {} ; return }
      }
      if (event.tool === "read") { args.path = file; delete args.offset; delete args.limit }
      else if (event.tool === "grep") { args.path = file; args.pattern = "SparseRead"; delete args.include; delete args.limit }
      else { args.command = "printf '%s\\n' 'SparseRead: call sro_preview on the original source.'"; delete args.background; delete args.timeout }
      rt.events.push({ phase: "rewrite", tool: event.tool, id: event.id })
    }))
    registrations.push(await ctx.tool.hook("execute.after", async event => {
      if (!["read", "grep", "shell"].includes(event.tool)) return
      removeReminder(`${event.sessionID}:${event.id}`)
      const rt = await runtime(event).catch(() => undefined)
      if (!rt) return
      rt.events.push({ phase: "after", tool: event.tool, id: event.id, status: event.status }); if (rt.events.length > 200) rt.events.shift()
      await rt.bridge.request("native_event", { phase: "after", tool: event.tool, params: event.input, truncated: event.status === "completed" && event.result.metadata?.truncated === true, context: contextFor(event) }).catch(() => undefined)
      if (event.status !== "completed" || !["auto", "advisory", "enforce", "nudge"].includes(rt.policy) || !event.result.metadata?.truncated) return
      const nudge = "\n\nSparseRead may help with this truncated source; use sro_preview for targeted evidence."
      const content = event.result.content
      event.result = { ...event.result, content: typeof content === "string" ? content + nudge : [...(content ?? []), { type: "text", text: nudge }] }
    }))
    const events = (async () => { try { for await (const event of ctx.event.subscribe({ signal: abort.signal } as any)) {
      const data: any = event.data
      const id = data?.sessionID ?? data?.info?.id
      if (!id || !sessions.has(String(id))) continue
      const rt = sessions.get(String(id))!
      if (rt.lifecycle.has(String(event.id))) continue
      rt.lifecycle.add(String(event.id))
      if (rt.lifecycle.size > 500) rt.lifecycle.delete(rt.lifecycle.values().next().value!)
      if (["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"].includes(event.type)) {
        rt.events.push({ phase: "lifecycle", type: event.type, id: event.id })
        if (rt.events.length > 200) rt.events.shift()
      }
      if (event.type === "session.execution.succeeded") await rt.bridge.request("lifecycle_event", { type: "assistant_final", context: { conversation_id: String(id) } }).catch(() => undefined)
      if (event.type === "session.deleted") { await rt.bridge.request("lifecycle_event", { type: "session_end", context: { conversation_id: String(id) } }).catch(() => undefined); await rt.bridge.shutdown(); sessions.delete(String(id)); for (const key of reminders.keys()) if (key.startsWith(`${id}:`)) removeReminder(key) }
    } } catch (error) { if (!abort.signal.aborted) console.error("[sparseread] event subscription failed", error) } })()
    return async () => { abort.abort(); for (const registration of registrations.reverse()) await registration.dispose(); await Promise.all([...sessions.values()].map(rt => rt.bridge.shutdown())); sessions.clear(); for (const id of reminders.keys()) removeReminder(id); await events }
  },
})
