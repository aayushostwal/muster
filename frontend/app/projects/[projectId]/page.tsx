import { ProjectWorkspace } from "@/components/project/project-workspace";

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <ProjectWorkspace projectId={projectId} />;
}
