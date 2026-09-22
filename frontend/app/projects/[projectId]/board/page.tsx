import { TaskBoard } from "@/components/board/task-board";

export default async function BoardPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <TaskBoard projectId={projectId} />;
}
