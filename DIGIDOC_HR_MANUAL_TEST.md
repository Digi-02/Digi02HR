# DigiDoc manual test for HR

Use a test employee account and a copy of the company letterhead. Download the Word file and inspect it in Microsoft Word.

1. Open DigiDoc, create a document, and type `dear HR. this is a test letter.`. Expected: the first letter and the first letter after the full stop are capitalized. Turn Auto-capitalize off, type another sentence, and confirm it stays as typed. Turn it back on.
2. Type `teh `, `dont `, and `(c) `. Expected: the configured corrections appear. Press Backspace immediately after one correction; the original word returns. Repeat with Ctrl+Z.
3. Select the letter text, choose a different font, make one phrase bold and italic, and apply the format painter to another phrase. Expected: the chosen font and formatting appear and are retained after saving.
4. Insert a numbered list with two items, change its style, restart it, and add a nested bullet list and a checklist. Expected: list markers, nesting, and restart are visible and stay after saving.
5. Insert a 2 by 3 table. Add and delete rows and columns on both sides. Set its width, border thickness, border colour, and cell shading. Merge two cells and split them again. Expected: every table command changes the selected table, and the table keeps its chosen width.
6. Open Layout. Change page size, orientation and margins; set paragraph spacing before/after and left/right/first-line indents. Expected: page and paragraph layout changes. With a non-A4 or landscape page selected, letterhead insertion is disabled and the message explains why. If a letterhead is active, switching page size warns and offers removal before applying.
7. Return to A4 portrait, enable the company letterhead, and enter header and footer text. Turn on Page X of Y. Expected: the editor preview repeats the header and footer, places them in the letterhead-safe margin area, and page numbering matches the page count.
8. Press Ctrl+F and find a word. Press Ctrl+H, enable Match case, enter a replacement and choose Replace all. Expected: only matching case is replaced, all changes happen in the browser, and the document count updates.
9. Select text and insert a link. Try an https URL, a mailto address, then a `javascript:` URL. Expected: the first two work and the unsafe URL is rejected. The generated link opens with `noopener noreferrer`.
10. Open Symbols and insert a symbol; insert today's date and a horizontal line. Expected: each appears at the caret.
11. Copy rich text including an image or style from another page and use Paste. Repeat with Ctrl+Shift+V. Expected: unsafe HTML and outside styles do not run or enter the document; plain text is inserted with Ctrl+Shift+V.
12. Select a paragraph and inspect the status bar. Expected: word count, character count and selected word/character counts update as the selection changes.
13. Download DOCX, ODT, PDF, RTF and TXT. Reopen each. Expected: all files open; lists and tables remain readable. DOCX/ODT/RTF/PDF have real page fields; TXT uses a page-count placeholder because plain text has no pages.
14. In Word, inspect table widths (one, two and many columns), merged cells, a table inside a list, empty list items, nested and restarted numbering, unicode, links, headers/footers and page fields. Expected: DOCX opens without a repair warning and table widths are not squeezed around their text.
15. Check the disabled states. Expected: Undo/Redo are disabled only when their history stack is empty; letterhead controls are disabled only when no artwork exists or the page is not A4 portrait; image controls are disabled until an image is selected. No other ribbon button is a dead control.

## Known limits to record

- Letterhead artwork is currently included in PDF and the editor preview only. DOCX, ODT, RTF and TXT contain the document content but not the letterhead image.
- TXT has no pages, so it cannot calculate real Page X of Y values or repeat a footer per printed page.
- DOCX is the reference download for Word fidelity. Word can substitute a font if the selected self-hosted font is not installed on that computer.
- Comments, suggestions, version history, table of contents, footnotes and real-time co-editing are not in this phase.
