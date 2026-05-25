import type { AIProvider } from '../../services/aiSettingsApi'

export function getSelectableChatProviders(providers: AIProvider[]) {
  return providers.filter((provider) => provider.enabled && Boolean(provider.api_key_masked))
}

export function getProviderModels(provider: AIProvider) {
  return Array.from(new Set([provider.model, ...(provider.available_models || [])].filter(Boolean)))
}
