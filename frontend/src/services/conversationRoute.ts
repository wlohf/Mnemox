export function getConversationPath(id: number): string {
  return `/conversations/${id}`
}

export function parseConversationRouteId(value?: string | null): number | null {
  if (!value || !/^\d+$/.test(value)) {
    return null
  }

  const id = Number(value)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}
