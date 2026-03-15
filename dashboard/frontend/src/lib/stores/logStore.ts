import { writable } from 'svelte/store';

export interface LogEntry {
  ts: number;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
  logger: string;
  msg: string;
}

export const logEntries = writable<LogEntry[]>([]);

/** Timestamp de la dernière entrée reçue — évite de re-fetcher l'historique complet. */
export const logSince = writable<number>(0);
