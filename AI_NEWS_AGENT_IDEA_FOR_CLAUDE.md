# AI NEWS AGENT — PROJECT IDEA

## Goal
Build a personal AI News Agent that automatically finds the most useful and relevant AI/technology news, selects the best article, generates a professional LinkedIn post with an LLM, sends the result by email, and stores published articles to avoid repetition.

## Core Pipeline

News Sources
→ Fetch Articles
→ Remove Duplicates
→ Score & Rank
→ Source-Diversity Selection
→ Select Best Article
→ Generate LinkedIn Post with AI
→ Send Email
→ Save to Database

## Main Requirements

### 1. News Fetching
Use multiple reputable AI/technology sources through RSS feeds or reliable public endpoints.

The system should:
- fetch from all sources
- handle failed feeds without stopping the whole agent
- use timeouts
- identify each article's source
- log fetch results

### 2. Deduplication
Remove duplicate articles using URL/title or another reliable method.

### 3. Scoring
Score articles based on factors such as:
- AI relevance
- developer relevance
- innovation
- freshness
- source credibility

Rank articles from highest to lowest score.

### 4. Source Diversity
Avoid allowing one source to dominate the final candidates.

Important design lesson:
If one source provides most articles (for example 90%+), simply taking the top N articles does NOT provide real diversity.

Preferred approach:
1. Group all ranked articles by source.
2. Take the best article from each source.
3. Remove articles below a configurable minimum quality threshold.
4. Sort the remaining candidates by score.
5. Select the highest-quality candidate.

Make the threshold configurable.

### 5. AI Content Generation
Use an LLM such as Gemini or another suitable provider to generate a concise, factual, professional LinkedIn post from the selected article.

The generated post should:
- be based on the article
- avoid hallucinated facts
- have a professional tone
- include relevant hashtags

### 6. Email
Send the generated post and article information through email.

Credentials must come from environment variables/secrets.

### 7. Database
Use a simple database such as SQLite to store processed/published articles and prevent unnecessary repetition.

### 8. Automation
Use GitHub Actions to run the agent automatically on a schedule.

Secrets must be stored in GitHub Secrets/environment variables, never in source code.

### 9. Testing
Create tests for:
- fetching
- deduplication
- scoring
- source diversity
- quality threshold
- AI generation
- database operations
- important edge cases

## Suggested Technology
- Python
- RSS/feedparser
- LLM API (Gemini or another suitable provider)
- SQLite
- pytest
- GitHub Actions

Use simple, maintainable architecture. Do not add unnecessary technologies.

## Expected Result

The final agent should automatically:

1. Find fresh AI news.
2. Remove duplicates.
3. Score and rank articles.
4. Prevent extreme single-source dominance.
5. Select the best article.
6. Generate a LinkedIn post using AI.
7. Email the result.
8. Save the article in the database.
9. Run automatically through GitHub Actions.

## IMPORTANT

This is a new independent project.

Do not assume any existing implementation.

First inspect the current project directory. If it is empty, design the project structure and start from the beginning.

Before major implementation, explain the proposed architecture and phases.

Do not commit or push to GitHub without explicit approval.
