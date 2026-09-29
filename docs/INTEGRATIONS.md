# Jira and Slack schedule

Open **Global configuration → Jira & Slack schedule**. Add the Jira site URL,
email, and API token, then map each Jira project key to a Muster project with a
primary directory. Set a five-field cron expression and an IANA timezone, save,
and enable the schedule. **Run now** performs the same scan without waiting for
the next scheduled firing.

The first run scans the previous 24 hours. Jira and Slack then keep separate
last-successful cursors. A five-minute overlap plus source IDs prevents repeats
after a restart or delayed search result. Failed sources retain their cursor.
The review list shows Jira issues without a project mapping and ambiguous Slack
threads. Adding a mapping lets the next Jira scan start those issues; Slack
review items can be created or dismissed from the page.

For Slack intake, add a **user token** with `search:read` and the relevant
`channels:history`, `groups:history`, `im:history`, and `mpim:history` scopes.
Enter the user ID belonging to that token and a Jira project key for new Slack
tickets. Muster searches DMs to that user, messages mentioning the user's ID,
and threads involving the user, then reads each matching thread. Access is limited by the token's Slack
conversation permissions. Clear requests become Jira tasks; other messages
remain in the review list. A Jira issue created from Slack contains the thread
permalink and discussion.

Every mapped Jira issue creates one Muster task and one persistent agent
session. Initial comments are included in the task prompt. Later Jira comments
are sent to the same task and resume the session. Agent messages and successful
PR delivery URLs are posted back to Jira during a scan. Outbound comment IDs
are recorded so the next scan does not feed Muster's own comment back to the
agent. When an agent turn finishes with changes ready for review, the
integration invokes Muster's existing PR preparation, validation, and delivery
flow. If there are no eligible changes or delivery fails, the task remains
available for review in Muster.

Jira and Slack tokens are encrypted with Muster's host key and are not returned
by the configuration API. Integration routes require a loopback client and a
local browser origin. Remote API errors and tokens are not copied into Jira
comments.

To stop external calls, disable the integration schedule. This does not delete
existing Jira issues, PRs, tasks, or run history. To roll back the schema after
disabling it, run `alembic downgrade 0011_portable_capabilities` from `backend`
only after confirming the new integration history is no longer needed.
