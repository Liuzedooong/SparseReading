import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"

type Json = any
const BRIDGE_PROTOCOL_VERSION = "1.0"

type BridgeRequest = {
  id: string
  method: string
  params?: Record<string, Json>
}

type BridgeResponse = {
  id: string
  ok: boolean
  result?: Json
  error?: string
}

export class SparseReadBridge {
  private process?: ChildProcessWithoutNullStreams
  private nextID = 1
  private buffer = ""
  private pending = new Map<string, { resolve: (value: Json) => void; reject: (error: Error) => void }>()
  private protocolCheck?: Promise<void>

  constructor(
    private readonly command: string,
    private readonly args: string[],
    private readonly cwd: string,
    private readonly restrictedEnv = false,
    private readonly timeoutMs = 120_000,
  ) {}

  request(method: string, params: Record<string, Json> = {}, signal?: AbortSignal): Promise<Json> {
    this.ensure()
    if (method === "version") return this.requestRaw(method, params)
    this.protocolCheck ??= this.requestRaw("version", {}).then((result) => {
      if (result?.protocol_version !== BRIDGE_PROTOCOL_VERSION) {
        throw new Error(`SparseRead bridge protocol mismatch: expected ${BRIDGE_PROTOCOL_VERSION}, got ${result?.protocol_version ?? "missing"}`)
      }
    }).catch(error => { void this.shutdown(); throw error })
    return this.protocolCheck.then(() => this.requestRaw(method, params, signal))
  }

  private requestRaw(method: string, params: Record<string, Json>, signal?: AbortSignal): Promise<Json> {
    const id = String(this.nextID++)
    const payload: BridgeRequest = { id, method, params }
    return new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(new Error("SparseRead request cancelled"))
      const finish = () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); this.pending.delete(id) }
      const abort = () => { finish(); reject(new Error("SparseRead request cancelled")); if (this.restrictedEnv && this.pending.size === 0) void this.shutdown() }
      const timer = setTimeout(() => { finish(); reject(new Error("SparseRead bridge request timed out")); void this.shutdown() }, this.timeoutMs)
      signal?.addEventListener("abort", abort, { once: true })
      this.pending.set(id, { resolve: value => { finish(); resolve(value) }, reject: error => { finish(); reject(error) } })
      this.process!.stdin.write(JSON.stringify(payload) + "\n", error => { if (error) { finish(); reject(error) } })
    })
  }

  shutdown(): Promise<void> {
    if (!this.process) return Promise.resolve()
    const child = this.process
    try {
      this.process.stdin.write(JSON.stringify({ id: String(this.nextID++), method: "shutdown", params: {} }) + "\n")
    } catch {
      // ignore shutdown races
    }
    this.process.kill()
    for (const pending of this.pending.values()) pending.reject(new Error("SparseRead bridge shut down"))
    this.process = undefined
    this.protocolCheck = undefined
    this.buffer = ""
    return new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve()
      const timer = setTimeout(() => { child.kill("SIGKILL"); resolve() }, 2000)
      child.once("close", () => { clearTimeout(timer); resolve() })
    })
  }

  private ensure() {
    if (this.process) return
    const allowed = new Set(["PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "SRO_ENABLED", "SRO_LAZY_TEXT_BYTES", "SRO_LARGE_BYTES", "SRO_STRUCTURED_LARGE_BYTES", "SRO_COLLECTION_FILES", "SRO_BENEFIT_GATE_OVERRIDE", ...["SCOUT", "FOCUS", "REFINE", "VERIFY", "COLLECT"].flatMap(mode => [`SRO_${mode}_BUDGET_CHARS`, `SRO_COLLECTION_${mode}_BUDGET_CHARS`])])
    const env = this.restrictedEnv ? Object.fromEntries(Object.entries(process.env).filter(([key]) => allowed.has(key))) : { ...process.env }
    this.process = spawn(this.command, this.args, {
      cwd: this.cwd,
      env,
      stdio: ["pipe", "pipe", "pipe"],
    })
    this.process.stdout.setEncoding("utf8")
    this.process.stdout.on("data", (chunk) => this.onData(String(chunk)))
    this.process.stderr.resume()
    const current = this.process
    const failed = (error: Error) => {
      if (this.process !== current) return
      for (const pending of this.pending.values()) pending.reject(error)
      this.process = undefined
      this.protocolCheck = undefined
      this.buffer = ""
    }
    this.process.on("error", failed)
    this.process.on("exit", (code, signal) => {
      const error = new Error(`SparseRead bridge exited code=${code ?? ""} signal=${signal ?? ""}`.trim())
      failed(error)
    })
  }

  private onData(text: string) {
    this.buffer += text
    if (this.buffer.length > 16_000_000) { void this.shutdown(); return }
    while (true) {
      const index = this.buffer.indexOf("\n")
      if (index < 0) return
      const line = this.buffer.slice(0, index).trim()
      this.buffer = this.buffer.slice(index + 1)
      if (!line) continue
      let response: BridgeResponse
      try {
        response = JSON.parse(line)
        if (!response || typeof response.id !== "string" || typeof response.ok !== "boolean") throw new Error("invalid response")
      } catch (error) {
        console.error("[sparseread bridge] invalid JSON response; restarting bridge")
        void this.shutdown()
        return
      }
      const pending = this.pending.get(response.id)
      if (!pending) continue
      this.pending.delete(response.id)
      if (response.ok) pending.resolve(response.result)
      else pending.reject(new Error(response.error || "SparseRead bridge error"))
    }
  }
}

