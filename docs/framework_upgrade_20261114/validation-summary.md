# Framework validation matrix — v0.1.4, 2026-11-14

This matrix records qualification of the **v0.1.4 source**.
The fixed integration commit `05768c8c4a583f5209ba32da56660fa7bc0d29b1`
completed the checks below; the eventual delivery commit adds documentation and
archive-list changes. `BUILD_COMMIT.txt` and `SHA256SUMS` identify the exact
delivered artifacts. The historical `v0.1.3` tag predates these changes;
development artifacts that
still carry `0.1.3` must not be confused with that tag. Prior paper measurements describe their original implementations and
workloads, not the upgraded adapters below.

All host results here are limited to the tested **macOS arm64** environment and
listed versions. A deterministic provider exercises host protocols but is not
an actual-model quality test. A single synthetic model workflow establishes
activation for that candidate only; no paired performance comparison is
claimed. The fixed commit passed 323 Python tests with zero skips (including official
NanoBot), five OpenCode Node tests, and 19 Pi Node tests with zero skips. Six
locks were checked, and 18 artifacts were built: six wheels, six sdists, three
npm packages, a Codex plugin archive and source ZIP/TAR. The two source archives
matched on 106 members' bytes and modes, and SHA256SUMS passed. Website build
and link checks passed after a transient network failure. CI configuration in the
tree does not itself establish a passing remote CI run.

| Component / target | Actual host and deterministic evidence | Actual model evidence | Artifact boundary and remaining work |
| --- | --- | --- | --- |
| Core | `133e93d`: identity, same-size source change, session separation, workspace paths, source manifest, invalidation, raw/verification and bounded collection tests; 290 source tests and 31 isolated-wheel tests at that checkpoint. | Not a model host by itself. | Earlier 0.1.3 development core wheel SHA-256 `87ea92c3367a659c07eee6bbc66178c7b837dd038795c2fe4eb9fde9441b8d32`; isolated 0.1.4 candidate wheel `44ac49e67c9e7cac8d90d73f66f0811a62bd5cf756624ef66f8999fd7598093a`. The `05768c8` source archive passed qualification. Source checks and opening are not an atomic filesystem sandbox. [Core evidence](core-implementation.md). |
| OpenCode V2 target **2.3.0** | Official 2.3.0 host: five-tool registration, source and collection permissions, Code Mode, session isolation, cancellation and bridge recovery. V1 **1.17.14** and **1.19.5** separately exercised through their real hosts with a scripted provider. | One synthetic `deepseek-flash` workflow on 2.3.0 exercised native read → preview → focused read and returned `CAPRI-913`; not a performance comparison. The available Paratera credentials returned blocked/401; that route remains unqualified. | Core/OpenCode runtime/build files matched `6cdc877` in that model candidate, while three installer/documentation files differed. Independent [packaging review](packaging-review.md) tested the `6cdc877` source archive and npm package; the integrated `05768c8` source ZIP also passed the actual 2.3.0 host check. See [OpenCode implementation](opencode-implementation.md). |
| Claude Code target **2.1.325** | Official 2.1.325: hook deny and native retry, bounded and host-denied reads, MCP discovery/error behavior, mode reinstall and rollback; eight MCP tools also exercised over stdio. | One `deepseek-flash` workflow used a test-only Messages-to-Chat wire converter and exercised preview → focused read → `CAPRI-913` over three requests (13,228 prompt plus output tokens; cache is included in prompt). This is not an Anthropic-native backend qualification. | Model run used an earlier candidate; final installer, whitespace-path and trace changes were separately tested deterministically. Earlier approved 0.1.3 Claude wheel SHA-256 `441e2dbad462de11bb4ff0cfd8b49cd32eba163b5295e38b045283683f61ee39`; isolated 0.1.4 candidate wheel `8cbcc9a29ff8dd2eb8547d17b2c6796da8a9ea81fef4be6668ce5db8b768d26e` has independently matched runtime code. [Claude evidence](claude-implementation.md). |
| Codex CLI target **0.169.0** | Official 0.169.0: project trust separation, six MCP tools, Unicode/stale/source-change/workspace checks, one-time `cat` handoff and native retry, fork, `write_stdin`, mode reinstall and changed-hook state. Hook trust remains separate from installation. | A corrected `deepseek-flash` compatibility-wire run invoked preview → focused read and returned `CAPRI-913`: three requests, 32,114 input tokens (25,728 cached input is a subset) and 245 output, total 32,359. Earlier unsuccessful requests remain in the verifier's record. | Source candidate integrated as `a5ca820`; the integrated `05768c8` source ZIP passed the actual 0.169.0 host check. CLI validation does not establish Desktop, Cloud or Web compatibility. [Codex evidence](codex-implementation.md). |
| NanoBot **0.4.1** | Official 0.4.1 AgentLoop, AgentHook and ToolRegistry: 19 isolated installed-wheel tests plus 9 independently reviewed permission cases, including stream/nonstream, sessions, source changes, tool disablement, failures and cancellation. Each persistent turn must first select the stock `read_file`; bounded native read can establish that proof. Shell, directories, list and bounded/forced native reads stay native. | One first-attempt `deepseek-flash` workflow used the stock official AgentLoop and Chat SSE, without protocol conversion: native read/handoff → preview → focus → `CAPRI-913`. Four requests used 37,920 input tokens (27,264 cached input is a subset) and 312 output, total 38,232. | Adapter `a7d4776`; final 0.1.4 wheel SHA-256 `befa8dbf7a9596c2b615db8aa2b3842c4d98c677fed98b2c648a713ec2392188`. Model wheel `afdbf92c31a78e2ebd3a105c402f44b1b7a41ba88e52baa848d43d43cbe18cdd` differed only in README metadata; five adapter runtime files were byte-identical. Other NanoBot versions and Windows are unqualified. [NanoBot evidence](nanobot-implementation.md). |
| Pi **0.87.1** | `05768c8`: 19 Node tests, zero skips; actual SDK npm package and extracted source ZIP installation exercised preview and raw. | No new model result claimed. | Validated fixed host version on macOS, not a claim of a latest-version upgrade. |
| OpenClaw **2026.7.1-2** | `05768c8`: extracted source ZIP installed through the actual CLI; inspect and loopback gateway preview/raw completed. | No model request; direct host tool invocation. | Validated fixed host version on macOS, not a claim of a latest-version upgrade. |

See also the independent OpenCode host record at
`/Users/captainliu/sparse-reading/docs/framework_upgrade_20261114/validation/opencode-host-validation.md`
and the Claude/Codex verifier's preserved fixture logs; those paths are local
evidence, not portable runtime dependencies. The checked-in reports preserve earlier failures and superseded hashes. See the
[independent final validation report](f4-final-validation.md) for the
fixed-commit gate and the exact delivery-artifact records.
