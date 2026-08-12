export function canApplyConceptDetail(
  requestId: number,
  activeRequestId: number,
  requestedConceptId: number,
  selectedConceptId: number | null,
): boolean {
  return requestId === activeRequestId && requestedConceptId === selectedConceptId
}
