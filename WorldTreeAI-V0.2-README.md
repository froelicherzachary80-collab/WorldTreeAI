# WorldTree AI V0.2 — The Connected Ancestry Update

**Release status: updated build-ready native desktop source (verification follow-up). A Windows EXE has NOT been compiled or tested.**

Follow-up: 32 backend tests pass; embedded Qt/Cytoscape graph rendering now passes on Linux after supplying missing public Ubuntu runtime libraries in scratch. OAuth PKCE and read-only ancestor import are implemented with fixture tests; production login still needs an approved app registration. Live ENA metadata download succeeded; AADR transfer and genetic inference remain unverified.

This upgrades the V0.1 project, retaining its database/import formats and adding a PySide6 native window, native research/relationship tools, migrations, evidence-aware analysis and a Windows packaging workflow. This is a usable foundation with explicit limitations, not completion of every proposed V0.2 scientific or online integration.

## The executable requirement

The intended release artifact is a portable folder with `WorldTreeAI.exe` plus bundled Qt/Python dependencies. Users launch only that EXE. It has a Windows GUI subsystem (`console=False`), starts its private loopback service internally, and embeds the local React/Cytoscape/Three.js tools inside Qt WebEngine. A browser or terminal does not need to be opened separately.

**Blocker:** the available development host is Linux and there is no connected Windows build runner or GitHub repository credential. No EXE or installer is included, and no file has been renamed to impersonate one.

### Automated Windows build

The source archive includes `.github/workflows/windows-build.yml` and `WorldTreeAI.spec`.

1. Put the **contents of this project folder at a GitHub repository root**, including the `.github` directory.
2. Open Actions → **WorldTreeAI Windows Release** → **Run workflow**.
3. The Windows 2022 x64 runner installs dependencies, rebuilds the frontend, runs tests, builds the portable application, verifies PE/GUI headers and checks that a native window appears.
4. Download `WorldTreeAI-V0.2-Windows-x64-portable` from that run's artifacts.
5. Extract the complete portable folder and double-click `WorldTreeAI.exe`. Keep its bundled `_internal` directory with it.

The workflow has been authored but not executed here. Its smoke test does not prove manual double-click behavior or operation on a clean Windows computer without Python. Those remain release gates. The executable is unsigned; code signing and an installer are not configured.

For developers with Windows: Python 3.12 x64, `pip install -r requirements.txt "pyinstaller>=6.16,<7"`, then `python -m PyInstaller --noconfirm WorldTreeAI.spec`. The prebuilt frontend is included. Source startup for development is `python WorldTreeAI.py`; this is a developer command, not the intended end-user launcher.

## First use and offline storage

At startup choose the default vault or select an existing/migrated/restored folder. The default uses Qt's per-user local application-data location, not the executable folder or PyInstaller extraction directory. Unlock or create a passphrase with at least 12 characters. There is no recovery for a lost passphrase.

An empty vault contains no invented relatives. The dashboard's optional synthetic demo is clearly labeled and can only initialize an empty vault. Use a separate vault for private research.

The program uses loopback port 8765 and refuses to attach to an already occupied port. Exit via the window or **Vault → Lock and exit**. Network access is unnecessary for local profiles, edits, imports, stored citations/photos, relationship calculations, duplicate review and backups. Uncached websites remain online resources.

## V0.1 migration

Use **Vault → Import V0.1 vault** and select the old `data` directory containing `worldtree.sqlite` and `vault.json`. The app copies it into a new timestamped folder. Restart, choose a non-default vault, and select the copy. Keep the original passphrase.

Migration 2 adds tables and indexes without dropping V0.1 records. A populated version-1 database gets a `worldtree.pre_v02.sqlite` safety copy before schema changes. The native copy workflow leaves the original V0.1 vault untouched. SQLite and vault metadata must stay together; keep the passphrase separately.

## Implemented functionality

| Module | What actually works |
|---|---|
| Native desktop | Qt main window, 18-section navigation, native menus/dialogs, dashboard, native service pages; embedded V0.1 tools where WebEngine is available |
| WorldTree Master | Existing profiles/edges/evidence/DNA/photos retained; new sources, identities, markers, findings, ancient samples, events and audit tables |
| Offline vault | Local inventory and storage size; encrypted full backups; GUI restore into a new directory; GUI V0.1-copy workflow |
| FamilySearch bridge | Registered-app OAuth PKCE and read-only ancestor import implemented; live approval/login unverified. GEDCOM alternative and local edits retained; no provider write code |
| Relationship engine | Biological common-ancestor traversal first; first/third/removed cousins, ancestors, half-siblings where enough parents are recorded, adoptive and marriage fallback; citations on each path |
| Multiple paths | Up to 8 paths per ancestor, 32 returned relationships, 20,000 visited paths; explicit truncation flag |
| Smart duplicates | Surname blocking with fuzzy names, dates/place conflicts, known parents, original identities; persistent separate/rejected/possible/later decisions |
| Reviewed merges | User reason and approval; preserve provider IDs, original profile facts and citations; encrypted pre-merge snapshot; undo only before subsequent data changes |
| DNA intelligence | Existing TXT/ZIP/CSV/manual match imports; stored shared-match evidence; connected-component clusters; recorded common ancestors; evidence-backed manual branch assignments via API |
| Famous explorer | Register a sourced notable local profile; calculate documented paths; label marriage separately; evidence-review notifications |
| Research center | Rate-limited Wikidata search/entity retrieval; public-source provenance; background tasks; proposed records; approval/rejection before new profiles are added; no automatic parent links |
| Ancestor detective | Local missing-field/parentage report plus explicit, opt-in public-name search; reports retrieved candidates and blocked requests honestly |
| Ancient browser | Canonical CSV/TSV and selected AADR annotation-column import; targeted sample IDs; offline sample search; dataset/version/license/citation retained |
| Public downloads | Official AADR metadata catalog; unrestricted annotation files only, max 50 MB; resumable partial downloads and repository checksums; live endpoint unavailable during development |
| Genetic laboratory | Known-build SNP concordance; ancient comparison additionally requires strand declarations, complements reverse alleles and excludes missing/haploid/ambiguous comparisons; never claims direct ancestry |
| Markers | All 14 marker kinds supported with reasons/status/source; profile display; automatic DNA/photo markers and reference-based direct-ancestor/unconnected markers; manual assignment/filter APIs |
| Graph | Bundled Cytoscape pan/zoom/search; bounded pages or focused branch expansion; distinct hypothesis/partner/adoptive/provider-match styles |
| Migration view | Native offline longitude/latitude grid with cited event points and lines by person; no basemap or inferred coordinates |
| Tree comparison | API compares approved identity mappings in two source namespaces; does not merge lookalikes |
| Historical photos/portrait | Preserved V0.1 encrypted photo gallery and generic rotatable speculative 3D head |

### Import examples

V0.1 SNP/GEDCOM/CSV synthetic fixtures remain under `fixtures/`. Start from distinct owner profiles for DNA import. A provider match entry never implies you own that match's raw genotype.

GEDCOM support is a **subset**, not full standard conformance: UTF-8 5.5.1/7 headers, INDI names, birth/death dates, birth locations, FAM parent/child/partner pointers, and `_FSFTID`/`_FSID`. Unsupported tags are not transformed into invented facts. Imported links remain hypotheses until manually reviewed with a citation. Full SOUR/media/ADOP/FAMC semantics, ANSEL, citations/continuations and every GEDCOM 7 structure are not implemented.

Use a stable namespace per imported tree for incremental deduplication. A record in another source remains separate until review. Existing local person fields are not overwritten during incremental import.

`ancient_public_kotias.csv` is a **real published specimen metadata excerpt**, not a DNA file or AADR download. Its accompanying license/attribution file documents the CC BY 4.0 publication source. Importing it demonstrates a real ancient record and provenance; it does not calculate a genetic connection to you.

## Authorization-dependent or blocked

- **FamilySearch:** official production access requires approval. OAuth authorization-code PKCE and read-only ancestor retrieval (1–8 generations) are now implemented. Enter the registered client ID in the native bridge, select beta or production, and register `http://127.0.0.1:8765/familysearch/callback` with FamilySearch. Authentication takes place in your normal browser, never in an app password form. OAuth state expires and is single-use; access tokens stay in memory and are cleared on lock/disconnect. Source payloads and IDs are preserved on authorized independent import. No approved key is available here, so live sign-in remains unverified. Descendant retrieval and full individual source-document retrieval remain incomplete. No protected-page scraping or provider writes occur.
- **AADR:** direct metadata retrieval returned HTTP 403 here; the dataset page also exposed a robot check. No bypass was attempted. The downloader is implemented but its live transfer/resume path has not been verified against Harvard in this environment.
- **Wikidata:** fixed public API connector and proposal flow implemented. Live successful retrieval is not claimed; automated evidence tests use labeled fixtures. Search sends only the explicitly selected name or Q identifier, never DNA.
- **ENA:** public study run-metadata download is implemented and live-tested with PRJEB6272 (nine run metadata rows). The source receipt and hash are in `docs/ENA_LIVE_VERIFICATION.json`. This does not download raw genomes or establish that every study record is an ancient specimen. ENA/EMBL-EBI terms apply. **WikiTree, SRA and general archives:** direct connectors are not implemented.

## Experimental or not implemented

No validated IBD/cM calculation, relationship-probability model, phasing, population-affinity/PCA model, haplogroup inference, segment triangulation or scientific face prediction is installed. SNP agreement is **technical concordance only**. Ancient pseudo-haploid calls are excluded rather than treated as diploid evidence. Input sample identity and strand metadata require source verification by the user.

No automated archive-wide parent discovery, local LLM, surname-history intelligence, complete famous/royal catalog, modern private DNA harvesting, public sharing, invitations or multi-user roles. All data is local/private. A proposed record is not proof of identity or a relationship.

Photo restoration/colorization was not implemented in V0.1 and is not falsely described as preserved here. The existing prototype is generic geometry and authorized photo storage. No ancestor likeness is generated.

Not all workflows have specialized UI: marker creation, branch assignment and tree comparison have authenticated APIs; native research output is structured text. Geographic coordinates are entered from cited records, not geocoded. Dates in migration events should be ISO-formatted for correct sorting. Full graph clustering, infinite branch navigation, background/checkpointed large imports, all source formats and PostgreSQL migration are future work.

Name blocks above 200 profiles are excluded from fuzzy candidate generation; only 100 candidates return per query. Whole-database encrypted merge snapshots can be expensive on large DNA collections. Exact network counts may be slow on very large databases. No million-record performance claim is made.

## Privacy and security limits

Raw DNA, original/photos and pre-merge snapshots use authenticated Fernet encryption with a Scrypt passphrase-derived key held in process memory. Windows credential-manager storage is not needed for absent provider credentials, and DPAPI is not integrated. Ordinary genealogy metadata in the working SQLite database is plaintext: use a private OS account and encrypted disk.

The entire backup database is passphrase encrypted. The JSON export is **unencrypted private information**, excluding raw genotypes and photos. Consent revocation deletes DNA, associated match/shared-match/ancient-comparison records and merge snapshots so snapshots cannot silently retain revoked genetic files. Existing exported backups, OS snapshots and SSD copies must be managed separately. Consent revocation does not mean forensic erasure across all storage media.

The app is single-user and loopback-only, with host/origin checks and HttpOnly same-site cookies. There is no publicly accessible profile endpoint. This is not hardened for public hosting or shared Windows accounts. Session timeout, throttling, multi-user ACLs and independent security review remain outstanding. Do not expose port 8765 externally.

## Development and verification

- Backend tests: `python -m pytest tests -q`.
- Native source smoke: `python tests/native_smoke.py` (offscreen on Linux; not an EXE test).
- Full embedded rendering smoke: `python tests/desktop_smoke.py` (requires working Qt WebEngine system libraries).
- Frontend rebuild: `cd frontend`, `npm ci`, `npm run build`.
- Schema: `backend/schema.sql` and `backend/schema_v02.sql`.
- Main entry: `WorldTreeAI.py` → `desktop/main.py`.
- Read `WorldTreeAI-V0.2-TEST-RESULTS.md` for exact results and blockers.

Screenshots are actual offscreen Linux Qt renders with seven clearly labeled synthetic profiles. They are not Windows screenshots.
