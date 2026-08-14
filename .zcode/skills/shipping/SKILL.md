---
name: shipping
description: Ship the current work end-to-end — commit, build & push the image, deploy, report. Use when the user asks to ship, publish, deploy, or release the current changes.
disable-model-invocation: true
---

Ship the current work in one pass: commit → build & push → deploy → report.

1. **Gate.** Run the project's quality gates (lint, type-check, drift, tests). Any failure: stop, fix, re-run until green.
2. **Commit.** Delegate to the commit skill.
3. **Build & push.** Build and push the image with the project's tooling and default tags.
4. **Deploy.** Target `test` by default; a different environment only if the user names one. Use the project's deploy automation — its built-in health check owns verification.
5. **Report.** Image reference, environment, outcome — one line.
