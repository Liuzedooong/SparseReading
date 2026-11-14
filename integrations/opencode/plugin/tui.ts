import type { Plugin } from "@opencode/plugin/tui"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { claimSuggestion } from "./onboarding.js"

const pluginDir = path.dirname(fileURLToPath(import.meta.url))

const plugin: Plugin.Definition = {
  id: "sparseread",
  setup(ctx) {
    return ctx.data.on("session.tool.success", event => {
      if (event.data.metadata?.sparsereadAdvisoryEvidence !== true) return
      const release = claimSuggestion(pluginDir)
      if (!release) return
      try {
        ctx.ui.toast.show({
          title: "SparseRead",
          message: "Consider auto mode: run the installer with --platform opencode --global --sparseread-mode auto, then restart OpenCode.",
          variant: "info",
          duration: 12000,
          sessionID: event.data.sessionID,
        })
      } catch { release() }
    })
  },
}

export default plugin
