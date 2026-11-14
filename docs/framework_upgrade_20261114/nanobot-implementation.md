# NanoBot 0.4.1 implementation and verification

The adapter targets the official `nanobot-ai==0.4.1` `AgentLoop`, `AgentHook`
and `Tool` interfaces. Version 0.2/0.3, other host versions, Windows and other
platforms have not been qualified. The optional host dependency is pinned;
adapter and core dependency floor are 0.1.4. The core does not import NanoBot.

The adapter registers the six SRO tools and one turn hook factory, replaces
only its own registration on reinstall, and keeps other hooks and tools. The
active runtime comes from each `RequestContext` and is keyed by workspace,
session and generation. Stateful SRO calls are serialized per session; ordinary
native tool batches keep the host's normal scheduling. Per-call callbacks track
successful writes and clean up pending state on errors and cancellation.
Ephemeral turns skip the hook and source access.

A direct SRO source operation requires a stock `read_file` selected in that
turn; a bounded native read can establish this proof. The actual selected
reader's resolver checks the requested lexical and canonical paths and each
path in the core source manifest. Broad native reads may be redirected through
an owned, short-lived same-tool reminder when the SRO preview tool is enabled;
the native reader checks both source and reminder. Bounded or forced reads,
directories, list operations and shell calls stay native. Missing proof,
parent path components, incompatible scopes, rejected paths and incomplete
manifests leave native access as the alternative. Reader checks and core
manifest version revalidation do not provide an atomic kernel filesystem
sandbox. A successful SRO direct call is not a claim of permissions beyond the
selected native reader. Supporting custom reader implementations and automatic
shell interception is outside this adapter's current scope.

Verification on macOS in an isolated Python 3.12 environment installed official
NanoBot 0.4.1 and built core/adapter wheels, with checkout `PYTHONPATH` removed:

```
uv build --wheel --out-dir /tmp/sro-nano041/wheels packages/sparseread-core
uv build --wheel --out-dir /tmp/sro-nano041/wheels integrations/nanobot/python
uv pip install --python /tmp/sro-nano041/venv/bin/python --no-deps --reinstall /tmp/sro-nano041/wheels/sparseread_core-0.1.4-py3-none-any.whl /tmp/sro-nano041/wheels/sparseread_nanobot-0.1.4-py3-none-any.whl
cd /tmp/sro-nano041
env -u PYTHONPATH ./venv/bin/python -m pytest --import-mode=importlib /Users/captainliu/Downloads/sparseread-github-mirror/updated-repo/integrations/nanobot/python/tests -q
```

Result: 19 passed. These use the official full AgentLoop with deterministic
provider for stream/nonstream, concurrent sessions, repeated turns/clear,
handoff, tool disablement, error/cancellation and provenance, and actual host
ToolRegistry/CompositeHook tests for schemas, all six tool executions, source
and session isolation, collection and path boundaries. Deterministic provider
results are not model results. An independent reviewer also ran nine host
permission cases and one bounded DeepSeek workflow through the real official
host: four requests, native read/handoff, preview and focus, final `CAPRI-913`.
The model call used the user's existing localhost DeepSeek service and only a
synthetic fixture.

Final adapter wheel SHA-256:
`befa8dbf7a9596c2b615db8aa2b3842c4d98c677fed98b2c648a713ec2392188`.
Core wheel SHA-256:
`44ac49e67c9e7cac8d90d73f66f0811a62bd5cf756624ef66f8999fd7598093a`.
The independent model test used the preceding adapter wheel
`afdbf92c31a78e2ebd3a105c402f44b1b7a41ba88e52baa848d43d43cbe18cdd`;
the wheel change was README metadata only, with identical adapter Python code.
An earlier test used text as a collection raw selector and failed; it was
corrected to the filename selector and now checks the returned source content.
Initial build command attempts using the wrong current directory or a nonexistent
venv `pip` executable also failed; the commands above were used successfully.

Independent evidence is retained under
`/Users/captainliu/sparse-reading/docs/framework_upgrade_20261114/validation/evidence-f3/`:
`nanobot-041-chat-deepseek.json`, `nanobot-041-chat-deepseek.stderr`,
`nanobot-041-chat-deepseek-usage.jsonl`,
`nanobot-041-native-contract-final.json` and
`nanobot-041-chat-offline-final.json`. The four DeepSeek requests reported
37,920 input tokens (27,264 cached), 312 output tokens and 38,232 total.
