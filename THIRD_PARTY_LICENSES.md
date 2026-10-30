# Third-party licenses

This file records third-party packages added for the DigiDoc Phase 1 and Phase 2
document pipeline. Existing project dependencies are managed in `requirements.txt`.

| Package | Pinned version | License | Use |
| --- | --- | --- | --- |
| ReportLab | 5.0.0 | BSD | Generate the controlled A4 sample and DigiDoc PDFs directly in application code. |
| charset-normalizer | 3.5.1 | MIT | Pinned permissive runtime dependency used by ReportLab's package metadata. |
| pypdfium2 | 5.14.0 | Apache-2.0 / BSD-3-Clause | Render generated PDF pages to PNG for the DigiDoc preview. The wheel bundles PDFium; include its upstream build license notices with deployment notices. |
| Lucide icons | Inline SVG paths adapted from Lucide | ISC, with the Feather MIT notice | Self-hosted, consistent outline icons in the DigiDoc ribbon and title bar. License text: `licenses/LUCIDE-LICENSE.txt`. |

The application does not use an office-suite conversion process.
