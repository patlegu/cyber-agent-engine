<script lang="ts">
  import { tick } from 'svelte';
  import { notify } from '../stores/notificationStore';
  import { sendCommand } from '../utils/coordinatorApi';

  interface Message {
    role: 'user' | 'coordinator';
    text: string;
    ts: string;
  }

  let messages: Message[] = [];
  let input = '';
  let sending = false;
  let chatEl: HTMLDivElement;

  async function submit() {
    if (!input.trim() || sending) return;
    const text = input.trim();
    input = '';
    messages = [...messages, { role: 'user', text, ts: new Date().toISOString() }];
    sending = true;
    scrollToBottom();
    try {
      const reply = await sendCommand(text);
      if (reply) {
        messages = [...messages, { role: 'coordinator', text: reply, ts: new Date().toISOString() }];
        scrollToBottom();
      }
    } catch (err: any) {
      notify(err.message, 'error');
    } finally {
      sending = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  async function scrollToBottom() {
    await tick();
    chatEl?.scrollTo({ top: chatEl.scrollHeight, behavior: 'smooth' });
  }
</script>

<div class="flex flex-col h-full gap-3">
  <h2 class="text-xl font-bold text-zinc-100">Coordinateur</h2>

  <div bind:this={chatEl} class="flex-1 overflow-y-auto space-y-3 bg-zinc-800 rounded-xl p-4 min-h-0">
    {#if messages.length === 0}
      <p class="text-zinc-500 text-sm text-center mt-8">Envoyez une commande au coordinateur…</p>
    {/if}
    {#each messages as msg (msg.ts)}
      <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
        <div class="max-w-[75%] px-4 py-2 rounded-xl text-sm whitespace-pre-wrap
          {msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-zinc-700 text-zinc-100'}">
          {msg.text}
        </div>
      </div>
    {/each}
    {#if sending}
      <div class="flex justify-start">
        <div class="bg-zinc-700 text-zinc-400 px-4 py-2 rounded-xl text-sm animate-pulse">…</div>
      </div>
    {/if}
  </div>

  <div class="flex gap-2 shrink-0">
    <textarea
      bind:value={input}
      on:keydown={onKeydown}
      rows="2"
      placeholder="Commande ou question… (Entrée pour envoyer)"
      class="input-text flex-1 resize-none"
      disabled={sending}
    ></textarea>
    <button
      on:click={submit}
      disabled={sending || !input.trim()}
      class="btn-primary self-end"
    >
      {sending ? '…' : 'Envoyer'}
    </button>
  </div>
</div>
