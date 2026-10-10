export interface PatientDocumentSummary {
  source_id: string
  patient_id: string
  doc_date?: string
  character_count: number
  chunks_count: number
  created_at: string
}

export interface PatientDocumentDetail {
  source_id: string
  patient_id: string
  doc_date?: string
  text: string
  character_count: number
  chunks_count: number
  created_at: string
}

export interface DocumentIngestRequest {
  source_id: string
  patient_id: string
  doc_date?: string
  mime_type: string
  text: string
}

export interface DocumentIngestResponse {
  source_id: string
  patient_id: string
  status: string
  chunks_created: number
  character_count: number
  actor: string
  ingested_at: string
}
