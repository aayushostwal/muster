import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getProject } from "../api/client";
import DirectoriesTab from "../components/project-tabs/DirectoriesTab";
import McpServersTab from "../components/project-tabs/McpServersTab";
import ToolsTab from "../components/project-tabs/ToolsTab";
import ArtifactsTab from "../components/project-tabs/ArtifactsTab";
import CronJobsTab from "../components/project-tabs/CronJobsTab";
import SecretsTab from "../components/project-tabs/SecretsTab";

const TABS = [
  "Directories",
  "MCP Servers",
  "Tools",
  "Artifacts",
  "Cron Jobs",
  "Secrets",
] as const;

type Tab = (typeof TABS)[number];

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("Directories");

  const projectQuery = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  if (!id) return null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{projectQuery.data?.name ?? "Project"}</h1>
          {projectQuery.data?.description && (
            <div className="muted">{projectQuery.data.description}</div>
          )}
        </div>
        <Link to={`/projects/${id}/board`}>
          <button className="primary">Task board →</button>
        </Link>
      </div>

      {projectQuery.isLoading && <div className="loading">Loading project…</div>}
      {projectQuery.isError && (
        <div className="error-banner">{(projectQuery.error as Error).message}</div>
      )}

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`tab ${tab === activeTab ? "active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="card">
        {activeTab === "Directories" && <DirectoriesTab projectId={id} />}
        {activeTab === "MCP Servers" && <McpServersTab projectId={id} />}
        {activeTab === "Tools" && <ToolsTab projectId={id} />}
        {activeTab === "Artifacts" && <ArtifactsTab projectId={id} />}
        {activeTab === "Cron Jobs" && <CronJobsTab projectId={id} />}
        {activeTab === "Secrets" && <SecretsTab projectId={id} />}
      </div>
    </div>
  );
}
