# WorldTreeAI V0.2 — Windows build verification

Built October 10, 2026, from commit 2b3ba4a6b5660feb9f6cdb6824ddaf4096742315.

- Build: https://github.com/froelicherzachary80-collab/WorldTreeAI/actions/runs/38025433560
- Environment: actual Microsoft Windows Server 2022 x64 GitHub-hosted runner; Python 3.12.10; PyInstaller 6.22.3.
- Automated suite: 32 passed, 1 warning, 17.03 seconds.
- Frontend production build: passed.
- PyInstaller packaging: passed.
- Executable PE signature and Windows GUI subsystem (2): passed.
- Packaged EXE launch: process remained running for 15 seconds and had a native window handle.
- Portable bundle includes Python, Qt/WebEngine, local frontend, and database schemas.
- ZIP SHA-256: dd45cd040856bf0e57e4a701dc697756dfe0a7a2e855caff33f6c300a6c997a8

Download the portable ZIP, extract ALL files into a folder, then double-click WorldTreeAI.exe. Keep _internal next to the EXE. Do not run directly inside the ZIP. No terminal, Python install, or separate server is needed.

Scope: startup verification reaches the vault unlock dialog, not a full end-to-end packaged GUI session. Windows 10/11 consumer editions and a Python-free clean PC were not separately tested. The embedded graph was rendered and checked in the source Qt application on Linux, not in this packaged Windows test. This build is unsigned.

Packaging does not change feature limitations: FamilySearch production OAuth still needs an approved client ID and live authorization testing. Public ENA metadata download was verified previously; AADR download remained blocked. Advanced IBD/cM and population inference remain unimplemented; experimental SNP concordance is not proof of ancestry. See the existing detailed test report for source functionality.

This report supersedes earlier statements that no Windows executable was produced.
