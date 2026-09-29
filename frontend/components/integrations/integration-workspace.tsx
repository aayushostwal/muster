"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";
import type { IntegrationConfig } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils";

type Form = Pick<IntegrationConfig, "enabled" | "schedule_expr" | "timezone" | "jira_base_url" | "jira_email" | "slack_user_id" | "slack_jira_project_key"> & {
  jira_token: string;
  slack_token: string;
};

const field = "field w-full";

function fromConfig(config: IntegrationConfig): Form {
  return {
    enabled: config.enabled, schedule_expr: config.schedule_expr, timezone: config.timezone,
    jira_base_url: config.jira_base_url, jira_email: config.jira_email,
    slack_user_id: config.slack_user_id, slack_jira_project_key: config.slack_jira_project_key,
    jira_token: "", slack_token: "",
  };
}

export function IntegrationWorkspace() {
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["integration-config"], queryFn: api.integrationConfig });
  const mappings = useQuery({ queryKey: ["integration-mappings"], queryFn: api.integrationMappings });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const review = useQuery({ queryKey: ["integration-review"], queryFn: api.integrationReview });
  const [draft, setDraft] = useState<Form | null>(null);
  const form = draft ?? (config.data ? fromConfig(config.data) : null);
  const [projectKey, setProjectKey] = useState("");
  const [projectId, setProjectId] = useState("");
  const [existingIssueKey, setExistingIssueKey] = useState("");
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: () => {
      if (!form) throw new Error("Configuration is not loaded");
      const { jira_token, slack_token, ...values } = form;
      return api.updateIntegrationConfig({ ...values, ...(jira_token ? { jira_token } : {}), ...(slack_token ? { slack_token } : {}) });
    },
    onSuccess: (saved) => { setError(""); queryClient.setQueryData(["integration-config"], saved); setDraft(null); },
    onError: (cause: Error) => setError(cause.message),
  });
  const run = useMutation({
    mutationFn: api.runIntegrationNow,
    onSuccess: (result) => { setError(result.error || ""); queryClient.invalidateQueries({ queryKey: ["integration-config"] }); queryClient.invalidateQueries({ queryKey: ["integration-review"] }); },
    onError: (cause: Error) => setError(cause.message),
  });
  const createMapping = useMutation({
    mutationFn: () => api.createIntegrationMapping({ jira_project_key: projectKey.trim().toUpperCase(), project_id: projectId }),
    onSuccess: () => { setProjectKey(""); setProjectId(""); setError(""); queryClient.invalidateQueries({ queryKey: ["integration-mappings"] }); },
    onError: (cause: Error) => setError(cause.message),
  });
  const deleteMapping = useMutation({
    mutationFn: api.deleteIntegrationMapping,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integration-mappings"] }),
    onError: (cause: Error) => setError(cause.message),
  });
  const approveReview = useMutation({
    mutationFn: api.createReviewTicket,
    onSuccess: () => { setError(""); queryClient.invalidateQueries({ queryKey: ["integration-review"] }); },
    onError: (cause: Error) => setError(cause.message),
  });
  const dismissReview = useMutation({
    mutationFn: api.dismissIntegrationReview,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integration-review"] }),
    onError: (cause: Error) => setError(cause.message),
  });
  const linkReview = useMutation({
    mutationFn: ({ id, key }: { id: string; key: string }) => api.linkReviewTicket(id, key),
    onSuccess: () => { setExistingIssueKey(""); setError(""); queryClient.invalidateQueries({ queryKey: ["integration-review"] }); },
    onError: (cause: Error) => setError(cause.message),
  });

  const change = <K extends keyof Form>(key: K, value: Form[K]) => setDraft((current) => ({ ...(current ?? fromConfig(config.data!)), [key]: value }));
  if (config.isError) return <main className="mx-auto max-w-4xl p-6 text-red-300">{config.error.message}</main>;
  if (config.isPending || !form) return <main className="mx-auto max-w-4xl p-6 text-slate-400">Loading integrations…</main>;

  return <main className="mx-auto max-w-4xl space-y-6 px-5 py-8 md:px-8">
    <div><h1 className="text-2xl font-semibold text-white">Jira & Slack schedule</h1><p className="mt-2 text-sm text-slate-400">Scan since the last successful run, create tasks from Jira, and turn directed Slack requests into Jira tickets.</p></div>
    <form className="surface space-y-5 rounded-panel p-5 md:p-7" onSubmit={(event: FormEvent) => { event.preventDefault(); save.mutate(); }}>
      <h2 className="text-lg font-medium text-white">Connection and time</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-xs text-slate-300">Schedule (five-field cron)<input className={field} value={form.schedule_expr} onChange={(event) => change("schedule_expr", event.target.value)} /></label>
        <label className="text-xs text-slate-300">Timezone<input className={field} value={form.timezone} onChange={(event) => change("timezone", event.target.value)} placeholder="Asia/Kolkata" /></label>
        <label className="text-xs text-slate-300">Jira site URL<input className={field} value={form.jira_base_url || ""} onChange={(event) => change("jira_base_url", event.target.value)} placeholder="https://company.atlassian.net" /></label>
        <label className="text-xs text-slate-300">Jira email<input className={field} value={form.jira_email || ""} onChange={(event) => change("jira_email", event.target.value)} /></label>
        <label className="text-xs text-slate-300">Jira API token {config.data.has_jira_token && <span className="text-signal-300">· saved</span>}<input className={field} type="password" autoComplete="new-password" value={form.jira_token} onChange={(event) => change("jira_token", event.target.value)} placeholder="Leave blank to keep saved token" /></label>
        <label className="text-xs text-slate-300">Slack user token {config.data.has_slack_token && <span className="text-signal-300">· saved</span>}<input className={field} type="password" autoComplete="new-password" value={form.slack_token} onChange={(event) => change("slack_token", event.target.value)} placeholder="Leave blank to keep saved token" /></label>
        <label className="text-xs text-slate-300">Your Slack user ID<input className={field} value={form.slack_user_id || ""} onChange={(event) => change("slack_user_id", event.target.value)} placeholder="U0123456789" /></label>
        <label className="text-xs text-slate-300">Jira project for Slack tickets<input className={field} value={form.slack_jira_project_key || ""} onChange={(event) => change("slack_jira_project_key", event.target.value.toUpperCase())} placeholder="TEAM" /></label>
      </div>
      <label className="flex items-center gap-3 text-sm text-slate-200"><input type="checkbox" checked={form.enabled} onChange={(event) => change("enabled", event.target.checked)} /> Enable schedule</label>
      <p className="text-xs text-slate-500">First run scans the previous 24 hours. Later runs use separate Jira and Slack cursors. Tokens are encrypted and never returned by this API.</p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      <div className="flex flex-wrap gap-3"><Button type="submit" loading={save.isPending}>Save settings</Button><Button type="button" variant="ghost" loading={run.isPending} onClick={() => run.mutate()}>Run now</Button></div>
      <p className="text-xs text-slate-500">Last run: {formatDateTime(config.data.last_run_at)} · {config.data.last_status || "Never"}</p>
    </form>

    <section className="surface space-y-4 rounded-panel p-5 md:p-7">
      <h2 className="text-lg font-medium text-white">Jira project routing</h2>
      <p className="text-xs text-slate-500">Only mapped Jira projects launch agents. Each Muster project needs a primary directory.</p>
      <form className="flex flex-wrap gap-3" onSubmit={(event) => { event.preventDefault(); createMapping.mutate(); }}>
        <input className={field + " sm:w-36"} aria-label="Jira project key" placeholder="Jira key" value={projectKey} onChange={(event) => setProjectKey(event.target.value)} required />
        <select className={field + " sm:w-64"} aria-label="Muster project" value={projectId} onChange={(event) => setProjectId(event.target.value)} required><option value="">Choose Muster project</option>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
        <Button type="submit" loading={createMapping.isPending}>Add mapping</Button>
      </form>
      <div className="space-y-2">{mappings.data?.items.map((mapping) => <div key={mapping.id} className="flex items-center justify-between rounded-lg border border-white/10 p-3 text-sm text-slate-300"><span>{mapping.jira_project_key} → <Link className="text-signal-300" href={`/projects/${mapping.project_id}`}>{projects.data?.items.find((project) => project.id === mapping.project_id)?.name || mapping.project_id}</Link></span><Button variant="ghost" onClick={() => deleteMapping.mutate(mapping.id)}>Remove</Button></div>)}</div>
    </section>

    <section className="surface space-y-3 rounded-panel p-5 md:p-7"><h2 className="text-lg font-medium text-white">Needs review</h2><p className="text-xs text-slate-500">Unmapped Jira issues and Slack messages without a clear action appear here.</p>{review.data?.items.length ? review.data.items.map((item) => <div key={item.id} className="rounded-lg border border-white/10 p-3 text-xs text-slate-300"><span className="font-semibold">{item.source} · {item.external_id}</span><p className="mt-2 whitespace-pre-wrap">{item.detail}</p>{item.source === "slack_thread" && <div className="mt-3 space-y-2"><div className="flex gap-2"><Button variant="ghost" loading={approveReview.isPending} onClick={() => approveReview.mutate(item.id)}>{item.status === "pending" ? "Finish linking" : "Create Jira ticket"}</Button>{item.status === "needs_review" && <Button variant="ghost" loading={dismissReview.isPending} onClick={() => dismissReview.mutate(item.id)}>Dismiss</Button>}</div><div className="flex gap-2"><input className={field + " max-w-36"} aria-label="Existing Jira issue key" placeholder="Existing Jira key" value={existingIssueKey} onChange={(event) => setExistingIssueKey(event.target.value.toUpperCase())} /><Button variant="ghost" loading={linkReview.isPending} disabled={!existingIssueKey} onClick={() => linkReview.mutate({ id: item.id, key: existingIssueKey })}>Link existing</Button></div></div>}</div>) : <p className="text-sm text-slate-500">Nothing waiting.</p>}</section>
  </main>;
}
