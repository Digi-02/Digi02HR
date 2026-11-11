# DigiDoc export fidelity

| Feature | DOCX | PDF | RTF | TXT |
|---|---|---|---|---|
| Bulleted lists, nesting, empty items | Exact native numbering | Exact list layout | Approximate visible markers; nesting is flattened | Approximate markers and nesting |
| Ordered lists, nesting, restart | Exact native numbering and restart | Exact numbering and restart | Approximate visible numbering; restart/nesting are not preserved | Approximate numbering and nesting |
| Paragraph spacing and indents | Exact | Exact | Approximate (spacing only) | Approximate blank lines; indents omitted |
| Tables | Exact editable tables | Exact table layout | Not supported | Approximate tab-separated cells |
| Images | Embedded | Embedded | Embedded inline | Approximate alt-text labels |
| Letterheads | Not supported | Exact page placement | Not supported | Not supported |
| Links | Clickable | Clickable | Not supported | Not supported |
| Bold, italic, underline, strike | Exact | Exact | Not supported | Not supported |
| Font, size, text colour, highlight | Preserved where supported | Preserved where supported | Not supported | Not supported |
| Page size, orientation, margins | Exact | Exact | Not supported | Not supported |
