import { closeSync, constants, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
import path from "node:path"

// This state is intentionally limited to a timestamp and a one-time marker.
const delay = 48 * 60 * 60 * 1000

function stateDir(pluginDir: string): string {
  const root = path.resolve(pluginDir, "..", "..")
  const rootStat = lstatSync(root)
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) throw new Error("Unsafe OpenCode config directory")
  let current = root
  for (const part of ["sparseread", "onboarding"]) {
    current = path.join(current, part)
    try { mkdirSync(current, { mode: 0o700 }) } catch (error: any) { if (error?.code !== "EEXIST") throw error }
    const stat = lstatSync(current)
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("Unsafe onboarding state directory")
  }
  return current
}

function readStateFile(file: string, maxBytes = 1024): string {
  const before = lstatSync(file)
  if (!before.isFile() || before.isSymbolicLink()) throw new Error("Invalid onboarding state")
  const fd = openSync(file, constants.O_RDONLY | (constants.O_NONBLOCK ?? 0) | (constants.O_NOFOLLOW ?? 0))
  try {
    const stat = fstatSync(fd)
    if (!stat.isFile() || stat.size > maxBytes) throw new Error("Invalid onboarding state")
    return readFileSync(fd, "utf8")
  } finally { closeSync(fd) }
}

function exclusiveFile(file: string, content: string): boolean {
  let fd: number
  try { fd = openSync(file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0), 0o600) }
  catch (error: any) { if (error?.code === "EEXIST") return false; throw error }
  try { writeFileSync(fd, content, "utf8") } finally { closeSync(fd) }
  return true
}

export function recordEvidence(pluginDir: string, now = Date.now()): void {
  try { exclusiveFile(path.join(stateDir(pluginDir), "first-use.json"), JSON.stringify({ firstUse: now })) } catch { /* reading must still work */ }
}

export function claimSuggestion(pluginDir: string, now = Date.now()): (() => void) | undefined {
  try {
    const root = path.resolve(pluginDir, "..", "..")
    const config = JSON.parse(readStateFile(path.join(root, "sparseread.json"), 1024 * 1024))
    if (config.policy !== "advisory") return undefined
    const dir = stateDir(pluginDir)
    const state = JSON.parse(readStateFile(path.join(dir, "first-use.json")))
    if (!Number.isFinite(state.firstUse) || state.firstUse < 0 || now - state.firstUse < delay) return undefined
    const marker = path.join(dir, "suggested")
    if (!exclusiveFile(marker, "shown\n")) return undefined
    return () => { try { unlinkSync(marker) } catch { /* best effort */ } }
  } catch { return undefined }
}

export function isEvidence(result: unknown): boolean {
  if (!result || typeof result !== "object") return false
  if ((result as any).error) return false
  const pack = (result as any).evidence_pack
  if (!pack || typeof pack !== "object" || pack.error || pack.sro_guard || pack.adapter_guard || pack.next_action?.guard) return false
  return Array.isArray(pack.evidence) && pack.evidence.some((item: any) => typeof item?.text === "string" && item.text.trim().length > 0)
}
