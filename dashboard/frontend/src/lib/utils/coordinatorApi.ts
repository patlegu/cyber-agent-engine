import { notificationStore } from '../stores/notificationStore';
import { upsertTask } from '../stores/taskStore';
import { sseState } from '../stores/sseStore';

// En dev : pointer vers le coordinateur via VITE_COORDINATOR_URL (ex: http://localhost:3001)
// En prod : chaîne vide → URLs relatives → même origine que FastAPI
const API_URL = import.meta.env.VITE_COORDINATOR_URL || '';

// Si VITE_DASHBOARD_TOKEN est défini, il est transmis en Bearer header (fetch)
// et en query param ?token= (EventSource qui ne supporte pas les headers custom).
const TOKEN: string = import.meta.env.VITE_DASHBOARD_TOKEN || '';

function authHeaders(): Record<string, string> {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

let _es: EventSource | null = null;

/**
 * Ouvre une connexion SSE vers le coordinateur et alimente les stores.
 * N'affiche le toast d'erreur qu'à la première déconnexion, et un toast
 * de succès à la reconnexion — évite le spam de notifications en cas de retry.
 * Retourne la fonction de déconnexion.
 */
export function connectSSE(): () => void {
  if (_es) _es.close();

  const sseUrl = `${API_URL}/events${TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ''}`;
  _es = new EventSource(sseUrl);
  sseState.set('connecting');

  _es.onopen = () => {
    sseState.update((prev) => {
      if (prev === 'disconnected') {
        notificationStore.set({ message: 'Connexion au coordinateur rétablie.', type: 'success' });
      }
      return 'connected';
    });
  };

  _es.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      if (event.type === 'notification') {
        notificationStore.set({ message: event.message, type: event.status ?? 'info' });
      } else if (event.type === 'task_update') {
        upsertTask(event.task);
      }
    } catch {
      // payload non-JSON ignoré
    }
  };

  _es.onerror = () => {
    sseState.update((prev) => {
      if (prev !== 'disconnected') {
        notificationStore.set({ message: 'Connexion au coordinateur perdue — reconnexion…', type: 'error' });
      }
      return 'disconnected';
    });
  };

  return () => {
    _es?.close();
    _es = null;
    sseState.set('disconnected');
  };
}

/**
 * Envoie une commande texte au coordinateur et retourne la réponse.
 */
export async function sendCommand(command: string): Promise<string> {
  const resp = await fetch(`${API_URL}/api/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ command }),
  });
  if (!resp.ok) throw new Error(`Coordinateur: ${resp.status} ${await resp.text()}`);
  const data = await resp.json();
  return data.reply ?? '';
}

/**
 * Approuve les actions en attente d'un checkpoint et reprend l'exécution.
 */
export async function approveCheckpoint(run_id: string): Promise<void> {
  const resp = await fetch(`${API_URL}/coordinator/checkpoint/${run_id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ comment: 'Approuvé via dashboard' }),
  });
  if (!resp.ok) throw new Error(`Approve failed: ${resp.status} ${await resp.text()}`);
}

/**
 * Rejette les actions en attente d'un checkpoint et avorte le plan.
 */
export async function rejectCheckpoint(run_id: string): Promise<void> {
  const resp = await fetch(`${API_URL}/coordinator/checkpoint/${run_id}/reject`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!resp.ok) throw new Error(`Reject failed: ${resp.status} ${await resp.text()}`);
}

/**
 * Récupère les entrées de log postérieures à `since` (timestamp UNIX secondes).
 * Retourne un tableau trié par ordre chronologique.
 */
export async function fetchLogs(since: number = 0): Promise<Array<{
  ts: number;
  level: string;
  logger: string;
  msg: string;
}>> {
  const resp = await fetch(`${API_URL}/api/logs?since=${since}`, {
    headers: authHeaders(),
  });
  if (!resp.ok) throw new Error(`Logs fetch failed: ${resp.status}`);
  const data = await resp.json();
  return data.logs ?? [];
}
