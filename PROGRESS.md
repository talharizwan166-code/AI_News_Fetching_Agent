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
   - **Also supports `DRY_RUN=1` env var (via args parsing)** ✅ FIXED

5. **Logging** - Centralized logging:
   - `LOG_LEVEL` env var controls verbosity (DEBUG, INFO, WARNING, ERROR)
   - Structured format with timestamps
   - Third-party loggers (urllib3, google, feedparser) quieted unless DEBUG

### Additional fixes:
- Verified Gemini model names against official API: using `gemini-3.5-flash` (primary) and `gemini-3.5-flash-lite` (fallback)
- Added `MIN_AI_RELEVANCE` config (default 0.30) for AI-relevance gate (Defect 5, early)
- Added config validation for scoring weights sum = 1.0 and threshold ranges (Defect 19, partial)

### Tests:
- All 42 tests pass
- Updated test fixtures with AI-relevant article content to pass AI relevance filter

---

## Phase 2: Defects 4-7, 11, 12, 14, 15, 19 ✅ COMPLETE

### Done:
- **Defect 4** ✅: `requests.get(timeout)` + `feedparser.parse(content)`; per-feed logging; one failed feed doesn't stop run (tested with VentureBeat 429)
- **Defect 5** ✅: Configurable AI-relevance gate (MIN_AI_RELEVANCE)
- **Defect 6** ✅: Word-boundary regex keyword matching; HTML stripping from summaries
- **Defect 7** ✅: Stronger dedup - strip utm_*/fragments, normalize URLs, compare titles against published history
- **Defect 11** ✅: Validate generated post (≤280 words, contains URL, 3-5 hashtags, retry once); prompt-injection guard (in generator.py)
- **Defect 12** ✅: Handle 429 and empty/None response from Gemini; env overrides for models (in generator.py, config.py)
- **Defect 14** ✅: Verify RSS URLs alive; `python -m src.check_feeds` command (added 2 new feeds: AI Weekly, KDnuggets AI; 8/9 feeds alive)
- **Defect 15** ✅: DB context managers, index on normalized_url, store normalized URL, migration path for existing news_agent.db
- **Defect 19** ✅: Env-configurable MIN_QUALITY_THRESHOLD, MIN_AI_RELEVANCE, FETCH_TIMEOUT_SECONDS, scoring weights; validate sum=1.0 (in config.py)

### Tests:
- All 42 tests pass
- Dry-run works end-to-end

---

## Phase 3: Defects 8, 9, 10, 13 + CI ✅ COMPLETE

### Done:
- **Defect 8** ✅: DB persistence on orphan `data` branch (workflow specified) - news_agent.yml uses git worktree with data branch
- **Defect 9** ✅: Concurrency group + "already ran today" guard (checks successful runs today, skips backup if primary succeeded)
- **Defect 10** ✅: Issue-body marker injection (base64/JSON in POST_MARKER); timeout=30 on all urlopen calls
- **Defect 13** ✅: LinkedIn API version from config (LINKEDIN_API_VERSION); 401 handling with clear "token expired" error; merged setup scripts (setup_linkedin.py using /v2/userinfo, no hardcoded client ID/secret)
- **CI** ✅: tests.yml workflow with pinned actions (checkout@v4.2.2, setup-python@v5.4.0, github-script@v7.0.1), timeout-minutes on all jobs

### Tests:
- All 42 tests pass
- Dry-run works end-to-end

---

## Phase 4: Defects 16-18 + README ✅ COMPLETE

### Done:
- **Defect 16** ✅: Rotate secrets reminder (90-day check); pre-run check .env not tracked; complete .env.example with all config options
- **Defect 17** ✅: UTF-8 README (was UTF-16); LICENSE verified (standard MIT)
- **Defect 18** ✅: .gitignore updated with logs/, .venv/, .DS_Store, *.log

### Tests:
- All 42 tests pass
- Dry-run works end-to-end

---

## Phase 5: Final Verification ✅ COMPLETE

### Done:
- Full pytest run: 42/42 tests pass
- Dry-run test: Works end-to-end (fetch→dedup→score→select→generate)
- `git status`: Clean except for emailer.py fix
- `git diff --stat`: 1 file changed, 1 insertion(+), 1 deletion(-)

### Final change:
- Fixed HTML entity in emailer.py: `&` → `&` for proper HTML escaping in approval button

---

## Ready to Commit

All phases (1-5) complete. The only change is the single-line HTML entity fix in `src/emailer.py`. 

**Shall I commit this change?**