# Proposal Tracking

Progress can track proposal repositories such as EIPs, Rust RFCs, PEPs, and Django DEPs. It parses proposal metadata, detects lifecycle events from git history, stores events in the database, and sends notifications for high-priority events.

## Event Types

- `created`: A new proposal file was added.
- `status_changed`: The proposal status changed but does not match a more specific category.
- `accepted`: The status indicates acceptance/finalization.
- `rejected`: The status indicates rejection.
- `withdrawn`: The status indicates withdrawal/abandonment, or a draft proposal file was deleted.
- `postponed`: The status indicates postponement/deferment.
- `content_modified`: The proposal file changed without a detected status change.
- `resurrected`: The status indicates resurrection.
- `superseded`: The status indicates supersession.

High-priority events that trigger notifications by default:

- `created`, `accepted`, `rejected`, `withdrawn`

## Troubleshooting

### Parsing errors

- Symptom: logs show parse failures for a proposal file.
- Fix: verify the file matches the expected format for the tracker type and the `file_pattern` filters only valid files.

### Clone/update failures

- Symptom: logs show git clone/reset failures.
- Fix: verify network access and that `repo_url` is reachable; check `branch` exists.

### AI analysis unavailable

- Symptom: event records exist but analysis summary/detail is missing.
- Fix: ensure Claude Code CLI is available and configured; proposal tracking will continue without AI analysis.
