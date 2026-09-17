# Confirmed technical incident: SQLite lock during 30-hour confirmation

The 2026-09-17 application log contains repeated `sqlite3.OperationalError: database is locked` traces during `confirm_af_policy`, `check`, `RunStore.get`, and `RunStore.save`.

This is confirmed technical evidence for failure signature `4ac7c59609da3256`, not a human business decision. The remediation is deterministic: all RunStore connections use a 15-second timeout and busy timeout, WAL journaling, and normal synchronous mode; the AF confirmation UI disables duplicate submission while the request is active.

No policy value was invented by this fix. Missing rating authority/reference remains `NEEDS_INPUT`; the user must still confirm real policy exceptions where applicable.
