# AI News Agent - Progress Tracker

## Phase 1: Defects 1, 2, 3, 20 + Logging ✅ COMPLETE

### Done:
1. **Defect 1** - `main.py` rewritten as thin entry point:
   - Imports and calls `src.agent.run_agent()`
   - Configures logging from `LOG_LEVEL` env var (default INFO)
   - Validates config via `config.validate()` reporting all missing vars at once
   - Non-zero exit on failure (1), zero on success/no-actionable-result (0)
   - Added `--dry-run` flag and `--verbose` flag

2. **Defect 2** - Requirements split:
   - `requirements.txt`: feedparser, google-genai, python-dotenv, requests, tenacity
   - `requirements-dev.txt`: includes requirements.txt + pytest

3. **Defect 3** - Gemini failure handling:
   - On generation failure: no approval issue created, no DB save
   - Returns `gemini_failed` status; next run retries the same article
   - Dry-run prints the error and exits cleanly

4. **Defect 20** - Dry-run implemented:
   - `--dry-run` flag runs fetch→dedup→score→select→generate
   - Prints selected article, score, and generated LinkedIn post
   - No email, no GitHub issue, no DB write
   - Also supports `DRY_RUN=1` env var (via args parsing)

5. **Logging** - Centralized logging:
   - `LOG_LEVEL` env var controls verbosity (DEBUG, INFO, WARNING, ERROR)
   - Structured format with timestamps
   - Third-party loggers (urllib3, google, feedparser) quieted unless DEBUG

### Additional fixes:
- Verified Gemini model names against official API: using `gemini-3.5-flash` (primary) and `gemini-3.5-flash-lite` (fallback)
- Added `MIN_AI_RELEVANCE` config (default 0.30) for AI-relevance gate (Defect 5, early)
- Added config validation for scoring weights sum = 1.0 and threshold ranges (Defect 19, partial)

### Tests:
- All 40 tests pass
- Updated test fixtures with AI-relevant article content to pass AI relevance filter

---

## Phase 2: Defects 4-7, 11, 12, 14, 15, 19 ⏳ IN PROGRESS

### Done:
- **Defect 4** ✅: `requests.get(timeout)` + `feedparser.parse(content)`; per-feed logging; one failed feed doesn't stop run (tested with VentureBeat 429)
- **Defect 5** ✅: Configurable AI-relevance gate (MIN_AI_RELEVANCE)
- **Defect 6** ✅: Word-boundary regex keyword matching; HTML stripping from summaries
- **Defect 7** ✅: Stronger dedup - strip utm_*/fragments, normalize URLs, compare titles against published history

### To do:
- **Defect 11**: Validate generated post (≤280 words, contains URL, 3-5 hashtags, retry once); prompt-injection guard
- **Defect 12**: Handle 429 and empty/None response from Gemini
- **Defect 14**: Verify RSS URLs alive; `python -m src.check_feeds` command
- **Defect 15**: DB context managers, index on url, store normalized URL, migration path
- **Defect 19**: Complete env-configurable all thresholds/weights; validate sum=1.0

---

## Phase 3: Defects 8, 9, 10, 13 + CI ⏳ PENDING

### To do:
- **Defect 8**: DB persistence on orphan `data` branch (workflow specified)
- **Defect 9**: Concurrency group + "already ran today" guard
- **Defect 10**: Issue-body marker injection (base64/JSON); timeout on urlopen
- **Defect 13**: LinkedIn API version from config; 401 handling; merge setup scripts
- **CI**: tests.yml, pinned actions, timeout-minutes

---

## Phase 4: Defects 16-18 + README ⏳ PENDING

### To do:
- **Defect 16**: Rotate secrets reminder; pre-run check .env not tracked; complete .env.example
- **Defect 17**: UTF-8 README; LICENSE diff check
- **Defect 18**: .gitignore: logs/, .venv/, .DS_Store, *.log

---

## Phase 5: Final Verification ⏳ PENDING

### To do:
- Full pytest run
- Dry-run test
- `git status` and `git diff --stat`
- Ask before commit

---

## Next Command to Run:
```bash
# Start Phase 2 - implement Defect 4 (fetch with requests + timeout)
```