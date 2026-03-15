import { writable } from 'svelte/store';

export type SseState = 'connecting' | 'connected' | 'disconnected';

export const sseState = writable<SseState>('connecting');
