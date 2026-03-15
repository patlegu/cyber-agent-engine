import { writable } from 'svelte/store';

export type TaskStatus = 'pending' | 'running' | 'done' | 'error' | 'checkpoint_wait';

export interface Task {
  id: string;
  agent: string;
  description: string;
  status: TaskStatus;
  result?: string;
  created_at: string;
  run_id?: string;
}

export const taskStore = writable<Task[]>([]);

export function upsertTask(task: Task) {
  taskStore.update(tasks => {
    const idx = tasks.findIndex(t => t.id === task.id);
    if (idx >= 0) {
      const updated = [...tasks];
      updated[idx] = task;
      return updated;
    }
    return [task, ...tasks];
  });
}
