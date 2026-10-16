# Chatcheck

Chatcheck runs local chatbot checks, optional rubric judging, blinded human
review and client reports. Python 3.12 or later is required.

```powershell
python -m pip install -e ".[dev]"
chatcheck init client-workspace
```

The `chatcheck` command and `python -m chatcheck` expose the same CLI. PDF reports
use locally installed Playwright Chromium. The optional `[pdf]` extra installs
WeasyPrint as a fallback. Bundled suites, report templates and remediation guidance
are included in wheels; credentials, databases and client reports are not.

See `docs/chatcheck-operations.md` in the source repository for setup, testing,
PDF export, workspace initialization and client data-retention procedures.
