# User

> OpenClaw convention: this file is the agent's memory of the user.
> **Ships blank.** Populated during bootstrap and updated over time as the
> agent learns user preferences (digest format tweaks, segment changes, etc.).

<!-- Bootstrap will populate this with:

     default_segment_id: <UUID>
     default_segment_name: <human-readable name>
     tz: <IANA timezone, e.g. Asia/Kolkata>
     slack_channel: <#channel-name>
     digest_limit: 5                 # accounts per digest
     web3_only: true                 # toggle via /adjust command
     schedule: "0 14 * * *"          # cron expression
     web3_domains_extensions: []     # user-added allow-list domains

     Additional free-form observations (e.g. "user prefers shorter messages").
-->
