<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import { get } from 'svelte/store';
  import { logEntries, logSince } from '../stores/logStore';
  import { fetchLogs } from '../utils/coordinatorApi';

  // Filtre de niveau affiché
  let levelFilter: 'ALL' | 'INFO' | 'WARNING' | 'ERROR' = 'ALL';
  // Suivi auto du bas
  let autoScroll = true;
  let logContainer: HTMLElement;
  let interval: ReturnType<typeof setInterval>;

  const LEVEL_ORDER: Record<string, number> = {
    DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4,
  };

  const LEVEL_CLASS: Record<string, string> = {
    DEBUG:    'text-zinc-500',
    INFO:     'text-zinc-300',
    WARNING:  'text-yellow-400',
    ERROR:    'text-red-400',
    CRITICAL: 'text-red-500 font-bold',
  };

  $: filtered = $logEntries.filter(
    (e) => levelFilter === 'ALL' || LEVEL_ORDER[e.level] >= LEVEL_ORDER[levelFilter],
  );

  async function poll() {
    try {
      const since = get(logSince);
      const entries = await fetchLogs(since);
      if (entries.length === 0) return;

      const maxTs = entries.reduce((m, e) => Math.max(m, e.ts), since);
      logSince.set(maxTs);
      logEntries.update((prev) => [...prev, ...entries].slice(-2000));

      if (autoScroll) {
        await tick();
        logContainer?.scrollTo({ top: logContainer.scrollHeight });
      }
    } catch {
      // erreur réseau — silencieux
    }
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString('fr-FR', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }

  function handleScroll() {
    if (!logContainer) return;
    const { scrollTop, scrollHeight, clientHeight } = logContainer;
    autoScroll = scrollHeight - scrollTop - clientHeight < 40;
  }

  function scrollToBottom() {
    autoScroll = true;
    logContainer?.scrollTo({ top: logContainer.scrollHeight, behavior: 'smooth' });
  }

  function clearLogs() {
    logEntries.set([]);
  }

  onMount(() => {
    interval = setInterval(poll, 2000);
    poll();
  });

  onDestroy(() => clearInterval(interval));
</script>

<div class="flex flex-col h-full gap-3">
  <!-- Barre d'outils -->
  <div class="flex items-center gap-3 flex-wrap">
    <span class="text-zinc-400 text-xs font-medium uppercase tracking-wide">Niveau</span>
    {#each ['ALL', 'INFO', 'WARNING', 'ERROR'] as lvl}
      <button
        class="px-2 py-0.5 rounded text-xs font-mono border transition-colors
               {levelFilter === lvl
                 ? 'bg-zinc-700 border-zinc-500 text-white'
                 : 'bg-transparent border-zinc-700 text-zinc-400 hover:border-zinc-500'}"
        on:click={() => (levelFilter = lvl)}
      >
        {lvl}
      </button>
    {/each}

    <div class="flex-1"></div>

    <span class="text-zinc-600 text-xs">{filtered.length} ligne{filtered.length !== 1 ? 's' : ''}</span>

    <button
      class="px-2 py-0.5 rounded text-xs border border-zinc-700 text-zinc-400
             hover:border-zinc-500 hover:text-zinc-200 transition-colors"
      on:click={clearLogs}
      title="Effacer"
    >
      Effacer
    </button>

    {#if !autoScroll}
      <button
        class="px-2 py-0.5 rounded text-xs border border-zinc-600 text-zinc-300
               hover:border-zinc-400 transition-colors"
        on:click={scrollToBottom}
        title="Suivre"
      >
        ↓ Suivre
      </button>
    {/if}
  </div>

  <!-- Zone de logs -->
  <div
    bind:this={logContainer}
    on:scroll={handleScroll}
    class="flex-1 overflow-y-auto font-mono text-xs bg-zinc-900 rounded-lg border border-zinc-800 p-3 space-y-0.5"
  >
    {#if filtered.length === 0}
      <p class="text-zinc-600 italic">Aucun log à afficher.</p>
    {:else}
      {#each filtered as entry (entry.ts + entry.msg)}
        <div class="flex gap-2 leading-5">
          <span class="text-zinc-600 shrink-0 select-none">{formatTime(entry.ts)}</span>
          <span class="shrink-0 w-16 {LEVEL_CLASS[entry.level] ?? 'text-zinc-300'}">{entry.level}</span>
          <span class="text-zinc-500 shrink-0 truncate max-w-[14ch]" title={entry.logger}>{entry.logger}</span>
          <span class="{LEVEL_CLASS[entry.level] ?? 'text-zinc-300'} break-all">{entry.msg}</span>
        </div>
      {/each}
    {/if}
  </div>
</div>
