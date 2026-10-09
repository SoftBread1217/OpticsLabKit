# Changelog

## 0.3.0 — 2026-10-09

- Per-view independent processing overrides, with effective settings recorded in exports.
- Duplicate views of a single data column for simultaneous scan-branch/processing comparisons.
- Re-reading instrument files from original bytes; failed reads preserve previous data.
- Branch discovery independent of processing settings, allowing recovery from invalid smoothing.
- Repeat mean/SD refuses incompatible processing methods and warns on mixed normalization scales.
- Session schema 2 preserves views/overrides and reads legacy schema-1 sessions.
- Atomic demo/session replacement and explicit in-memory file removal free retained-file slots.
- Client event/model integration tests against the real local API, plus Node syntax checks in CI.
- Startup backend-version checks explain when an old service must be restarted after upgrading.

## 0.2.0 — 2026-10-05

- Shared SVG preview/PNG/SVG/PDF renderer with dimensions, typography, axes and legends.
- Editable per-curve labels, colors, lines and markers.
- Explicit experimental groups, TE/TM inventory checks and monotonic scan branches.
- Optional repeated-run mean/sample SD on overlap-only grids, with unit/condition confirmation.
- Portable original-byte sessions, atomic validation/restoration and explicit privacy notices.
- Origin-friendly independent X/Y tables and a standalone script using the same plot renderer.
- Synthetic branch/repeat examples and scientific/workflow regression coverage.
- No automatic FWHM, extinction ratio, physical unit conversion or claims of journal compliance.

## 0.1.0 — 2026-10-04

Initial local workbench for importing, comparing, processing, and exporting optical lab curves.
