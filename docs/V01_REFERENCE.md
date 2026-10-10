# WorldTree AI V0.1 — DNA Genesis

A working, private, single-user genealogy application for Windows 10/11 and a local web browser. This is a foundation release, not completion of the entire V1.0 specification. The default database starts empty. Synthetic demonstration data are opt-in and visibly labeled.

## Start on Windows

1. Install 64-bit Python 3.12 or newer from https://www.python.org/downloads/ (enable the Python launcher).
2. Extract this ZIP to a writable folder, outside public/shared folders.
3. Double-click **Setup_Windows.bat**. First setup needs internet to install dependencies.
4. Double-click **Start_WorldTree.bat**. Open http://127.0.0.1:8765 if the browser does not open.
5. Create a passphrase of at least 12 characters. There is no password recovery. Save it securely.
6. Choose **load synthetic demo** to explore, or create your own profiles in Global Family Tree. For private work after trying the demo, stop the server and choose a fresh data directory; do not mix synthetic profiles into real research.

The prebuilt React frontend is included: Node.js is NOT required to run. Stop with Ctrl+C in the server window. Do not close the server window while using the app.

Linux/macOS: `python -m venv .venv`, activate it, `python -m pip install -r requirements.txt`, then `python launch.py`.

## First import walkthrough

Create two owner profiles. In Import & Data Management, assign `fixtures/ancestry_synthetic.txt` to the first and `fixtures/23andme_synthetic.txt` to the second, with authorization checked and a synthetic owner statement. The laboratory compares these two files: 2 comparable markers, 1 identical genotype, 50% technical agreement. These deliberately tiny files do not support genetic kinship estimates.

Import `family_synthetic.ged` with namespace `synthetic-tree`. Repeating the same file does not duplicate people. Updating this same tree with new individual IDs adds profiles; existing profile fields are preserved, not silently overwritten. Different trees use different namespaces; identical names in separate trees remain distinct until reviewed.

Import `relatives_synthetic.csv` with an explicit owner and authorization. The adapter requires the real-format `Display Name` column, reads known sharing/prediction columns, and preserves all remaining fields as original JSON. No segment triangulation is inferred.

Imported GEDCOM parent links are hypotheses. In Global Family Tree, review a link with a supporting citation before marking it documented. The Relationship Finder excludes unreviewed links. The built-in demo uses documented *synthetic* edges to demonstrate first-cousin paths.

## Implemented

- FastAPI backend, persistent SQLite database, initial schema migration, React/TypeScript frontend, bundled Cytoscape and Three.js (no runtime CDN).
- Private profiles with names, dates, locations, aliases/notes storage and API updates; biological/adoptive parent and partner links; evidence citations and audit history.
- Search, paginated graph (100 nodes per UI page; server hard cap 200), pan/zoom/select, profile panel, dashboard, recorded-date timeline.
- Ancestry/23andMe SNP TXT and single-file ZIP parsing, build metadata, marker validation, duplicate file/owner conflict detection, explicit authorization statements, encrypted original DNA storage.
- Compatible known-build genotype concordance, explicitly not IBD/cM or kinship.
- UTF-8 GEDCOM 5.5/5.5.1 subset: INDI, NAME, BIRT/DEAT DATE, birth PLAC, FAM HUSB/WIFE/CHIL. Original source namespaces preserve identity across imports.
- Authorized DNA Relatives CSV and manual match entry. CSV provider IDs deduplicate imports; rows without stable IDs deduplicate only exact repeated files.
- Name-based duplicate candidates with explicit reason and approval before merge; retains provider rows, citations, notes and old-profile audit snapshot.
- Documented relationship paths, common ancestor for basic cousin/ancestor cases, adoptive/partner path fallback, unknown result when evidence is insufficient.
- Research task queue with local rule-based gap suggestions; citations remain user-reviewed.
- Authorized photo upload, encrypted original and display derivative; generic rotatable 3D head, clearly labeled speculative.
- Passphrase-derived vault key kept only in server memory, lock/logout, raw DNA/photo encryption, consent revocation, encrypted full backup, offline restore and unencrypted genealogy JSON export.

## Explicitly incomplete / limitations

- No automatic historical-source searches, official genealogy API integrations, local LLM, autonomous expansion, or proposed-edit review workflow. Research tasks are a planner, not an AI researcher.
- No IBD inference, validated shared-cM probabilities, shared-match clustering, parental phasing, segment visualization/triangulation, ethnicity analysis or DNA appearance prediction.
- No photo damage restoration, colorization, resemblance generation, reconstructed facial geometry, apparent-age controls or photorealistic portraits. The head is generic geometry, never an inferred ancestor.
- Locations are displayed in a register; no actual world map/geocoding or migration routes. No maternal/paternal or ancient ancestor filters.
- No invitations, public hosting or multi-user roles. All profiles are private; there is no separate minors policy engine beyond required permission statements. Only the local OS user boundary and vault authentication are supported.
- GEDCOM source records, multimedia records, full GEDCOM 7, ANSEL, custom tags, adoption tags, inline source citations and continuation fields are not imported. Family assertions may be incomplete: review before marking documented. No automatic incremental field reconciliation.
- Relationship labels show one shortest common-ancestor path. Multiple relationships, pedigree collapse, full-vs-half-cousin distinctions, ancestry deeper than 10,000 visited nodes, and complex blended pedigrees require further work.
- UI profile selectors/search show up to 100 current results; search narrows choices. Match display caps at 500. Graph pages show only edges whose two endpoints are on that page. This is bounded rendering, not population clustering or full graph navigation.
- Imports are synchronous and atomic, not background/checkpointed. Per-file safety cap 80 MB; there is no total profile/file-count cap. Million-profile performance is not validated.
- Profile merge dismissal is temporary; rejected candidates are not persisted. Conflicting provider IDs can cause a merge failure rather than silent record loss. Full unmerge is not available; take a backup first.
- Dashboard shows implemented counts. Full connected-component totals, verified-common-ancestor counts and speculative-connection metrics are not presented as implemented results.
- No backup import UI; restore uses the included command-line utility. No SQLite-to-PostgreSQL adapter yet.

## Security and backups

Bind only to 127.0.0.1. This is not an internet-facing service. Host/origin checks, same-site HttpOnly sessions and a self-only content policy protect browser access. Local HTTP cookies are not Secure because the server uses loopback HTTP. Sessions end on lock or server restart; inactivity expiry and login throttling are not implemented.

Raw DNA and photos use Fernet authenticated encryption, with a Scrypt-derived key and unique random salt. Passphrase and key are not written to disk. Working **genealogical metadata is plaintext SQLite**. Use a private OS account and encrypted disk (e.g. BitLocker). Do not use a shared PC account for sensitive data. DNA parsing uses process memory; OS swap protection is outside the application.

The backup endpoint encrypts the complete consistent SQLite snapshot and packages it with vault metadata. Keep the passphrase separately. Restore while stopped:

`.venv\Scripts\python restore.py WorldTree_private_backup.zip restored-data`

Destination must be new. Then set `WORLDTREE_DATA` to that directory before starting. Alternatively, after verifying the restored copy and with the server stopped, move it to the default `data` directory. Do not overwrite a current database without a backup.

Consent revocation deletes that person's DNA and associated match rows, enables SQLite secure_delete, and vacuums the database. It cannot erase existing backups, SSD snapshots or copies already exported. Delete those separately where required. Export JSON contains private profile/match information and is not encrypted; raw genotypes/photos are excluded.

## Source layout

- `backend/app.py`: API, vault, services, graph queries, relationship paths.
- `backend/parsers.py`: SNP, CSV and GEDCOM adapters.
- `backend/schema.sql`: complete initial database schema.
- `frontend/src/`: editable React/TypeScript UI and CSS.
- `frontend/dist/`: production frontend, ready to run offline.
- `fixtures/`: synthetic import examples.
- `tests/test_acceptance.py`: repeatable backend acceptance tests.
- `launch.py`, Windows BAT files, `restore.py`: startup/recovery.

Rebuild frontend: install Node 20.19+ or 22.12+, then `cd frontend`, `npm ci`, `npm run build`. Backend tests: from project root `python -m pytest -q`.

## Provider references checked during implementation

- Ancestry DNA download / match-list export limitation: https://help.ancestry.co.uk/hc/en-gb/articles/53933317283603-Downloading-DNA-Data
- 23andMe DNA Relatives privacy/download settings: https://customercare.23andme.com/hc/en-us/articles/18262768896023-DNA-Relatives-Privacy-and-Display-Settings
- 23andMe raw data access: https://customercare.23andme.com/hc/en-us/articles/212196868-Accessing-Your-Raw-Genetic-Data

No provider website automation, credentials, paywall bypass, remote uploads or paid APIs are used. Export availability and fields depend on provider settings.

## Planned versions (not implemented)

V0.2: validated genetic grouping and improved evidence review. V0.3: permitted archive integrations and proposed edits. V0.4: consent-aware artistic image workflows. V0.5: large-network navigation and opt-in collaboration. V1.0: integrated platform after validation.
