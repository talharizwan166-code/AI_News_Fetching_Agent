# Client chatbot checks

1. Edit `target.json` for the endpoint, authentication and response field.
   Export `CHATBOT_API_KEY` in your shell (or remove the header if unnecessary).
   `.env.example` is documentation; Chatcheck does not load it automatically.
2. Add reviewed tests to `suite.json`. It is intentionally empty: validation
   and execution reject empty suites. Adapt cases from the bundled library to
   the client's actual policies; never assume the fictional store's facts.
3. Validate and run locally:

   ```powershell
   chatcheck validate --suite suite.json
   chatcheck run --target target.json --suite suite.json --db client.db
   chatcheck report --run <id> --db client.db --out report.html --pdf
   ```

PDF uses locally installed Playwright Chromium; install it if needed with
`python -m playwright install chromium`. No judge calls happen by default.
`python -m chatcheck` works anywhere the package is installed.

For retention, close active jobs and use
`chatcheck purge --run <id> --db client.db --yes`, or
`chatcheck purge --older-than 30 --db client.db --yes` for finished runs older
than 30 days. Purge does not delete exported reports, backups or provider logs;
apply your agreed retention policy to those copies too. Keep client databases,
reports and credentials out of source control.
