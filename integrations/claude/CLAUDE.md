# SparseRead File Reading Guidance

SparseRead tools are available as MCP tools: `sro_preview`, `sro_read`,
`sro_card`, `sro_raw`, `sro_decide`, `sro_trace`, `sro_preflight`, and
`sro_usage`. Consider them for targeted evidence in larger documents or
collections. Native tools remain available for bounded reads, exact work,
verification, and cases where SparseRead is unsuitable.

## Evidence workflow

1. Use `sro_preview(path="...")` to inspect a permitted workspace source.
2. If targeted evidence is needed, call `sro_read` with the returned
   `artifact_id` and a concrete goal, slots, or needles.
3. Use `sro_raw` or native tools when original content or verification is
   necessary. Refresh a stale raw reference with a new preview.

For multi-file evidence, an optional `episode_hint` can specify `goal`,
`relation`, and `coverage`; the gate determines its own decision. Preflight
considers top-level regular files only; an explicit preview can target other
permitted workspace sources. Collection calls can read multiple files, and MCP
approval is distinct from the native Read tool's per-file permissions.

Auto mode can redirect the first eligible unbounded native `Read` or simple
single-file `cat` for a session and source version. The retry remains subject
to normal host permissions. Advisory mode does not block native reads. Bounded
reads, searches, pipes, and compound commands remain native. PowerShell shell
interception has not been verified.
