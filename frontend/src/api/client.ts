export class ApiError extends Error {
  readonly status: number
  /** The API's error code (`detail.code`), when it gave one. */
  readonly code: string | undefined
  /** The rest of the API's error detail, e.g. what a refusal is about. */
  readonly detail: Record<string, unknown> | undefined

  constructor(status: number, message: string, detail?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = typeof detail?.code === 'string' ? detail.code : undefined
  }
}

export async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(response.status, errorMessage(response, body), errorDetail(body))
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

/** The API's short error message (`detail.message`), the first field a validation error
 * names, else the HTTP status. */
function errorMessage(response: Response, body: unknown): string {
  const detail = (
    body as {
      detail?: { message?: string } | { loc?: (string | number)[]; msg?: string }[]
    } | null
  )?.detail
  if (Array.isArray(detail)) {
    const [first] = detail
    if (first?.msg) return `${first.loc?.at(-1) ?? 'value'}: ${first.msg}`
  } else if (detail?.message) return detail.message
  return `${response.status} ${response.statusText}`
}

function errorDetail(body: unknown): Record<string, unknown> | undefined {
  const detail = (body as { detail?: unknown } | null)?.detail
  return detail && typeof detail === 'object' && !Array.isArray(detail)
    ? (detail as Record<string, unknown>)
    : undefined
}

export interface Health {
  status: 'ok'
  version: string
  database: 'ok'
}

export const getHealth = (signal?: AbortSignal) => getJson<Health>('/health', { signal })

export type GameState = 'open' | 'locked' | 'generating' | 'generated' | 'running' | 'archived'
export type GameAction = 'lock' | 'unlock' | 'generate' | 'discard-output' | 'start' | 'stop'

export interface Game {
  id: number
  state: GameState
  created_at: string
  updated_at: string
  actions: GameAction[]
  /** ARCHIVE is possible: not mid-generation, and there is something to keep. */
  archivable: boolean
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

export type ServerState = 'stopped' | 'starting' | 'running' | 'stopping' | 'idle' | 'crashed'

export interface ServerStatus {
  reachable: boolean
  state: ServerState | null
  archipelago_version: string | null
  multidata: string | null
  port: number | null
  started_at: string | null
  exit_code: number | null
  /** MultiServer's last lines, when it crashed. */
  log_tail: string[]
}

export const getServer = (signal?: AbortSignal) => getJson<ServerStatus>('/server', { signal })
export const saveServer = () => postJson<ServerStatus>('/server/save')

/** One line for MultiServer's console, as typed there: a /command, or chat as the server. */
export const sendCommand = (text: string) => postJsonBody<ServerStatus>('/server/command', { text })

export interface HealthDetails {
  version: string
  archipelago_version: string | null
  isolation: string
  isolation_warning: string | null
  /** What the web UI answers to: addresses, local names, then APSUI_ALLOWED_HOSTS. */
  host_names: string[]
  host_names_warning: string | null
  services: { name: 'web' | 'worker' | 'server'; up: boolean; detail: string }[]
  ports: { name: string; port: number | null }[]
  disks: { name: string; path: string; total: number; used: number; free: number }[]
}

export const getHealthDetails = (signal?: AbortSignal) =>
  getJson<HealthDetails>('/health/details', { signal })

export interface PatchFile {
  file: string
  player: number
  slot: string
  size: number
}

export const listPatches = (signal?: AbortSignal) =>
  getJson<PatchFile[]>('/game/patches', { signal })

export const patchUrl = (file: string) => `/api/game/patches/${encodeURIComponent(file)}`
export const allPatchesUrl = '/api/game/patches-all.zip'

export interface SpoilerInfo {
  file: string
  size: number
}

/** Whether the generated game has a spoiler log; safe to call, it holds no spoilers. */
export const getSpoiler = (signal?: AbortSignal) =>
  getJson<SpoilerInfo>('/game/spoiler', { signal })

export const spoilerUrl = '/api/game/spoiler.txt'

/** The spoiler log itself: fetch it only once the admin has confirmed. */
export async function getSpoilerText(signal?: AbortSignal): Promise<string> {
  const response = await fetch(spoilerUrl, { signal })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError(response.status, errorMessage(response, body), errorDetail(body))
  }
  return response.text()
}

export interface CommandArg {
  name: string
  /** player, item, location, number, option or text. */
  kind: string
  required: boolean
  /** Takes the rest of the line (the command joins the words). */
  rest: boolean
  default: string | null
  choices: string[]
}

export interface ConsoleCommand {
  name: string
  help: string
  /** Gets everything after the command as one text, unquoted. */
  raw: boolean
  args: CommandArg[]
}

export interface ConsoleNames {
  players: { slot: number; name: string; game: string }[]
  games: Record<string, { items: string[]; locations: string[] }>
}

export const listCommands = (signal?: AbortSignal) =>
  getJson<ConsoleCommand[]>('/console/commands', { signal })

export const getConsoleNames = (signal?: AbortSignal) =>
  getJson<ConsoleNames>('/console/names', { signal })

/** The server feed's WebSocket, on this page's own host (the server refuses others). */
export const serverFeedUrl = () =>
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api/server/feed`

export type SettingValue = string | number | boolean | string[]

export interface SettingField {
  key: string
  label: string
  help: string
  group: 'server' | 'generation' | 'uploads' | 'archives' | 'advanced'
  kind: 'text' | 'password' | 'number' | 'bool' | 'choice' | 'multi'
  /** live: at once on a running server; else at the next start, generation, upload or
   * archive. */
  applies: 'live' | 'start' | 'generation' | 'upload' | 'archive'
  choices: { value: string | number; label: string }[]
  min: number | null
  max: number | null
  warning: string | null
}

export interface SettingsPage {
  values: Record<string, SettingValue>
  fields: SettingField[]
}

export const getSettings = (signal?: AbortSignal) => getJson<SettingsPage>('/settings', { signal })

export const putSettings = (values: Record<string, SettingValue>) =>
  getJson<{ values: Record<string, SettingValue>; applied_now: string[] }>('/settings', {
    method: 'PUT',
    body: JSON.stringify(values),
    headers: { 'Content-Type': 'application/json' },
  })

export const archiveGame = () => postJson<Game>('/game/archive')

export interface Archive {
  id: number
  created_at: string
  archived_at: string | null
  /** Restore brings it back in this state (Running comes back Generated). */
  archived_from: GameState | null
  size: number | null
  seed_name: string | null
  slots: string[]
  worlds: string[]
}

export interface ArchiveDetail extends Archive {
  files: { path: string; size: number }[]
  generations: Generation[]
  uploads: Record<string, unknown>[]
}

export interface ArchiveList {
  archives: Archive[]
  retention: {
    limit: 'none' | 'count' | 'size'
    max_count: number
    max_size_mb: number
    count: number
    total_size: number
  }
}

/** What a restore is refused over: the current game, which must make way first. */
export interface CurrentGameSummary {
  id: number
  state: GameState
  slots: number
}

export type RestoreChoice = 'archive' | 'delete'

export const listArchives = (signal?: AbortSignal) => getJson<ArchiveList>('/archives', { signal })
export const getArchive = (id: number, signal?: AbortSignal) =>
  getJson<ArchiveDetail>(`/archives/${id}`, { signal })
export const restoreArchive = (id: number, current: RestoreChoice | null) =>
  postJsonBody<Game>(`/archives/${id}/restore`, { current })
export const deleteArchive = (id: number) =>
  getJson<{ deleted: boolean }>(`/archives/${id}`, { method: 'DELETE' })
export const archiveDownloadUrl = (id: number) => `/api/archives/${id}/download`
export const archiveFileUrl = (id: number, path: string) =>
  `/api/archives/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`
