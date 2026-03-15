import { writable } from 'svelte/store';

export type NotificationType = 'success' | 'error' | 'info';

export interface Notification {
  message: string;
  type: NotificationType;
}

export const notificationStore = writable<Notification | null>(null);

export function notify(message: string, type: NotificationType = 'info') {
  notificationStore.set({ message, type });
  setTimeout(() => notificationStore.set(null), 5000);
}
