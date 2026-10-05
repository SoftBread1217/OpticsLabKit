# Roadmap

## v0.1.0 — Import, compare, and export

- [x] Local Chinese interface and synthetic TE/TM demonstration
- [x] TXT/CSV/TSV/DAT/XLSX import with explicit parsing settings
- [x] Multi-curve overlays, optional baseline, smoothing, normalization
- [x] Acquisition-order preservation and explicit invalid-row reporting
- [x] PNG/SVG/CSV exports and provenance manifest
- [x] Python API, CLI, regression tests and CI configuration

## v0.2.0 — Optical workflows and reproducible editing

- [x] Shared preview/export renderer and physical figure styling
- [x] Per-curve label/color/line/marker controls
- [x] User-declared TE/TM groups and pair inventory checks
- [x] Monotonic branch selection before processing; no cross-turn smoothing
- [x] Repeated-run mean/sample SD, overlap-only interpolation and validation
- [x] Original-byte session save/load with parser settings and comparison controls
- [x] Vector PDF, Origin-friendly independent X/Y tables and standalone redraw scripts
- [x] Synthetic examples and backend/end-to-end regression tests
- [x] User-approved publication with local scientific/workflow tests and remote CI gate
- [ ] Ongoing feedback with real instrument files and target-journal figure dimensions

## Later: driven by real usage

- Per-curve processing settings (currently one shared processing panel)
- Peak/dip fitting and FWHM with model, background, and uncertainty made explicit
- Extinction ratio with user-confirmed power/dB conventions
- Batch exports for repeated measurements
- Supplied uncertainty columns and error bars (distinct from repeated-run sample SD)
- Optional PhotonAct-compatible optical response export after branch/units validation

Prioritize formats and analysis that actual lab users need. No experiment data is bundled
until its provenance and publication permission are established.
