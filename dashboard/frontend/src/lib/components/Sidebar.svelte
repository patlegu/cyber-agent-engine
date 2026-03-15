<script lang="ts">
  import { onMount, createEventDispatcher } from 'svelte';
  import { sidebarState } from '../stores/sidebarStore';

  export let activeTab: string = '';

  const dispatch = createEventDispatcher();

  const navItems = [
    { icon: '💬', label: 'Coordinateur', key: 'chat' },
    { icon: '⚙️', label: 'Tâches agents', key: 'tasks' },
    { icon: '📋', label: 'Logs', key: 'logs' },
    { icon: '📡', label: 'État système', key: 'status' },
    { icon: 'ℹ️', label: 'À propos', key: 'about' },
  ];

  let isMobile = false;

  onMount(() => {
    const checkScreen = () => {
      const mobile = window.innerWidth < 768;
      isMobile = mobile;
      sidebarState.update(state => ({ ...state, isMobile: mobile }));
    };
    checkScreen();
    window.addEventListener('resize', checkScreen);
    return () => window.removeEventListener('resize', checkScreen);
  });

  $: sidebarState.update(state => ({
    ...state,
    showSidebar: isMobile ? false : true,
  }));

  function selectTab(key: string) {
    dispatch('selectTab', key);
    if (isMobile) sidebarState.update(s => ({ ...s, showSidebar: false }));
  }
</script>

{#if isMobile && $sidebarState.showSidebar}
  <button
    type="button"
    class="fixed inset-0 bg-black bg-opacity-40 z-30"
    on:click={() => sidebarState.update(s => ({ ...s, showSidebar: false }))}
    aria-label="Fermer le menu"
    tabindex="-1"
  ></button>
{/if}

<nav class={`bg-zinc-900 text-white
  ${$sidebarState.isMobile ? 'w-16' : 'w-56'}
  h-[calc(100vh-4rem)] flex flex-col fixed top-16 left-0 z-40
  shadow-lg transition-all duration-300 ease-in-out
  ${$sidebarState.isMobile && !$sidebarState.showSidebar ? '-translate-x-full' : 'translate-x-0'}`}>

  <div class="flex-grow overflow-y-auto space-y-1 mt-2">
    {#each navItems as item (item.key)}
      <button
        on:click={() => selectTab(item.key)}
        type="button"
        title={item.label}
        class="relative group flex items-center px-4 py-3 gap-3 w-full text-left text-gray-300 hover:bg-gray-700 hover:text-white transition-colors duration-150
          {activeTab === item.key ? 'bg-blue-600 text-white font-semibold border-l-4 border-blue-400' : 'border-l-4 border-transparent'}"
        aria-current={activeTab === item.key ? 'page' : undefined}
      >
        <span class="text-xl">{item.icon}</span>
        {#if !$sidebarState.isMobile}
          <span class="whitespace-nowrap">{item.label}</span>
        {/if}
      </button>
    {/each}
  </div>

  <div class="p-4 border-t border-zinc-800">
    {#if !$sidebarState.isMobile}
      <p class="text-xs text-gray-500">cyber-agent-engine</p>
    {/if}
  </div>
</nav>
