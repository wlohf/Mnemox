import { describe, expect, it } from 'vitest'
import type { AIProvider } from '../../services/aiSettingsApi'
import { getProviderModels, getSelectableChatProviders } from './chatModelOptions'

function provider(overrides: Partial<AIProvider>): AIProvider {
  return {
    provider_name: 'openai',
    display_name: 'OpenAI',
    api_key_masked: 'sk-****test',
    base_url: 'https://api.openai.com/v1',
    model: 'gpt-4',
    available_models: [],
    is_active: false,
    enabled: true,
    ...overrides,
  }
}

describe('chat model selector helpers', () => {
  it('keeps only enabled providers with a configured API key', () => {
    const providers = [
      provider({ provider_name: 'deepseek', display_name: 'DeepSeek', api_key_masked: '', model: 'deepseek-chat' }),
      provider({ provider_name: 'qwen', display_name: 'Qwen', api_key_masked: '', model: 'qwen-turbo' }),
      provider({ provider_name: 'openai', display_name: 'OpenAI', api_key_masked: 'sk-****1234', model: 'gpt-4' }),
      provider({ provider_name: 'claude', display_name: 'Claude', api_key_masked: 'sk-****5678', enabled: false, model: 'claude-sonnet' }),
    ]

    expect(getSelectableChatProviders(providers).map((item) => item.provider_name)).toEqual(['openai'])
  })

  it('deduplicates the default model and discovered models', () => {
    const models = getProviderModels(provider({
      model: 'gpt-4',
      available_models: ['gpt-4', 'gpt-4o'],
    }))

    expect(models).toEqual(['gpt-4', 'gpt-4o'])
  })
})
