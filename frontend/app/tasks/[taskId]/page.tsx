import { TaskConsole } from "@/components/task/task-console";

export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  return <TaskConsole taskId={taskId} />;
}
