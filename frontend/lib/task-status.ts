import type { Task, TaskStatus } from "@/lib/types";

export type TaskStage = TaskStatus | "ready_for_review";

type TaskLifecycleState = Pick<Task, "status" | "attention_reason">;

export function taskStage(task: TaskLifecycleState): TaskStage {
  if (task.status === "waiting_on_you" && task.attention_reason === "awaiting_review") {
    return "ready_for_review";
  }
  return task.status;
}

export function taskNeedsAttention(task: TaskLifecycleState): boolean {
  return task.status === "waiting_on_you" || task.status === "failed";
}
