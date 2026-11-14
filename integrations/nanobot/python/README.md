# sparseread-nanobot

SparseRead's NanoBot integration is tested with `nanobot-ai==0.4.1`. Install
`sparseread-nanobot[nanobot]` and call `sparseread_nanobot.install(agent)` on
an official 0.4.1 `AgentLoop` before starting it. The adapter also registers
in the `sparseread.adapters` entry-point group. Versions 0.2 and 0.3 and other
hosts have not been qualified by this adapter.

The adapter binds its tools and hook to the actual request workspace, session,
generation and turn; it serializes stateful SparseRead calls within a session.
Each persistent turn must first execute the stock `read_file` tool, including a
bounded read, before direct SparseRead source access is available. A broad
`read_file` may hand off to `sro_preview` if the preview tool is enabled and the
source passes the host's native reader checks. If no reader proof is available,
use native tools. Ephemeral turns skip the hook and SparseRead source access.

Only stock `read_file` is eligible for automatic handoff. Bounded or forced
reads, directories, `list_dir`, and shell commands remain native. SparseRead
source access is confined to the session workspace; mismatched workspace scopes,
parent (`..`) components, unsupported collections and paths rejected by the
native reader fail closed to native tools. Collection paths are checked against
the native reader and a core manifest before reading. These checks use the
0.4.1 reader's private resolver and are not an atomic filesystem sandbox.

The supported entry is `install`; the previous standalone hook constructor is
not a compatibility interface. This integration does not modify NanoBot's
user configuration or claim authorization beyond the current native reader.
