<script lang="ts">
  import { notificationStore } from '../stores/notificationStore';
  import { onDestroy } from 'svelte';

  let notification: { message: string; type: string } | null = null;
  const unsubscribe = notificationStore.subscribe(value => {
    notification = value;
  });

  onDestroy(unsubscribe);
</script>

{#if notification}
  <div class="notification-banner type-{notification.type}" role="alert">
    <p>{notification.message}</p>
    <button class="close-button" on:click={() => notificationStore.set(null)} aria-label="Fermer">&times;</button>
  </div>
{/if}

<style>
  .notification-banner {
    position: fixed;
    top: 72px;
    left: 50%;
    transform: translateX(-50%);
    padding: 0.75rem 1.25rem;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    z-index: 1000;
    display: flex;
    justify-content: space-between;
    align-items: center;
    min-width: 300px;
    max-width: 600px;
    font-size: 0.9rem;
  }
  .type-success { background: #1a3a1e; color: #4ade80; border: 1px solid #16a34a; }
  .type-error   { background: #3a1a1a; color: #f87171; border: 1px solid #dc2626; }
  .type-info    { background: #1a2a3a; color: #60a5fa; border: 1px solid #2563eb; }
  .close-button {
    background: none; border: none; color: inherit;
    font-size: 1.4rem; margin-left: 1rem; cursor: pointer; padding: 0;
  }
</style>
