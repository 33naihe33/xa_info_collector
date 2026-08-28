// web/frontend/src/api/client.ts
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export interface SourceInfo {
  name: string
  display_name: string
  enabled: boolean
  doc_count: number
  categories: string[]
}

export interface DocumentItem {
  id: number
  source: string
  doc_type: string
  title: string
  url: string
  publish_date: string
  is_analyzed: boolean
}

export interface DocumentDetail extends DocumentItem {
  text: string
  raw_html: string
}

export interface DocumentListResponse {
  total: number
  items: DocumentItem[]
}

export interface CrawlRunInfo {
  id: number
  source: string
  started_at: string
  finished_at: string | null
  status: string
  new_count: number
  error_count: number
  last_crawled_date: string | null
}

export interface CollectStatusResponse {
  source: string
  last_run: CrawlRunInfo | null
}

export interface OpportunityItem {
  id: number
  title: string
  source_doc_id: number | null
  business_line: string
  opp_type: string
  fin_scale: string | null
  fin_products: string[]
  target_client: string | null
  buyer_dept: string | null
  relocate_from: string | null
  relocate_scale: string | null
  relocate_phase: string | null
  trigger_event: string | null
  timing_window: string | null
  insight: string | null
  action_suggest: string | null
  priority: string
  status: string
  publish_date: string
  deadline: string | null
}

export interface OpportunityListResponse {
  total: number
  items: OpportunityItem[]
}

export interface OpportunityStats {
  total: number
  by_line: Record<string, number>
}

export interface LeadershipVisitItem {
  id: number
  source_doc_id: number | null
  leader_name: string
  leader_title: string | null
  visit_date: string | null
  visit_topic: string | null
  visited_entities: string[]
  summary: string | null
  priority: string
  publish_date: string | null
  images: string[]
  extracted_at: string
  source_url?: string
  source_name?: string
}

export interface LeadershipVisitListResponse {
  total: number
  items: LeadershipVisitItem[]
}

export interface LeadershipVisitStats {
  total: number
  by_priority: Record<string, number>
}

export interface LineBriefItem {
  title: string
  clue: string
  priority: string
  publish_date: string
  source_url?: string
  source_name?: string
}

export interface LineBrief {
  line: string
  label: string
  count: number
  items: LineBriefItem[]
}

export interface GraphNode {
  id: number
  name: string
  category: string
  symbolSize: number
  entity_type: string
}

export interface GraphEdge {
  source: number
  target: number
  relation_type: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  categories: { name: string }[]
  total_nodes: number
  total_edges: number
}

export interface ReportOpportunity {
  title: string
  summary?: string
  priority?: string
  source_url?: string
  source_name?: string
  publish_date?: string
  visit_date?: string
}

export interface ReportSection {
  line: string
  opportunities: ReportOpportunity[]
}

export interface ReportContent {
  title: string
  summary: string
  sections: ReportSection[]
  recommendations: string
  stats: { total: number; by_priority?: Record<string, number> }
  opportunity_count?: number
}

export interface ReportItem {
  id: number
  report_type: string
  period_start: string
  period_end: string
  content: ReportContent
  opportunity_ids: number[]
  docx_path: string | null
  pdf_path: string | null
  generated_at: string
}

export interface ReportListResponse {
  total: number
  items: ReportItem[]
}

export interface GenerateReportResponse {
  report_id: number
  content: ReportContent
}

export interface PushSettings {
  instant_enabled: boolean
  instant_threshold: string
  daily_limit: number
  focus_lines: string[]
  daily_digest_enabled: boolean
  daily_digest_time: string
  weekly_digest_enabled: boolean
  digest_threshold: string
  dnd_enabled: boolean
  dnd_start: string
  dnd_end: string
}

export interface PushStats {
  subscriptions: number
  today_count: number
  today_instant: number
  today_scheduled: number
}

export const apiClient = {
  getSources: () => api.get<{ sources: SourceInfo[] }>('/collect/sources'),
  getCollectStatus: (source: string) => api.get<CollectStatusResponse>('/collect/status', { params: { source } }),
  triggerCollect: (source: string) => api.post('/collect/trigger', null, { params: { source } }),
  getDocuments: (params: { source?: string; limit?: number; offset?: number }) =>
    api.get<DocumentListResponse>('/documents', { params }),
  getDocument: (id: number) => api.get<DocumentDetail>(`/documents/${id}`),
  getOpportunities: (params: { business_line?: string; priority?: string; status?: string; date_from?: string; date_to?: string; limit?: number; offset?: number }) =>
    api.get<OpportunityListResponse>('/opportunities', { params }),
  getOpportunity: (id: number) => api.get<OpportunityItem>(`/opportunities/${id}`),
  getOpportunityStats: () => api.get<OpportunityStats>('/opportunities/stats'),
  getLeadershipVisits: (params: { visit_date_from?: string; visit_date_to?: string; limit?: number; offset?: number }) =>
    api.get<LeadershipVisitListResponse>('/leadership', { params }),
  getLeadershipVisit: (id: number) => api.get<LeadershipVisitItem>(`/leadership/${id}`),
  getLeadershipStats: () => api.get<LeadershipVisitStats>('/leadership/stats'),
  getGraph: (params: { entity_types?: string; relation_types?: string; limit?: number }) =>
    api.get<GraphData>('/graph', { params }),
  triggerAnalyze: () => api.post('/analyze/trigger'),
  generateReport: (params: { report_type: string; date_from: string; date_to: string; business_lines?: string[] }) =>
    api.post<GenerateReportResponse>('/reports/generate', params),
  generateLineBriefs: (params: { date_from: string; date_to: string }) =>
    api.post<{ briefs: LineBrief[] }>('/reports/line-briefs', params),
  getReports: () => api.get<ReportListResponse>('/reports'),
  getReport: (id: number) => api.get<ReportItem>(`/reports/${id}`),
  exportReportUrl: (id: number, format: string) => `/api/reports/${id}/export?format=${format}`,
  generateReportFile: (id: number) => api.post(`/reports/${id}/generate-file`),
  downloadReportUrl: (id: number) => `/api/reports/${id}/download`,
  // 推送设置（增量 6）
  getPushSettings: () => api.get<PushSettings>('/push/settings'),
  updatePushSettings: (settings: Partial<PushSettings>) => api.put<PushSettings>('/push/settings', settings),
  subscribePush: (endpoint: string, keys: Record<string, string>) =>
    api.post('/push/subscribe', { endpoint, keys }),
  getPushStats: () => api.get<PushStats>('/push/stats'),
  getVapidKey: () => api.get<{ public_key: string | null }>('/push/vapid-key'),
}
