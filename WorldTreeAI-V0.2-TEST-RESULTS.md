# V0.2 test results

## Environment and actual results

Linux x64, Python 3.12, PySide6 6.12.0. All personal genealogy/DNA tests use synthetic fixtures. One ancient specimen metadata fixture is transcribed from an attributed CC BY 4.0 publication; no private genetic files were used.

- **Backend: 32 tests passed, 0 failed** (includes 12 retained V0.1 tests).
- **Frontend: TypeScript check and Vite production build passed.**
- **Native Qt source: window opened, all native pages constructed, seven synthetic profiles displayed, and a first-cousin calculation executed through a native button.**
- **Embedded WebEngine/Cytoscape graph source rendering: PASS on Linux.** Missing libXtst/libxkbfile were obtained from the public Ubuntu archive and extracted into a scratch-only library path. The actual embedded graph canvas, labels, synthetic notice and native pages were verified. Windows packaged rendering remains unverified.
- **Windows build/executable: not run.** No Windows runner is connected; no EXE exists in this delivery.
- **AADR live catalog/download: blocked** by HTTP 403/robot check. No bypass attempted. Successful live resume/checksum transfer not claimed.
- **ENA live metadata download: PASS**, PRJEB6272, nine public run metadata rows, 371 bytes, locally hashed and cached. No raw genotype download claimed.
- **FamilySearch OAuth: fixture tests PASS** for PKCE, single-use/expired/wrong state, denied login, token clearing and GET-only ancestry transport. Live authorized login remains NOT RUN.

## Requested 20 acceptance checks

| # | Requirement | Actual result |
|---|---|---|
| 1 | EXE double-click launch | NOT RUN — executable not compiled |
| 2 | No terminal window | NOT RUN on Windows; spec sets GUI subsystem and pipeline checks it |
| 3 | GEDCOM import | PASS — supported UTF-8 structures and fixtures |
| 4 | FamilySearch-origin local edits | PASS — `_FSFTID` retained, locally editable; no FamilySearch writes; OAuth/import code tested with fixtures; approved live key unavailable |
| 5 | Offline tree access | PASS — local edit/search/vault with outbound URL calls disabled |
| 6 | DNA Relatives CSV | PASS — valid-format synthetic report |
| 7 | Raw DNA separate from match metadata | PASS — encrypted DNA table and separate matches |
| 8 | Famous sourced synthetic relationship | PASS — cousin path and review notification |
| 9 | Real public ancient sample with citation/license | PASS for published Kotias metadata excerpt; NOT a downloaded AADR genotype record |
| 10 | Similarity not mislabeled direct ancestry | PASS — explicit technical-concordance result and false direct-ancestor claim |
| 11 | Missing segments handled | PASS — shared-match clusters do not claim triangulation; no segment inference |
| 12 | Duplicate suggestion and merge preservation | PASS — review decisions, identities and original facts retained; undo tested |
| 13 | First/third/removed cousins, ancestors, unrelated | PASS; half-siblings and adoptive/marriage cases also tested |
| 14 | Detective evidence candidates, no unapproved people | PASS on cited synthetic proposals; successful live public search remains UNVERIFIED |
| 15 | Multiple providers per person | PASS — mapping retained through merge and undo |
| 16 | Full backup restored to clean DB | PASS — decrypted snapshot, SQLite integrity check and migrated/sample records checked |
| 17 | No public private-DNA view | PASS — unauthenticated endpoints denied; no public-profile feature |
| 18 | Bounded large-network navigation | PASS at API layer — 10,000 profiles, cap of 200 nodes; embedded graph source rendering PASS on Linux; Windows package NOT VERIFIED |
| 19 | Data after EXE restart | NOT RUN for EXE; backend reload persistence PASS and migration tested in separate process |
| 20 | Portable app without installed Python | NOT RUN — requires compiled package on clean Windows host |

## Additional checks

- Cross-owner duplicate genotype upload rejected; malformed SNP inputs and missing authorization rejected.
- Four-generation parent path works; cycle insertion rejected.
- Merge undo refuses to overwrite later edits.
- Genome-build mismatch rejected; reverse strand complementation and ambiguous-marker exclusions tested.
- V0.1 populated schema migrates in a subprocess and keeps original profile plus pre-migration backup.
- Local photo storage, encrypted backup, origin checks and consent revocation retain V0.1 test coverage.

Measured synthetic microbenchmark on this host: 10,000 profile insertion about 0.116 seconds; bounded name search about 0.0012 seconds, returning 19 results. These are one-run local measurements, not a Windows or million-record performance guarantee.

Warnings: one Starlette/httpx test-transport deprecation; Vite reports a bundled script above 500 kB. Native offscreen Qt reports propagateSizeHints limitations. None failed the passing tests.

## Remaining release gates

Run the supplied Windows workflow; manually verify double-click, no-console behavior, WebEngine/Three.js graph rendering, backup/restore dialogs, shutdown/restart persistence and clean-machine portability. Verify approved/live provider integrations separately. Do not label these checks as passed based on source inspection or Linux screenshots.

## Follow-up release blockers

An actual Windows build/validation still requires connected Windows infrastructure. GitHub integration was discovered and offered but is not confirmed connected. FamilySearch requires an approved client ID and registered redirect URI; regular account login alone does not satisfy that requirement. Advanced IBD, calibrated relationship probabilities, population models and scientific validation remain incomplete. None are represented as complete based on UI tests.
