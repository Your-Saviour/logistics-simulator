import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
export default defineConfig({ plugins: [svelte()], server: { proxy: { '/api': process.env.API_UPSTREAM || 'http://logistics-api:8000' } } });
