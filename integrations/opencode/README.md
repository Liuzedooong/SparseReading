# OpenCode SparseRead Integration

This directory contains the OpenCode plugin, bridge adapter, and local runner
for comparing OpenCode native truncation against SparseRead.

The plugin uses the framework-neutral core in `packages/sparseread-core` and
calls `python -m sparseread_opencode.bridge` through a stdio JSONL bridge. The
source installer creates the managed runtime used by production installs; the
local runner below is benchmark-only.

## Modes

- `native_truncation`: no plugin; OpenCode default `read` / `grep` / `bash`.
- `plugin_observe`: SR tools are available and native tool calls are traced.
- `plugin_auto`: production-equivalent row. It sends `SPARSEREAD_POLICY=auto`
  to the plugin, so long text/PDF and compact high-confidence closures can be
  redirected to `sro_preview`, boundary collections can stay advisory, and
  small code/data/computation work stays native.
- `plugin_nudge`: compatibility name for the OpenCode `advisory` policy.
  Native truncation / runtime-gated large reads append a short SR hint.
- `plugin_replace_truncation_experimental`: compatibility name for the
  OpenCode `enforce` policy. Only OpenCode high-confidence broad reads are
  blocked and redirected to `sro_preview`, with `sro_read` used only when the
  preview is insufficient and targeted evidence is needed.

Only `plugin_auto` matches the recommended source-install production shape.
`plugin_nudge` and `plugin_replace_truncation_experimental` remain
compatibility/debug rows for runner comparisons.

Production tool path:

```text
sro_preview(path) -> use preview | sro_read({artifact_id}, mode, HintSpec) | sro_raw(raw_ref)
```

`sro_card -> sro_read` remains available under `SR_PROFILE=bench_protocol` and
for compatibility/debugging, but it is no longer the production first step.

The product gate is runtime-feature based. It does not branch on benchmark task
ids: long text/PDF and compact audit closures can be enforced; medium or
uncertain collections are advisory; small code/data/computation work stays
native. Command-security bundles stay SR-assisted, but use a stricter
one-collect-then-write advisory trajectory to avoid repeated SR ready-after
reads while preserving native reads for small templates.

## Install

Use the source installer from the repository root when OpenCode is already
installed:

```bash
uv run --project . python scripts/install_sparseread.py \
  --platform opencode \
  --opencode-workspace /path/to/project \
  --doctor
```

Then launch OpenCode from that workspace:

```bash
cd /path/to/project
opencode run "Use SparseRead to inspect the large report"
```

The installer now writes `.opencode/sparseread.json` as the persistent workspace
config, so production launch no longer depends on shell-specific `source`
activation. It selects the V1 or V2 entry by the CLI major. OpenCode 1.17.14,
1.19.5 and 2.3.0 have been exercised on macOS with a local deterministic
provider; a real-model qualification is tracked separately. On Windows, the
same command can be run from PowerShell, but Windows host compatibility has not
yet been qualified. V2 doctor verifies a synthetic host tool call, not model
quality or performance. Remote workspaces are not supported by the local bridge.


### Optional global OpenCode V2 install (development checkout only)

This option is in the current development source; the published v0.1.4 ZIP
does not include `--global`. From this checkout, run:

```bash
uv run --no-project --python 3.12 python scripts/install_sparseread.py \
  --platform opencode --global --doctor
```

This installs for the current user under `$XDG_CONFIG_HOME/opencode` (or
`~/.config/opencode` when unset). An absolute `OPENCODE_CONFIG_DIR` overrides
that location; relative overrides are rejected. Project installation remains the default;
`--global` cannot be combined with `--opencode-workspace` or another platform.
Global installation requires OpenCode V2; V1 lacks the V2 permission binding.
The bridge uses each local session's workspace and is unavailable for remote
workspaces. Restart OpenCode after installation.

In tested OpenCode 2.3.0, a global and a project plugin with the same
`sparseread` ID are deduplicated: the global copy runs and the project copy can
be reported as failed with `Duplicate plugin ID: sparseread`. The project files
are left in place. To disable SparseRead in a project, add
`"plugins": ["-sparseread"]` to that project's OpenCode configuration, merging
with any existing plugin list; this disables both copies by ID. Alternatively,
after reviewing it, remove an old project-local SparseRead plugin yourself.

To remove the global installation, review and remove only its owned
`plugins/sparseread` directory, `sparseread.json`, and
`sparseread/runtime/opencode` under the global OpenCode configuration root.
Do not remove other plugins or the OpenCode configuration directory. With the
global copy removed, a retained project-local copy can take effect again.
`--doctor` uses an isolated deterministic provider; it is not a model-quality
or performance evaluation.

## Runner

```bash
uv run --project nanobot-sro-v3 python integrations/opencode/run_pilot.py --offline
```

Use the installed `opencode` CLI to run real agent trajectories. If it is not on
PATH, set `OPENCODE_PATH` or pass `--opencode-cmd` with the executable path (or
a JSON argv array).

The benchmark runner materializes every task input at the `workspace_files.dest`
path declared in task frontmatter. This is also the path used by the automated
grader. Do not reintroduce a synthetic `./assets` prefix: doing so can produce a
correct report in the wrong directory and incorrectly score the case as zero.
The runner also passes the per-case runtime through OpenCode's explicit `--dir`
option. Relying on the subprocess working directory alone lets OpenCode discover
the outer repository root and run the agent against unrelated benchmark files.

This directory is the only OpenCode implementation source. The former
root-level `opencode_pilot/` copy was removed to prevent release drift.
