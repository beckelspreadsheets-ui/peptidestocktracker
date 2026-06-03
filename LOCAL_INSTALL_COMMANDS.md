# Local install commands

Use these commands after downloading the integrated zip.

```bash
mkdir -p /Users/andrewferguson/peptidestocktracker
cd /Users/andrewferguson/Downloads
unzip peptidestocktracker_prd_full_integrated.zip -d peptidestocktracker_prd_full_integrated
rsync -av --delete peptidestocktracker_prd_full_integrated/ /Users/andrewferguson/peptidestocktracker/
cd /Users/andrewferguson/peptidestocktracker
git init
git add .
git commit -m "Initial peptide stock tracker PRD with Gemini and Kimi research context"
```

Then open `/Users/andrewferguson/peptidestocktracker` in Codex and paste `prompts/codex_repo_bootstrap.md`.
