<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { derived } from 'svelte/store';

  import Header from './lib/components/Header.svelte';
  import Sidebar from './lib/components/Sidebar.svelte';
  import NotificationDisplay from './lib/components/NotificationDisplay.svelte';
  import ChatView from './lib/components/ChatView.svelte';
  import AgentStatusView from './lib/components/AgentStatusView.svelte';
  import SystemStatusView from './lib/components/SystemStatusView.svelte';
  import LogView from './lib/components/LogView.svelte';

  import { sidebarState } from './lib/stores/sidebarStore';
  import { connectSSE } from './lib/utils/coordinatorApi';

  let tab = 'chat';
  let disconnectSSE: (() => void) | null = null;

  const mainMarginClass = derived(sidebarState, ({ isMobile }) =>
    isMobile ? '' : 'md:ml-56'
  );

  onMount(() => {
    disconnectSSE = connectSSE();
  });

  onDestroy(() => {
    disconnectSSE?.();
  });
</script>

<NotificationDisplay />
<Header title="Cyber Agent" />

<div class="flex bg-zinc-950 pt-16 min-h-screen">
  <Sidebar activeTab={tab} on:selectTab={(e) => tab = e.detail} />

  <main class={`overflow-y-auto flex-1 transition-all duration-300 p-6 ${$mainMarginClass}`}>
    <!-- Les composants restent montés (état préservé) — seule la visibilité change. -->
    <div class="mx-auto max-w-5xl w-full h-[calc(100vh-6rem)]">
      <div class="h-full" class:hidden={tab !== 'chat'}>
        <ChatView />
      </div>
      <div class="h-full" class:hidden={tab !== 'tasks'}>
        <AgentStatusView />
      </div>
      <div class="h-full" class:hidden={tab !== 'status'}>
        <SystemStatusView />
      </div>
      <div class="h-full" class:hidden={tab !== 'logs'}>
        <LogView />
      </div>
      <div class="h-full" class:hidden={tab !== 'about'}>
        <p class="text-zinc-400 text-sm">cyber-agent-engine — coordinateur multi-agents.</p>
      </div>
    </div>
  </main>
</div>
