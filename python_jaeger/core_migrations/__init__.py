"""Per-release migration scripts.

Each migration is a module named v<FROM>_to_v<TO>.py with a top-level
`migrate(layout)` callable. The runner discovers them by walking this
directory, sorts them by their (FROM → TO) edge, and applies them in
order until the instance's manifest matches the installed CORE_VERSION.

Migrations must be idempotent — running a successfully-applied migration
again is a no-op. On any failure the runner refuses to start (a partial
migration is worse than a clear refusal).
"""
