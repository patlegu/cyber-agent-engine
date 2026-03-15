<script lang="ts">
  import { taskStore, type Task, upsertTask } from '../stores/taskStore';
  import { approveCheckpoint, rejectCheckpoint } from '../utils/coordinatorApi';
  import { notificationStore } from '../stores/notificationStore';

  const statusColor: Record<string, string> = {
    pending:         'text-yellow-400',
    running:         'text-blue-400',
    done:            'text-green-400',
    error:           'text-red-400',
    checkpoint_wait: 'text-orange-400',
  };

  const statusIcon: Record<string, string> = {
    pending:         '⏳',
    running:         '⚙️',
    done:            '✅',
    error:           '❌',
    checkpoint_wait: '🔐',
  };

  const statusLabel: Record<string, string> = {
    pending:         'en attente',
    running:         'en cours',
    done:            'terminé',
    error:           'erreur',
    checkpoint_wait: 'approbation requise',
  };

  async function approve(task: Task) {
    if (!task.run_id) return;
    try {
      await approveCheckpoint(task.run_id);
      upsertTask({ ...task, status: 'running' });
      notificationStore.set({ message: 'Exécution approuvée — reprise en cours.', type: 'success' });
    } catch (e: any) {
      notificationStore.set({ message: e.message, type: 'error' });
    }
  }

  async function reject(task: Task) {
    if (!task.run_id) return;
    try {
      await rejectCheckpoint(task.run_id);
      upsertTask({ ...task, status: 'error' });
      notificationStore.set({ message: 'Plan rejeté. Aucune action exécutée.', type: 'info' });
    } catch (e: any) {
      notificationStore.set({ message: e.message, type: 'error' });
    }
  }

  function clearDone() {
    taskStore.update(tasks => tasks.filter(t => t.status !== 'done'));
  }
</script>

<div class="flex flex-col gap-4">
  <div class="flex items-center justify-between">
    <h2 class="text-xl font-bold text-zinc-100">Tâches agents</h2>
    {#if $taskStore.some(t => t.status === 'done')}
      <button on:click={clearDone} class="btn-secondary text-xs">Effacer terminées</button>
    {/if}
  </div>

  {#if $taskStore.length === 0}
    <p class="text-zinc-500 text-sm">Aucune tâche en cours.</p>
  {:else}
    <div class="space-y-2">
      {#each $taskStore as task (task.id)}
        <div class="bg-zinc-800 rounded-xl p-4 flex items-start gap-3
          {task.status === 'checkpoint_wait' ? 'ring-1 ring-orange-500/60' : ''}">
          <span class="text-xl shrink-0">{statusIcon[task.status] ?? '•'}</span>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="font-semibold text-zinc-100 text-sm">{task.agent}</span>
              <span class="text-xs font-mono {statusColor[task.status] ?? 'text-zinc-400'}">
                {statusLabel[task.status] ?? task.status}
              </span>
              <span class="text-xs text-zinc-600 ml-auto">{new Date(task.created_at).toLocaleTimeString()}</span>
            </div>
            <p class="text-zinc-300 text-sm">{task.description}</p>
            {#if task.result}
              <pre class="text-zinc-500 text-xs mt-2 whitespace-pre-wrap line-clamp-4 bg-zinc-900 rounded p-2">{task.result}</pre>
            {/if}
            {#if task.status === 'checkpoint_wait' && task.run_id}
              <div class="flex gap-2 mt-3">
                <button
                  on:click={() => approve(task)}
                  class="px-3 py-1 rounded-lg bg-green-600 hover:bg-green-500 text-white text-xs font-semibold transition-colors"
                >
                  Approuver
                </button>
                <button
                  on:click={() => reject(task)}
                  class="px-3 py-1 rounded-lg bg-red-700 hover:bg-red-600 text-white text-xs font-semibold transition-colors"
                >
                  Rejeter
                </button>
              </div>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
