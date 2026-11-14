import { useState } from "react";
import CopySnippet from "./CopySnippet";
import { HarnessMark, type HarnessId } from "./HarnessMark";

type Install = {
  id: HarnessId;
  label: string;
  hint: string;
  code: string;
};

const INSTALLS: Install[] = [
  {
    id: "nanobot",
    label: "NanoBot",
    hint: "Run in your NanoBot Python environment, then call sparseread_nanobot.install(agent) before AgentLoop starts.",
    code: `uv pip install \\
  packages/sparseread-core \\
  integrations/nanobot/python`,
  },
  {
    id: "opencode",
    label: "OpenCode",
    hint: "Writes the workspace plugin, a managed Python runtime, and runs doctor.",
    code: `uv run --no-project --python 3.12 python scripts/install_sparseread.py \\
  --platform opencode \\
  --opencode-workspace /path/to/your/project \\
  --doctor`,
  },
  {
    id: "openclaw",
    label: "OpenClaw",
    hint: "Builds the OpenClaw plugin, installs it into the current profile, and runs doctor.",
    code: `uv run --no-project --python 3.12 python scripts/install_sparseread.py \\
  --platform openclaw \\
  --doctor`,
  },
  {
    id: "claude",
    label: "Claude Code",
    hint: "Merges MCP tools and per-event hooks into the workspace. Restart Claude Code after install.",
    code: `uv run --no-project --python 3.12 python scripts/install_sparseread.py \\
  --platform claude \\
  --claude-workspace /path/to/your/project \\
  --doctor`,
  },
  {
    id: "codex",
    label: "Codex",
    hint: "Installs into the project; review project and hook trust separately.",
    code: `uv run --no-project --python 3.12 python scripts/install_sparseread.py \\
  --platform codex --workspace /path/to/your/project --doctor`,
  },
  {
    id: "pi",
    label: "Pi",
    hint: "Installs a project extension; review the host trust prompt.",
    code: `uv run --no-project --python 3.12 python scripts/install_sparseread.py \\
  --platform pi --workspace /path/to/your/project --doctor`,
  },
];

export default function InstallTabs() {
  const [active, setActive] = useState<HarnessId>("nanobot");
  const current = INSTALLS.find((item) => item.id === active) ?? INSTALLS[0];

  return (
    <div className="install-tabs">
      <p className="install-switch-label">Choose a platform</p>
      <div className="install-tablist" role="tablist" aria-label="Install into a harness">
        {INSTALLS.map((item) => {
          const on = item.id === active;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`install-tab-${item.id}`}
              aria-selected={on}
              aria-controls={`install-panel-${item.id}`}
              className={on ? "on" : undefined}
              onClick={() => setActive(item.id)}
            >
              <HarnessMark id={item.id} size={18} />
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        id={`install-panel-${current.id}`}
        role="tabpanel"
        aria-labelledby={`install-tab-${current.id}`}
      >
        <CopySnippet label={current.label} code={current.code} />
        <p className="note">{current.hint}</p>
      </div>
    </div>
  );
}
