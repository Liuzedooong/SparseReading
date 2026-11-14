# @sparseread/opencode

OpenCode plugin for SparseRead. It registers SparseRead tools and lifecycle
guards, then talks to the independently installed `sparseread-opencode` Python
bridge over JSONL protocol `1.0`.

The default export (`@sparseread/opencode`) is the legacy V1 function entry;
`@sparseread/opencode/v2` is the V2 `Plugin.define` entry. Use a current patched
Node.js 22 or newer. For workspace installation and the matching Python wheel,
use the source installer; it selects one entry from the installed CLI major.
V2 host checks use OpenCode and SDK 2.3.0. Its doctor uses a local scripted
provider to test an actual synthetic tool call, not real-model behavior. The
local Python bridge does not support remote workspaces.

Build and inspect the publishable package:

```bash
npm ci
npm run build
npm pack --dry-run
```
