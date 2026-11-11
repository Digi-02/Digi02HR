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

   Or download the current Windows installer from
   <https://www.libreoffice.org/download/download/> and run the MSI installer.
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
