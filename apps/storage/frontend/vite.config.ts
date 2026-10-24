import {defineConfig} from 'vitest/config'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue()],test:{environment:'happy-dom'},server:{proxy:{'/api':process.env.API_UPSTREAM||'http://storage-api:8000'}}})
