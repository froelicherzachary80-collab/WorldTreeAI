# V0.2.0 — Connected Ancestry

Upgraded the existing V0.1 source rather than creating an incompatible replacement.

- Added native PySide6 desktop, per-user storage, in-process local service and embedded local assets.
- Added Windows portable PyInstaller configuration and Windows-runner build/test/artifact workflow. No EXE was compiled in this Linux session.
- Added schema migration 2 and pre-migration safety copy; retained existing imports and database formats.
- Added multi-path biological relationships, half-sibling evidence handling and separate nonbiological results.
- Added surname-block duplicate review, persistent decisions, provenance-retaining merges and guarded undo.
- Added provider identity mappings, markers, shared-match clusters, famous-profile paths and notifications.
- Added public Wikidata proposals/background tasks with explicit approval; blocked network results remain blocked.
- Added public ancient metadata imports, real licensed specimen metadata fixture, AADR annotation download/resume/checksum implementation and experimental strand-aware SNP concordance.
- Added local coordinate events, offline inventory, native backup/restore and V0.1 migration dialogs.
- Added source-native GUI smoke tests, expanded backend acceptance tests and actual Qt screenshots.

Corrections during validation: fixed native window method collision; corrected event SQL placeholders; prevented high-volume duplicate groups from starving small candidate blocks; disabled old irreversible merge behavior; removed revoked genetic data from merge snapshots; added graceful WebEngine-unavailable status.

No `.bat` launchers are delivered as the V0.2 user interface. Source-development Python scripts remain included for maintainers. No installer or signing certificate is supplied.

## Verification follow-up

- Resolved Linux Qt WebEngine runtime dependencies outside the package and verified the real embedded graph visually and through an automated smoke check.
- Implemented native FamilySearch PKCE authorization and read-only ancestor import, with single-use state, token lifetime and fixture tests. Live provider approval is still required.
- Added ENA study metadata download/cache/provenance and successfully verified a live public request.
- Expanded backend test suite to 32 passes. No Windows binary, advanced IBD engine, or fully validated genetic inference is claimed.
