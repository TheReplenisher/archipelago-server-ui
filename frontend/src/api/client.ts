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
    const error = new ApiError(response.status, errorMessage(response, body), errorDetail(body))
    if (error.code === ADMIN_LOGIN_REQUIRED) window.dispatchEvent(new Event(ADMIN_LOGGED_OUT))
    throw error
  }
  return (await response.json()) as T
}

/** The API's answer on an admin route without a logged-in admin (#32). */
export const ADMIN_LOGIN_REQUIRED = 'admin-login-required'
/** Fired on window when an admin route says the admin isn't logged in (any more). */
export const ADMIN_LOGGED_OUT = 'apsui:admin-logged-out'

export interface AdminSession {
  /** False until the first admin sets a password. */
  password_set: boolean
  logged_in: boolean
  username: string | null
}

export const getAdminSession = (signal?: AbortSignal) =>
  getJson<AdminSession>('/admin/session', { signal })

export const adminSetup = (password: string) =>
  postJsonBody<AdminSession>('/admin/setup', { password })

export const adminLogin = (password: string) =>
  postJsonBody<AdminSession>('/admin/login', { password })

export const adminLogout = () => postJson<AdminSession>('/admin/logout')

export const changeAdminPassword = (current: string, next: string) =>
  postJsonBody<AdminSession>('/admin/password', { current, new: next })

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
  /** admin, or player (from the Player tab). */
  uploaded_by?: string
  uploaded_from?: string | null
  uploaded_at: string
  checked_at: string | null
  slots: string[]
  /** The games its documents use, from its last check. */
  games?: string[]
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
  /** When the admin last changed the version (#34). */
  overridden_at?: string | null
  /** The uploads that change checked again, as they are now. */
  rechecked?: Upload[]
}

/** Change a game's locked version (#34): a library apworld, or null for the official world. */
export const overrideWorld = (world: string, apworldId: number | null) =>
  postJsonBody<WorldLock>(`/worlds/${encodeURIComponent(world)}/override`, {
    apworld_id: apworldId,
  })

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
  uploaded_from?: string | null
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
  /** Stored settings that stopped validating after an update, shown at their defaults. */
  reset: string[]
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

/** AP's network item flags. */
export const ITEM_PROGRESSION = 1
export const ITEM_USEFUL = 2
export const ITEM_TRAP = 4

export interface SlotView {
  slot: { name: string; game: string; team: number; slot: number }
  /** False while the connection to the server is being re-made. */
  live: boolean
  goal: boolean
  hint_points: number
  checked: number
  locations: number
  received: { item: string; player: string; location: string; flags: number }[]
  /** null when the room's !remaining setting doesn't allow it (yet). */
  unreceived: { item: string; count: number; flags: number }[] | null
  unreceived_rule: 'enabled' | 'goal' | 'disabled' | 'unavailable'
  unchecked: string[]
  hints: {
    item: string
    receiving: string
    finding: string
    location: string
    entrance: string
    found: boolean
    status: string
    flags: number
  }[]
}

export const getSlotView = (signal?: AbortSignal) => getJson<SlotView>('/slot', { signal })
export const slotLogin = (name: string, password: string) =>
  postJsonBody<{ name: string }>('/slot/login', { name, password })
export const slotLogout = () => postJson<{ ok: boolean }>('/slot/logout')

export interface AuditEntry {
  id: number
  at: string
  /** The admin, `shell` for apsui-admin, null for a refused login. */
  actor: string | null
  action: string
  label: string
  target: string | null
  detail: Record<string, unknown> | null
  status: number
  ok: boolean
  client: string | null
}

export interface AuditPage {
  entries: AuditEntry[]
  /** Pass as `before` for older entries; null on the last page. */
  next_before: number | null
  actions: Record<string, string>
}

export interface AuditFilter {
  actions: string[]
  failed: boolean
  q: string
}

export function getAudit(filter: AuditFilter, before?: number, signal?: AbortSignal) {
  const params = new URLSearchParams()
  for (const action of filter.actions) params.append('action', action)
  if (filter.failed) params.set('failed', 'true')
  if (filter.q.trim()) params.set('q', filter.q.trim())
  if (before) params.set('before', String(before))
  return getJson<AuditPage>(`/audit?${params.toString()}`, { signal })
}

// ---- Player uploads (#33)

export interface PlayerGame {
  state: GameState
  /** Players can upload now: the game is Open and the admin allows it. */
  uploads_open: boolean
  player_uploads: boolean
  apworld_approval: 'manual' | 'auto'
  max_slots: number
  slots_used: number
  taken_names: string[]
}

export const getPlayerGame = (signal?: AbortSignal) =>
  getJson<PlayerGame>('/player/game', { signal })

export interface PlayerLibrary {
  apworlds: { id: number; label: string; game: string; replaces_builtin: boolean }[]
  locked: { world: string; label: string }[]
}

export const getPlayerLibrary = (signal?: AbortSignal) =>
  getJson<PlayerLibrary>('/player/library', { signal })

/** What a player sees of their own upload: status and the short error, never the detail. */
export interface PlayerUpload {
  kind: 'yaml' | 'apworld'
  id: number
  filename: string
  status: UploadStatus | 'checking' | 'pending' | 'approved'
  error_code: string | null
  error_message: string | null
  /** YAML: its slots, and what needs a new name. */
  slots?: string[]
  name_problems?: NameProblem[]
  current_game?: boolean
  /** Apworld: its library label, and whether it replaces a built-in world. */
  label?: string
  game?: string | null
  replaces_builtin?: boolean
  uploaded_at: string
}

/** The key to a player's own upload, kept in their browser. */
export interface Receipt {
  kind: 'yaml' | 'apworld'
  id: number
  receipt: string
}

const RECEIPTS_KEY = 'apsui.receipts'
const MAX_RECEIPTS = 50

export function loadReceipts(): Receipt[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(RECEIPTS_KEY) ?? '[]')
    return Array.isArray(stored) ? (stored as Receipt[]) : []
  } catch {
    return []
  }
}

export function saveReceipts(receipts: Receipt[]) {
  try {
    localStorage.setItem(RECEIPTS_KEY, JSON.stringify(receipts.slice(-MAX_RECEIPTS)))
  } catch {
    // Private windows and blocked storage: the receipts last as long as the page.
  }
}

interface Uploaded {
  receipt: string
  upload: PlayerUpload
}

export function playerUploadYaml(file: File, apworldIds: number[] = []) {
  const form = new FormData()
  form.append('file', file)
  for (const id of apworldIds) form.append('apworld_ids', String(id))
  return postJson<Uploaded>('/player/yaml', form)
}

export function playerUploadApworld(file: File) {
  const form = new FormData()
  form.append('file', file)
  return postJson<Uploaded>('/player/apworld', form)
}

export const getPlayerUploads = (receipts: Receipt[]) =>
  postJsonBody<PlayerUpload[]>('/player/receipts', { receipts })

export const playerRename = (receipt: Receipt, names: { document: number; name: string }[]) =>
  postJsonBody<PlayerUpload>(`/player/yaml/${receipt.id}/rename`, {
    receipt: receipt.receipt,
    names,
  })

export const playerWithdraw = (receipt: Receipt) =>
  postJsonBody<PlayerUpload>(`/player/yaml/${receipt.id}/withdraw`, { receipt: receipt.receipt })

// ---- Player side: own patch files (#36) and the player feed (#35)

export const listMyPatches = (signal?: AbortSignal) =>
  getJson<PatchFile[]>('/slot/patches', { signal })

export const myPatchUrl = (file: string) => `/api/slot/patches/${encodeURIComponent(file)}`

export interface FeedPart {
  /** text, player, item, location or entrance. */
  kind: string
  text: string
  /** Items: AP's flags (progression, useful, trap). */
  flags?: number
}

export interface FeedEntry {
  id: number
  /** Unix seconds. */
  at: number
  /** ItemSend, ItemCheat, Chat, ServerChat, Join, Part, Goal, Release, Collect, Countdown. */
  type: string
  parts: FeedPart[]
}

export const getPlayerFeed = (after: number, signal?: AbortSignal) =>
  getJson<{ entries: FeedEntry[]; last: number }>(`/slot/feed?after=${after}`, { signal })

// ---- Backups (#38)

export interface Backup {
  name: string
  size: number
  created_at: string
  /** False for a file this version can't restore. */
  readable: boolean
  archives: boolean
  label: string | null
  app_version: string | null
  archipelago_version: string | null
  files: number
}

export interface BackupList {
  backups: Backup[]
  making: boolean
  total_size: number
}

export const listBackups = (signal?: AbortSignal) => getJson<BackupList>('/backups', { signal })
export const createBackup = (archives: boolean) =>
  postJsonBody<{ ok: boolean }>('/backups', { archives })
export const deleteBackup = (name: string) =>
  getJson<{ ok: boolean }>(`/backups/${encodeURIComponent(name)}`, { method: 'DELETE' })
export const restoreBackup = (name: string) =>
  postJson<{ restored: string; created_at: string; archives: boolean }>(
    `/backups/${encodeURIComponent(name)}/restore`,
  )
export const backupUrl = (name: string) => `/api/backups/${encodeURIComponent(name)}`

const PIECE = 8 * 1024 * 1024

/** Upload a backup file in 8 MB pieces, so a proxy's body limit doesn't matter. */
export async function uploadBackup(file: File, onProgress: (done: number) => void) {
  const { id } = await postJson<{ id: string }>('/backups/incoming')
  for (let offset = 0; offset < file.size; offset += PIECE) {
    await getJson<{ size: number }>(`/backups/incoming/${id}?offset=${offset}`, {
      method: 'PUT',
      body: file.slice(offset, offset + PIECE),
      headers: { 'Content-Type': 'application/octet-stream' },
    })
    onProgress(Math.min(offset + PIECE, file.size) / file.size)
  }
  return postJsonBody<Backup>(`/backups/incoming/${id}/finish`, { filename: file.name })
}
