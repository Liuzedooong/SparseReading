import readline from "node:readline"
import fs from "node:fs"
const log = process.argv[2]
for await (const line of readline.createInterface({ input: process.stdin })) {
  const req = JSON.parse(line)
  if (log) fs.appendFileSync(log, JSON.stringify({ ...req, sawSecret: !!process.env.SRO_FAKE_SECRET }) + "\n")
  if (req.method === "shutdown") process.exit(0)
  if (req.method === "hang") continue
  if (req.method === "crash") process.exit(7)
  if (req.method === "malformed") { process.stdout.write("{invalid}\n"); continue }
  let result = {}
  if (req.method === "version") result = { protocol_version: "1.0" }
  if (req.method === "source_manifest") {
    const target = req.params.target?.path || "/tmp/example"
    result = target.endsWith("collection") ? { complete: true, kind: "collection", root: target, paths: [{ path: target, canonical_path: target }, { path: `${target}/blocked.txt`, canonical_path: `${target}/blocked.txt` }], manifest_token: "token" } : { complete: true, paths: [{ path: target, canonical_path: target }], manifest_token: "token" }
  }
  if (req.method === "decide") result = { opencode_gate: { block_native_read: true } }
  if (req.method === "preview") result = { artifact_id: "test" }
  process.stdout.write(JSON.stringify({ id: req.id, ok: true, result }) + "\n")
}
