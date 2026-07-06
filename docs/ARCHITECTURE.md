# Architecture notes

## v1.2 design

The project now has two layers:

1. **Stable compatibility layer**
   - `legacy_scan.py`
   - `legacy_rename.py`

   These are the proven working scripts, kept intact to avoid breaking the workflow.

2. **New project layer**
   - `adb.py`
   - `cli.py`
   - `workflow.py`
   - `settings.py`
   - `names.py`
   - `templates.py`
   - `ocr.py`
   - `logs.py`
   - `paths.py`

The CLI calls the legacy scripts via `python -m`, but shared concepts are now represented as modules.

## Next extraction target

The next practical extraction is to move the scan decision code from `legacy_scan.py` into `names.py` and then replace the inline legacy decision logic with calls to `classify_for_name`.

After that, move template matching into `templates.py`.


## v0.4 notes

The project now has reusable modules for:

- diagnostics: `doctor.py`
- app package actions: `apps.py`
- screen model and coordinate scaling: `ui.py`

The next safe extraction is to make `legacy_rename.py` call `ui.DEFAULT_SCREEN.fixed_triangle()` instead of carrying its own fixed coordinate helper.


## v0.5 notes

`workflow.py` no longer owns the subprocess argument construction. It calls:

- `scan.run_scan_pass()`
- `rename.run_rename_pass()`

`legacy_rename.py` now uses the shared `navigation.fixed_triangle_point()` helper for the fixed appraisal triangle coordinates. This is the first piece of legacy logic wired to a new extracted module.


## v0.6 notes

The scanner had a regression because it still used `right_triangle_template.png` for scan navigation. That template can falsely match Pokémon shapes high on the screen. `legacy_scan.py` is now wired to `navigation.fixed_triangle_point()` just like the renamer.


## v0.7 notes

v0.6 correctly moved scanner triangle navigation to fixed coordinates, but the retry/refresh branch used the wrong wait variable name (`wait_after_right_retry`). v0.7 fixes this to the original function parameter, `wait_after_right`.


## v0.8 notes

A cleanup layer was added in `cleanup.py`. `workflow.run_workflow()` calls it by default before scan starts, so stale screenshots/logs cannot affect current-run debugging or CSV-based rename flow.


## v0.9 notes

Naming was corrected:

- `rank1` maps to Great League suffix `(1)`.
- `rank2` maps to Ultra League suffix `(2)`.
- Only rows passing the threshold are included in `rename_to`.
- IV names are compact digit strings.


## v1.0 notes

PvP league mapping now uses visible row order from the OCR text instead of circled rank symbols. Circled rank symbols are ranking within each league, not a league identifier, and both rows may show `①`.

- first PvP percentage row -> Great League
- second PvP percentage row -> Ultra League


## v1.1 notes

PvP row parsing now extracts both visible row order and the circled form/evolution marker after each PvP percentage. Names use compact marker digits instead of parentheses to stay under the nickname length limit.


## v1.2 notes

The README now includes full setup requirements, including Google platform-tools ADB installation and Wireless debugging pairing/recovery steps. Helper scripts were added under `scripts/`.
