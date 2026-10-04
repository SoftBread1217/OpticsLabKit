# Roadmap

## v0.1.0 — Import, compare, and export

- [x] Local Chinese interface and synthetic TE/TM demonstration
- [x] TXT/CSV/TSV/DAT/XLSX import with explicit parsing settings
- [x] Multi-curve overlays, optional baseline, smoothing, normalization
- [x] Acquisition-order preservation and explicit invalid-row reporting
- [x] PNG/SVG/CSV exports and provenance manifest
- [x] Python API, CLI, regression tests and CI configuration

## Next: driven by real usage

- Save and reload comparison sessions and per-curve processing settings
- Peak/dip fitting and FWHM with model, background, and uncertainty made explicit
- Extinction ratio with user-confirmed power/dB conventions
- Batch exports for repeated measurements
- Uncertainty columns and error bars
- Optional PhotonAct-compatible optical response export after branch/units validation

Prioritize formats and analysis that actual lab users need. No experiment data is bundled
until its provenance and publication permission are established.
