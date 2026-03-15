<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  interface SystemStatus {
    system: { cpu_percent: number; memory_percent: number; disk_percent: number };
    network: { internet: boolean; opnsense: boolean; opnsense_details: string };
    agent: { vllm_status: boolean; model_loaded: boolean };
  }

  let status: SystemStatus | null = null;
  let error = '';
  let interval: ReturnType<typeof setInterval>;

  async function fetchStatus() {
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      status = await resp.json();
      error = '';
    } catch (e: any) {
      error = e.message;
    }
  }

  onMount(() => {
    fetchStatus();
    interval = setInterval(fetchStatus, 5000);
  });

  onDestroy(() => clearInterval(interval));

  function bar(pct: number): string {
    if (pct > 85) return 'bg-red-500';
    if (pct > 60) return 'bg-yellow-400';
    return 'bg-green-500';
  }
</script>

<div class="flex flex-col gap-6">
  <h2 class="text-xl font-bold text-zinc-100">État système</h2>

  {#if error}
    <p class="text-red-400 text-sm">{error}</p>
  {:else if !status}
    <p class="text-zinc-500 text-sm animate-pulse">Chargement…</p>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {#each [
        { label: 'CPU', value: status.system.cpu_percent },
        { label: 'Mémoire', value: status.system.memory_percent },
        { label: 'Disque', value: status.system.disk_percent },
      ] as stat}
        <div class="bg-zinc-800 rounded-xl p-4">
          <div class="flex justify-between text-sm text-zinc-300 mb-2">
            <span>{stat.label}</span>
            <span class="font-mono">{stat.value.toFixed(1)}%</span>
          </div>
          <div class="w-full bg-zinc-700 rounded-full h-2">
            <div class="h-2 rounded-full transition-all {bar(stat.value)}" style="width:{stat.value}%"></div>
          </div>
        </div>
      {/each}
    </div>

    <div class="bg-zinc-800 rounded-xl p-4 space-y-2 text-sm">
      <h3 class="font-semibold text-zinc-200 mb-2">Réseau</h3>
      <div class="flex gap-2 items-center">
        <span>{status.network.internet ? '✅' : '❌'}</span>
        <span class="text-zinc-300">Internet</span>
      </div>
      <div class="flex gap-2 items-center">
        <span>{status.network.opnsense ? '✅' : '❌'}</span>
        <span class="text-zinc-300">OPNsense — {status.network.opnsense_details}</span>
      </div>
    </div>

    <div class="bg-zinc-800 rounded-xl p-4 space-y-2 text-sm">
      <h3 class="font-semibold text-zinc-200 mb-2">Agent IA</h3>
      <div class="flex gap-2 items-center">
        <span>{status.agent.vllm_status ? '✅' : '❌'}</span>
        <span class="text-zinc-300">vLLM</span>
      </div>
      <div class="flex gap-2 items-center">
        <span>{status.agent.model_loaded ? '✅' : '❌'}</span>
        <span class="text-zinc-300">Modèle chargé</span>
      </div>
    </div>
  {/if}
</div>
