# Recurring agents

Open **Global configuration → Recurring agents**. Write the prompt that the agent should receive on each run, give it a name, select a project and either Codex or Claude Code, choose a model and thinking level, then choose a number of minutes, hours, or days. The project needs a primary read/write directory. Each firing creates a new task and starts a fresh CLI session with the saved model and thinking level, so its run and output appear on the project board.

The agent receives the capabilities available to that project: its bound directories, enabled tools, skills, and MCP connectors. To triage Jira or Slack, connect those services as MCP connectors and describe the workflow in the prompt. The prompt can ask the agent to search, summarize, create tickets, or take other actions that its configured capabilities allow. Muster does not automatically grant access to an unconfigured connector.

Use **Run now** to start a session immediately, including when the agent is paused. **Edit** changes future runs; past task sessions keep their original settings. **Pause** stops scheduled runs without deleting past tasks. Intervals range from 1 minute to 365 days and retain their phase across backend restarts. Existing legacy cron jobs remain editable and runnable; editing one keeps its cron expression unless you choose **Use interval**. The previous dedicated Jira and Slack poller is no longer scheduled on startup or by the recurring agent page. Its stored settings and history are retained.

The recurring-agent list shows jobs from every project on page load, including paused jobs. Use the project filter above the list to narrow it. The project selected in the new-agent form does not hide other saved jobs.
