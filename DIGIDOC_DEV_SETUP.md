# DigiDoc development tools

These tools are for local development and tests only. They are not installed or
used by the production application.

## Windows setup

1. Create or activate the repository virtual environment, then install the
   development Python dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

   The development requirements include `python-docx`, which reopens generated
   Word documents in the export tests.

2. Install LibreOffice Writer for headless DOCX conversion. With Windows
   Package Manager:

   ```powershell
   winget install --id TheDocumentFoundation.LibreOffice --exact
   ```

   Or download the Windows x86-64 MSI from
   <https://www.libreoffice.org/download/download/?type=win-x86>. If Windows
   Installer reports error 1618, close other Office installers, restart Windows
   after the active installation has completed, then run the downloaded MSI as
   Administrator and choose Typical, Next, Install, Finish. Windows may ask
   for administrator approval.
   The tests look for `soffice` on `PATH` and in the standard
   `C:\Program Files\LibreOffice\program` directory. If installed elsewhere,
   add its `program` directory to `PATH` before running the tests.

3. Run the DigiDoc tests:

   ```powershell
   .\.venv\Scripts\python.exe manage.py test attendance.test_digidoc
   ```

   When LibreOffice is present, DOCX tests use an isolated user profile and
   convert each generated file to PDF in headless mode. Without LibreOffice,
   the tests still validate the DOCX ZIP, XML, relationships, and reopen it with
   `python-docx`, while reporting the conversion as unavailable.

To check a generated file manually, run:

```powershell
& "C:\Program Files\LibreOffice\program\soffice.com" --headless --convert-to pdf --outdir $env:TEMP sample.docx
```

The command creates `sample.pdf` when conversion succeeds. Check that the PDF
opens and that list levels, restarts, images, tables, links and formatting look
correct. In Word, also verify that a long document, an empty document, empty
list items, a list after a table, special characters, and a letterhead document
open without a repair warning.
