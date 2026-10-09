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

export const postJson = <T>(path: string) => getJson<T>(path, { method: 'POST' })

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
export type GameAction = 'lock' | 'unlock'

export interface Game {
  id: number
  state: GameState
  created_at: string
  updated_at: string
  actions: GameAction[]
}

export const getGame = (signal?: AbortSignal) => getJson<Game>('/game', { signal })
export const runGameAction = (action: GameAction) => postJson<Game>(`/game/${action}`)
