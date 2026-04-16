# Bootstrap

> OpenClaw convention: this file guides the first-run setup.
> **Self-deletes after setup is complete.** Don't put durable instructions here.

<!-- TO BE AUTHORED IN STEP 4. The bootstrap flow (locked per DECISIONS.md):

     1. Greet the user, explain what this agent does in 2 sentences
     2. Confirm Reo API key is present (manifest secret — validate by calling /segments)
     3. Ask user for their Reo segment:
        - "Paste the URL from Reo dashboard — looks like web.reo.dev/dashboard/accounts?segId=<UUID>"
        - Parse UUID from URL (or accept bare UUID)
        - Call list_segments, find + name back the segment, confirm with user
        - Persist to USER.md as default_segment_id + default_segment_name
     4. Slack pairing (Pinata handles the OAuth; agent just confirms channel)
     5. Run one test digest (reduced scope: limit=3) → post to Slack → confirm arrival
     6. Schedule: confirm cron "0 14 * * *" UTC or let user adjust
     7. Delete BOOTSTRAP.md on successful completion
-->
