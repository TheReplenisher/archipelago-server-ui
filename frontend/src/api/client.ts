export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}

export const postJson = <T>(path: string, body?: BodyInit) =>
  getJson<T>(path, { method: 'POST', body })

export const postJsonBody = <T>(path: string, body: unknown) =>
  getJson<T>(path, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  })

/** The API's short error message (`detail.message`), else the HTTP status. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: { message?: string } }
    if (body.detail?.message) return body.detail.message
  } catch {
    // not JSON
  }
  return `${response.status} ${response.statusText}`
}

export interface Health {
  status: 'ok'
  version: string
  database: 'ok'
}

export const getHealth = (signal?: AbortSignal) => getJson<Health>('/health', { signal })

export type GameState = 'open' | 'locked' | 'generating' | 'generated' | 'running' | 'archived'
export type GameAction = 'lock' | 'unlock' | 'generate' | 'discard-output'

export interface Game {
  id: number
  state: GameState
  created_at: string
  updated_at: string
  actions: GameAction[]
}

export const getGame = (signal?: AbortSignal) => getJson<Game>('/game', { signal })
/** Generate answers with the new generation run; the others with the game. */
export const runGameAction = (action: GameAction) => postJson<unknown>(`/game/${action}`)

export type UploadStatus = 'pending' | 'needs-name' | 'accepted' | 'rejected' | 'removed'

export interface NameProblem {
  document: number
  /** The name in the file, or the names a weighted entry could roll. */
  current: string | string[] | null
  code: string
  message: string
  suggestion: string
}

export interface Upload {
  id: number
  kind: string
  filename: string
  status: UploadStatus
  error_code: string | null
  error_message: string | null
  uploaded_at: string
  checked_at: string | null
  slots: string[]
  name_problems: NameProblem[]
}

export const listUploads = (signal?: AbortSignal) => getJson<Upload[]>('/uploads', { signal })

/** `apworldIds` picks library apworlds for the games the YAML uses. */
export function uploadYaml(file: File, apworldIds: number[] = []) {
  const form = new FormData()
  form.append('file', file)
  for (const id of apworldIds) form.append('apworld_ids', String(id))
  return postJson<Upload>('/uploads/yaml', form)
}

/** The world a game is locked to in the current game. */
export interface WorldLock {
  world: string
  label: string
  apworld_id: number | null
  upload_id: number
}

export const listWorlds = (signal?: AbortSignal) => getJson<WorldLock[]>('/worlds', { signal })

export const removeUpload = (id: number) => getJson<Upload>(`/uploads/${id}`, { method: 'DELETE' })

export const renameUpload = (id: number, names: { document: number; name: string }[]) =>
  postJsonBody<Upload>(`/uploads/${id}/rename`, { names })

export const cancelUpload = (id: number) => postJson<Upload>(`/uploads/${id}/cancel`)

export type ApworldStatus = 'checking' | 'pending' | 'approved' | 'rejected'

export interface Apworld {
  id: number
  filename: string
  /** `Game · custom · version · short hash` */
  label: string
  game: string | null
  world_version: string | null
  sha256: string
  short_hash: string
  size: number
  status: ApworldStatus
  /** The built-in world's version, when this apworld would replace it. */
  replaces_builtin: string | null
  error_code: string | null
  error_message: string | null
  uploaded_by: string
  uploaded_at: string
  checked_at: string | null
  decided_at: string | null
}

export interface ImportTest {
  loaded: boolean
  games: string[]
  replaces_builtin: string | null
  error: string | null
  detail: string | null
}

export interface ApworldDetail extends Apworld {
  module: string | null
  minimum_ap_version: string | null
  maximum_ap_version: string | null
  authors: string[]
  manifest: Record<string, unknown> | null
  files: { name: string; size: number }[]
  import_test: ImportTest | null
}

export const listApworlds = (signal?: AbortSignal) => getJson<Apworld[]>('/apworlds', { signal })

export const getApworld = (id: number, signal?: AbortSignal) =>
  getJson<ApworldDetail>(`/apworlds/${id}`, { signal })

export function uploadApworld(file: File) {
  const form = new FormData()
  form.append('file', file)
  return postJson<Apworld>('/apworlds', form)
}

export const approveApworld = (id: number) => postJson<Apworld>(`/apworlds/${id}/approve`)
export const rejectApworld = (id: number) => postJson<Apworld>(`/apworlds/${id}/reject`)

export type UploadKind = 'yaml' | 'apworld'

export interface LogEntry {
  kind: UploadKind
  id: number
  /** `<kind>-<id>`: what an error code links to. */
  key: string
  filename: string
  sha256: string
  size: number
  status: string
  error_code: string | null
  error_message: string | null
  uploaded_by: string
  uploaded_at: string
  game_id: number | null
}

export interface LogCheck {
  name: string
  status: 'ok' | 'failed' | 'warning' | 'waiting'
  message: string
  detail: string | null
}

export interface LogDetail extends LogEntry {
  checks: LogCheck[]
  job: {
    id: string
    type: string
    status: string
    submitted_at: string
    finished_at: string | null
    error_code: string | null
    error_message: string | null
    traceback: string | null
    log_tail: string | null
  } | null
}

export const listUploadLog = (signal?: AbortSignal) =>
  getJson<LogEntry[]>('/logs/uploads', { signal })

export const getUploadLog = (kind: UploadKind, id: number, signal?: AbortSignal) =>
  getJson<LogDetail>(`/logs/uploads/${kind}/${id}`, { signal })

export interface Generation {
  id: number
  status: 'running' | 'ok' | 'failed'
  started_at: string
  finished_at: string | null
  seed_name: string | null
  output_file: string | null
  players: string[]
  error_code: string | null
  error_message: string | null
  /** The uploads Archipelago's error points at, where it names one. */
  culprits: { upload_id: number; filename: string; slots: string[] }[]
  traceback: string | null
  log_tail: string | null
}

export const listGenerations = (signal?: AbortSignal) =>
  getJson<Generation[]>('/game/generations', { signal })
