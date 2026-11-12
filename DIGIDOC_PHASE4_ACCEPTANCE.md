# DigiDoc Phase 4 acceptance evidence

## Tester findings

| Finding | Status | Test names | Screenshot/file evidence |
|---|---|---|---|
| No automatic capitalization after a full stop or at paragraph start | Fixed | `test_autocorrect_and_autocapitalization_undo_immediately` | `attendance/test_digidoc.py`; `artifacts/digidoc-phase4-e2e/DigiDoc_Phase4_acceptance.docx` |
| No autocorrection | Fixed | `test_autocorrect_and_autocapitalization_undo_immediately` | Same test source; corrections can be undone immediately |
| Table controls and widths | Fixed | `test_table_widths_and_merges_are_explicit_in_docx_and_odt_exports`; `test_table_attributes_are_strictly_validated`; `test_table_grid_toolbar_and_structural_controls_work_in_editor` | DOCX/ODT XML tests and `DigiDoc_Phase4_acceptance.docx` |
| Layout controls non-functional | Fixed | `test_page_layout_spacing_and_indent_values_are_strict`; `test_layout_controls_apply_page_margin_spacing_and_letterhead_rules` | `DigiDoc_Phase4_editor_1440.png`, `DigiDoc_Phase4_editor_390.png` |
| Bold and italic not responsive | Fixed | `test_inline_format_toggle_stays_under_50ms_on_fifty_pages` | Performance test in `attendance/test_digidoc.py` (prints measured samples) |
| Too few fonts | Fixed | `test_font_allowlist_includes_phase_two_families_and_size_ceiling` | Font selector in editor screenshot; test source |
| Word download broken by bullets and numbering | Fixed | `test_docx_lists_use_numbering_definitions_and_preserve_nesting_and_restarts`; `test_phase4_editor_downloads_all_five_formats` | `DigiDoc_Phase4_acceptance.docx` |
| Fewer functions than Google Docs | Partly | Feature-specific tests listed in `DIGIDOC_FEATURE_FIDELITY.md` | Parity table in `DIGIDOC_FEATURE_FIDELITY.md`; 5 output files in `artifacts/digidoc-phase4-e2e/` |

## Browser run outputs

The Playwright scenario is `DigiDocPhaseTwoTests.test_phase4_editor_downloads_all_five_formats` in `attendance/test_digidoc.py`. It types a letter, creates a real ordered list and table, applies a font, enables a company letterhead, changes page margins, sets headers/footer/page numbers, then saves and reopens all five outputs with python-docx, odfpy, striprtf, pypdf and UTF-8 decoding.

Files: `artifacts/digidoc-phase4-e2e/DigiDoc_Phase4_acceptance.docx`, `.odt`, `.pdf`, `.rtf`, `.txt`, `DigiDoc_Phase4_editor_1440.png`, and `DigiDoc_Phase4_editor_390.png`.

## Remaining approximations and missing features

- Letterhead artwork is preserved by the editor and PDF export. DOCX, ODT, RTF and TXT exports omit the artwork.
- TXT has no pagination; its page-number entry is a placeholder and its header/footer appear at the start/end of the text.
- Comments, suggestion mode, version history, table of contents, footnotes and real-time co-editing remain unbuilt by design.
