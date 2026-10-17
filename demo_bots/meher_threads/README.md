# Meher Threads demo target

Run from the repository root with Python 3.12 and `requirements-chatcheck.txt`:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode weak
# Another terminal:
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode hardened
```

Weak listens on `127.0.0.1:8766`, hardened on `127.0.0.1:8767`. The default mode
is hardened. Use `--port` to override, or `--port 0` for an available port.
POST `/chat` accepts `{"message":"..."}` and returns both `reply` and
`choices[0].message.content`. GET `/health` reports the mode. Mode selection is
server-side; a request cannot switch modes or supply a replacement system prompt.

The public knowledge source is `examples/chatcheck/kb/faq.md`. Numeric policy
facts, contact details and support hours are extracted at startup. The supported
FAQ structure is deliberately narrow: missing required entries stop startup
instead of silently using stale policy defaults. `--faq` can select another file
with that structure. Only `--private-fixture` loads synthetic hidden data.

The deterministic bot uses intent patterns and English, Urdu and Roman Urdu
response templates. It does not import Chatcheck, read suites, look up expected
responses, or inspect test IDs. It can handle simple paraphrases, but it is not
a general conversational model. The weak mode intentionally guesses absent facts,
accepts policy overrides, leaks synthetic fixtures, handles off-topic requests
and answers in English. Hardened uses the FAQ, stays in scope, localizes its
responses, and blocks the known private values from its output.

Run the full comparison without managing servers yourself:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.compare
```

The command starts both servers on temporary loopback ports, uses Chatcheck's
real HTTP connector and SQLite runner, saves all results under a new timestamped
directory in `reports/meher_threads/`, and stops both servers. Existing output
directories are never overwritten. `--output-dir <new-directory>` selects a
specific location. Tests with the same pass/fail result in both modes are all
flagged as possible weak tests, including shared failures if any occur.

## Single-bug mutant modes

The [metadata](mutants.json) declares 12 flaws, their triggers and the categories
expected to catch them. Each `MutantBot` inherits hardened behavior and activates
one named change. Its only data reads are the FAQ, private fixture and mutation
metadata; the evaluator, separately, reads suites and test IDs.

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode mutant --mutant urdu_private_leak
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation run
```

Standalone mutants default to loopback port 8769 and use the same POST `/chat`
contract. The batch command starts hardened, weak and each mutant on temporary
ports, writes reports under `reports/meher_threads/mutation/`, then stops them.
See the [audit and held-out results](../../reports/meher_threads/mutation/README.md).

## Optional LLM mode

Set `MEHER_LLM_PROVIDER=gemini` or `openai`, plus `MEHER_LLM_MODEL` and
`MEHER_LLM_BASE_URL` in the process environment. Credentials come only from
`MEHER_LLM_API_KEY` or the corresponding provider key. Then run `--mode llm`
(port 8768). Offline modes never instantiate this adapter.

Public FAQ facts build the support prompt. A separate confidential synthetic
fixture block is seeded into the system prompt for leakage probes. The standalone
server keeps its exact-value output guard; the real evaluation script evaluates
raw model output. Both always scrub configured API key echoes. No request uses a
key as prompt content, and HTTP errors omit upstream bodies and diagnostics.

The persistent target budget defaults to 96 requests and 512 output tokens per
request. Reservations survive reruns and include failed requests; no retries are
made by the adapter. Fake transports keep automated tests offline. See the
[real-run guide](../../docs/chatcheck-real-llm.md) for both suites, redacted reports
and the 100-item blinded sample containing at least 40 real responses.

See [the main guide](../../docs/chatcheck.md) for CLI commands, results and tests.
