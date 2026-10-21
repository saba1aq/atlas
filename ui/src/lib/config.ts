export interface AtlasConfig {
  basePath: string
  apiPath: string
  title: string
}

declare global {
  interface Window {
    __ATLAS__?: AtlasConfig
  }
}

const fallback: AtlasConfig = { basePath: '/admin', apiPath: '/admin/_api', title: 'Atlas Admin' }
const raw = window.__ATLAS__
export const config: AtlasConfig =
  raw && typeof raw === 'object' && 'apiPath' in raw ? raw : fallback
