# DigiDoc feature fidelity and Google Docs parity

## Export fidelity

| Feature | DOCX | ODT | PDF | RTF | TXT |
|---|---|---|---|---|---|
| Bulleted lists, nesting, empty items | Native Word numbering | Native ODF lists | Rendered list markers | Rendered list markers and indentation | Visible markers and indentation |
| Number styles and restart | Native numbering definitions and restart | ODF numbering styles and start values | Rendered markers and start values | Visible markers and start values | Visible markers and start values |
| Tables | Editable; fixed layout, full/selected width, grid and cell widths, merges, shading, borders | Editable; table and column widths, cell spans, shading and borders | Rendered at selected width with proportional columns | RTF table geometry, cell borders, shading | Readable text rows; styling and merges are lost |
| Paragraph layout | Spacing, indents, page dimensions and margins | Spacing, indents, page dimensions and margins | Rendered page size, margins, spacing and indents | Spacing and basic indents; no page layout | Spacing approximated with blank lines; indents omitted |
| Headers and footers | Native repeating header/footer parts | ODF master page header/footer | Repeated on each page | Repeated header/footer groups | Header appears first; footer appears at end |
| Page X of Y | Word PAGE and NUMPAGES fields | ODF page-number and page-count fields | Actual page count | RTF page and NUMPAGES fields | Placeholder text; plain text has no pagination |
| Letterhead artwork | Not preserved | Not preserved | Preserved on A4 portrait pages | Not preserved | Not preserved |
| Links | Clickable; only http, https and mailto pass validation | Clickable; only http, https and mailto pass validation | Clickable; only http, https and mailto pass validation | Clickable; only http, https and mailto pass validation | URL text only |
| Bold, italic, underline, strike, super/subscript | Native formatting | Native formatting | Rendered | Native RTF formatting | Plain text |
| Fonts, size and colour | Preserved; missing fonts may be substituted by Word | Preserved; missing fonts may be substituted | Self-hosted fonts embedded where available | Font names and size retained | Plain text |
| Images | Embedded in the document | Embedded in the document | Embedded | Embedded inline | Alt text label |

## Google Docs parity

`exists` means the feature works in DigiDoc. `partly` means an approximation or format limitation remains. `missing` means it is not built. This table consolidates the Phase 0 parity review and the requested Phase 4 scope.

| Google Docs capability | Status | DigiDoc behavior / limit |
|---|---|---|
| Rich text, headings, fonts, colours, highlight | exists | 25 self-hosted fonts plus system fonts; other document readers can substitute fonts |
| Auto-capitalization and autocorrect | exists | On by default, toggles are visible; Backspace and Ctrl+Z restore the immediate correction |
| Bullets, numbered styles, nested lists, restart, checklist | exists | Real list nodes and native list definitions in DOCX; list markers are rendered by the other exporters |
| Tables, resize, rows/columns, merge/split, borders and shading | exists | Widths and cell styling are represented in all exporters within their format limits |
| Page size, orientation, margins, paragraph spacing and indents | exists | A4/A5/A3/Letter/Legal, portrait/landscape, validated ranges |
| Letterhead artwork | partly | Editor and PDF support A4 portrait artwork; DOCX, ODT, RTF and TXT omit the artwork |
| Headers, footers, page numbers | partly | All five exporters receive the values; TXT cannot paginate and emits a placeholder |
| Find and replace | exists | Browser-only; Ctrl+F, Ctrl+H, match case, replace all |
| Word and character counts, selection count | exists | Live in the editor status bar |
| Links, special characters, date, horizontal rule | exists | Link schemes restricted to http, https and mailto |
| Clean paste and paste as plain text | exists | Pasted HTML is ignored; Ctrl+Shift+V inserts clipboard text |
| Format painter | exists | Copies inline formatting to a second text selection |
| Comments, suggestion mode, version history, table of contents, footnotes, real-time co-editing | missing | Planned only; not part of this release |

## Disabled controls audit

There are no controls left with a ?coming next? placeholder. The following controls are disabled only when their action cannot apply:

- Undo and redo: disabled while their respective history stacks are empty.
- Company/personal letterhead controls: disabled when no saved artwork is available, or while page size/orientation is not A4 portrait. The layout message explains the A4 portrait restriction.
- Letterhead guide toggle: disabled if no letterhead is active; there are no guides to toggle.
- Image width, alignment, crop and remove: disabled until an image is selected; the image toolbar appears after selection.

The former Image Move action was removed because dragging the image itself already moves it. The disabled ?Info? menu item was changed to a non-interactive current-page label.

## Tests

- DOCX table width and grid XML: `DigiDocPhaseTwoTests.test_table_widths_and_merges_are_explicit_in_docx_and_odt_exports` in `attendance/test_digidoc.py`.
- Browser table controls: `DigiDocPhaseTwoTests.test_table_grid_toolbar_and_structural_controls_work_in_editor`.
- Headers, footers and page-number fields: `DigiDocPhaseTwoTests.test_headers_footers_page_numbers_export_to_all_formats`.
- Find/replace, link safety, special characters, safe paste and horizontal rule: `DigiDocPhaseTwoTests.test_phase4_find_replace_links_special_characters_and_safe_paste`.
- Browser scenario and five-file reopen checks: `DigiDocPhaseTwoTests.test_phase4_editor_downloads_all_five_formats`.
- Security attack cases: `DigiDocPhaseTwoTests.test_allow_list_accepts_safe_content_and_rejects_unknown_nodes_attrs_and_urls`, `test_link_validation_and_editor_tools_are_present`, and `test_all_export_formats_embed_scoped_inline_images_and_preserve_spacing`.
