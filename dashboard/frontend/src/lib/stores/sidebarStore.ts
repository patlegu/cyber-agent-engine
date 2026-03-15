import { writable } from 'svelte/store';

export const sidebarState = writable({
  isMobile: false,
  showSidebar: true,
});
