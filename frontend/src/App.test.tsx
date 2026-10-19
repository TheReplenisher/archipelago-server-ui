import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderRoute } from './test/render'

const openGame = {
  id: 1,
  state: 'open',
  created_at: '2026-10-09T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
  actions: ['lock'],
  archivable: false,
}

const notLoggedIn = { detail: { code: 'not-logged-in', message: 'Log in with your slot name' } }

/** Answers /api/health with `health` and /api/game like a fresh install. */
function stubHealth(health: () => Promise<Response>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/game') return Promise.resolve(Response.json(openGame))
    if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
    if (url === '/api/worlds') return Promise.resolve(Response.json([]))
    if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
    if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
    if (url === '/api/uploads') return Promise.resolve(Response.json([]))
    if (url === '/api/archives') return Promise.resolve(Response.json(noArchives))
    if (url === '/api/slot') return Promise.resolve(Response.json(notLoggedIn, { status: 401 }))
    return health()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const okHealth = () =>
  Promise.resolve(Response.json({ status: 'ok', version: '1.2.3', database: 'ok' }))

const noArchives = {
  archives: [],
  retention: { limit: 'none', max_count: 20, max_size_mb: 10240, count: 0, total_size: 0 },
}

/** What the admin page also fetches: no archives yet, and the health check. */
const fallback = (input: RequestInfo | URL) =>
  String(input) === '/api/archives' ? Promise.resolve(Response.json(noArchives)) : okHealth()

describe('app shell', () => {
  it('sends / to the player page', async () => {
    const { router } = renderRoute('/')
    expect(await screen.findByRole('heading', { name: 'Player' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/player')
  })

  it('switches between the Player and Admin tabs', async () => {
    stubHealth(okHealth)
    const { router } = renderRoute('/player')
    const mainNav = screen.getByRole('navigation', { name: 'Main' })

    await userEvent.click(within(mainNav).getByRole('link', { name: 'Admin' }))
    expect(await screen.findByRole('heading', { name: 'Admin' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin')
  })

  it('shows a not-found page for unknown routes', async () => {
    renderRoute('/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})

describe('admin page', () => {
  it('warns that Alpha 1 has no admin login', () => {
    stubHealth(okHealth)
    renderRoute('/admin')
    expect(screen.getByText('No admin login in Alpha 1')).toBeInTheDocument()
  })

  it('shows the backend version when the API is up', async () => {
    const fetchMock = stubHealth(okHealth)
    renderRoute('/admin')
    expect(await screen.findByText('Online · v1.2.3')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/health', expect.anything())
  })

  it('says so when the API is unreachable', async () => {
    stubHealth(() => Promise.reject(new TypeError('Failed to fetch')))
    renderRoute('/admin')
    await waitFor(() => expect(screen.getByText('Unreachable')).toBeInTheDocument())
  })
})

describe('current game', () => {
  it('shows the state and moves it with the allowed action', async () => {
    let current = openGame
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/lock' && init?.method === 'POST') {
        current = { ...openGame, state: 'locked', actions: ['unlock'] }
        return Promise.resolve(Response.json(current))
      }
      if (url === '/api/game') return Promise.resolve(Response.json(current))
      if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
      if (url === '/api/worlds') return Promise.resolve(Response.json([]))
      if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
      if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
      if (url === '/api/uploads') return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    expect(await screen.findByText('Open')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Lock uploads' }))
    expect(await screen.findByText('Locked')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Unlock uploads' })).toBeInTheDocument()
  })

  it("shows the API's message when an action is refused", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/game/lock' && init?.method === 'POST')
          return Promise.resolve(
            Response.json(
              {
                detail: { code: 'invalid-transition', message: "Can't lock a game that is locked" },
              },
              { status: 409 },
            ),
          )
        if (url === '/api/game') return Promise.resolve(Response.json(openGame))
        if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
        if (url === '/api/worlds') return Promise.resolve(Response.json([]))
        if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
        if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
        if (url === '/api/uploads') return Promise.resolve(Response.json([]))
        return fallback(input)
      }),
    )
    renderRoute('/admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Lock uploads' }))
    expect(await screen.findByText("Can't lock a game that is locked")).toBeInTheDocument()
  })
})

describe('uploads', () => {
  const base = {
    kind: 'yaml',
    uploaded_at: '2026-10-09T00:00:00Z',
    checked_at: null,
    error_code: null,
    error_message: null,
    slots: [],
    name_problems: [],
  }

  it('uploads a YAML, shows it as checking, then the result', async () => {
    let listed = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/uploads/yaml' && init?.method === 'POST')
        return Promise.resolve(
          Response.json({ ...base, id: 1, filename: 'me.yaml', status: 'pending' }),
        )
      if (url === '/api/uploads') {
        listed += 1
        // first load: nothing; after the upload: checking; then the worker has finished
        const rows =
          listed === 1
            ? []
            : listed === 2
              ? [{ ...base, id: 1, filename: 'me.yaml', status: 'pending' }]
              : [{ ...base, id: 1, filename: 'me.yaml', status: 'accepted', slots: ['Quester'] }]
        return Promise.resolve(Response.json(rows))
      }
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
      if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
      if (url === '/api/worlds') return Promise.resolve(Response.json([]))
      if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
      if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    const { container } = renderRoute('/admin')

    await screen.findByRole('button', { name: 'Upload YAML' })
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, new File(['name: Quester'], 'me.yaml', { type: 'text/yaml' }))

    expect(await screen.findByText('checking')).toBeInTheDocument()
    expect(await screen.findByText('Quester', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('accepted')).toBeInTheDocument()
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u) === '/api/uploads/yaml')!
    expect(init?.body).toBeInstanceOf(FormData)
  })

  it('shows the short reason for a rejected file', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/uploads')
          return Promise.resolve(
            Response.json([
              {
                ...base,
                id: 2,
                filename: 'bad.yaml',
                status: 'rejected',
                error_code: 'name-too-long',
                error_message: 'Slot name is longer than 16 characters',
              },
            ]),
          )
        if (url === '/api/game') return Promise.resolve(Response.json(openGame))
        if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
        if (url === '/api/worlds') return Promise.resolve(Response.json([]))
        if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
        if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
        return fallback(input)
      }),
    )
    renderRoute('/admin')
    expect(await screen.findByText('Slot name is longer than 16 characters')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  })
})

describe('fixing slot names', () => {
  const waiting = {
    id: 3,
    kind: 'yaml',
    filename: 'weighted.yaml',
    status: 'needs-name',
    uploaded_at: '2026-10-09T00:00:00Z',
    checked_at: '2026-10-09T00:00:01Z',
    error_code: null,
    error_message: null,
    slots: [],
    name_problems: [
      {
        document: 0,
        current: ['Alice', 'Bob'],
        code: 'name-not-fixed',
        message: 'Slot name must be one fixed name',
        suggestion: 'Alice',
      },
    ],
  }

  function stub(onPost: (url: string, init?: RequestInit) => Response) {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST') return Promise.resolve(onPost(url, init))
      if (url === '/api/uploads') return Promise.resolve(Response.json([waiting]))
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
      if (url === '/api/apworlds') return Promise.resolve(Response.json([]))
      if (url === '/api/worlds') return Promise.resolve(Response.json([]))
      if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
      if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('renames with the suggestion pre-filled', async () => {
    const fetchMock = stub(() =>
      Response.json({ ...waiting, status: 'pending', name_problems: [] }),
    )
    renderRoute('/admin')
    expect(await screen.findByText('needs a name')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Fix name' }))

    const input = await screen.findByLabelText(/Slot 1: one of Alice, Bob/)
    expect(input).toHaveValue('Alice')
    await userEvent.clear(input)
    await userEvent.type(input, 'Carol')
    await userEvent.click(screen.getByRole('button', { name: 'Save names' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/uploads/3/rename', expect.anything()),
    )
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u) === '/api/uploads/3/rename')!
    expect(JSON.parse(String(init?.body))).toEqual({ names: [{ document: 0, name: 'Carol' }] })
  })

  it('shows why a new name was refused and stays open', async () => {
    stub(() =>
      Response.json(
        { detail: { code: 'name-taken', message: 'Slot name Alice is already taken' } },
        { status: 400 },
      ),
    )
    renderRoute('/admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Fix name' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Save names' }))
    expect(await screen.findByText('Slot name Alice is already taken')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save names' })).toBeInTheDocument()
  })

  it('cancels only after confirming', async () => {
    const fetchMock = stub(() =>
      Response.json({ ...waiting, status: 'rejected', error_code: 'cancelled', name_problems: [] }),
    )
    renderRoute('/admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Fix name' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel upload' }))
    expect(fetchMock).not.toHaveBeenCalledWith('/api/uploads/3/cancel', expect.anything())
    await userEvent.click(screen.getByRole('button', { name: 'Yes, cancel upload' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/uploads/3/cancel', expect.anything()),
    )
  })
})

describe('apworld approval', () => {
  const pending = {
    id: 7,
    filename: 'apquest.apworld',
    label: 'APQuest · custom · v9.9.0 · a3f9c1',
    game: 'APQuest',
    world_version: '9.9.0',
    sha256: 'a3f9c1' + '0'.repeat(58),
    short_hash: 'a3f9c1',
    size: 2048,
    status: 'pending',
    replaces_builtin: '2.0.0',
    error_code: null,
    error_message: null,
    uploaded_by: 'admin',
    uploaded_at: '2026-10-10T00:00:00Z',
    checked_at: '2026-10-10T00:00:01Z',
    decided_at: null,
  }
  const detail = {
    ...pending,
    module: 'apquest',
    minimum_ap_version: '0.6.0',
    maximum_ap_version: null,
    authors: ['Someone'],
    manifest: { game: 'APQuest', world_version: '9.9.0' },
    files: [{ name: 'apquest/__init__.py', size: 120 }],
    import_test: {
      loaded: true,
      games: ['APQuest'],
      replaces_builtin: '2.0.0',
      error: null,
      detail: null,
    },
  }

  function stub() {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST')
        return Promise.resolve(Response.json({ ...pending, status: 'approved' }))
      if (url === '/api/apworlds') return Promise.resolve(Response.json([pending]))
      if (url === '/api/apworlds/7') return Promise.resolve(Response.json(detail))
      if (url === '/api/worlds') return Promise.resolve(Response.json([]))
      if (url === '/api/game/generations') return Promise.resolve(Response.json([]))
      if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
      if (url === '/api/uploads') return Promise.resolve(Response.json([]))
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('flags a built-in replacement and approves from the review screen', async () => {
    const fetchMock = stub()
    renderRoute('/admin')
    expect(await screen.findByText('needs approval')).toBeInTheDocument()
    expect(screen.getByText('replaces built-in')).toBeInTheDocument()
    expect(screen.getByText('1 waiting for approval')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Review' }))
    expect(await screen.findByText('Replaces a built-in world')).toBeInTheDocument()
    expect(screen.getByText(pending.sha256)).toBeInTheDocument()
    expect(screen.getByText('loaded: APQuest')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/apworlds/7/approve', expect.anything()),
    )
  })
})

describe('custom apworlds for a YAML', () => {
  const approved = {
    id: 4,
    filename: 'sample_game.apworld',
    label: 'Sample Game · custom · v1.0.0 · abc123',
    game: 'Sample Game',
    world_version: '1.0.0',
    sha256: 'abc123' + '0'.repeat(58),
    short_hash: 'abc123',
    size: 1024,
    status: 'approved',
    replaces_builtin: null,
    error_code: null,
    error_message: null,
    uploaded_by: 'admin',
    uploaded_at: '2026-10-10T00:00:00Z',
    checked_at: '2026-10-10T00:00:01Z',
    decided_at: '2026-10-10T00:00:02Z',
  }

  it('shows locked versions and sends the picked apworlds with the upload', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST') return Promise.resolve(Response.json({}, { status: 202 }))
      if (url === '/api/apworlds') return Promise.resolve(Response.json([approved]))
      if (url === '/api/logs/uploads') return Promise.resolve(Response.json([]))
      if (url === '/api/worlds')
        return Promise.resolve(
          Response.json([
            {
              world: 'APQuest',
              label: 'APQuest · official · AP 0.6.8',
              apworld_id: null,
              upload_id: 1,
            },
          ]),
        )
      if (url === '/api/uploads') return Promise.resolve(Response.json([]))
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    expect(await screen.findByText('APQuest · official · AP 0.6.8')).toBeInTheDocument()
    await userEvent.click(screen.getByPlaceholderText('Official worlds'))
    await userEvent.click(
      await screen.findByRole('option', {
        name: 'Sample Game · custom · v1.0.0 · abc123',
        hidden: true,
      }),
    )

    const file = new File(['name: Knight\n'], 'knight.yaml', { type: 'text/yaml' })
    const input = document.querySelector<HTMLInputElement>('input[type=file][accept*=".yaml"]')!
    await userEvent.upload(input, file)
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/uploads/yaml', expect.anything()),
    )
    const [, init] = fetchMock.mock.calls.find(([u]) => String(u) === '/api/uploads/yaml')!
    expect((init!.body as FormData).getAll('apworld_ids')).toEqual(['4'])
  })
})

describe('upload log', () => {
  it('opens the full log entry from a short error code', async () => {
    const rejected = {
      id: 5,
      kind: 'yaml',
      filename: 'bad.yaml',
      status: 'rejected',
      uploaded_at: '2026-10-10T00:00:00Z',
      checked_at: '2026-10-10T00:00:01Z',
      error_code: 'check-failed',
      error_message: "The file couldn't be checked; see the upload log",
      slots: [],
      name_problems: [],
    }
    const entry = {
      ...rejected,
      key: 'yaml-5',
      sha256: 'f'.repeat(64),
      size: 40,
      uploaded_by: 'admin',
      game_id: 1,
      checks: [
        { name: 'Stored', status: 'ok', message: '40 bytes', detail: null },
        { name: 'Worker check', status: 'failed', message: 'Worker job error', detail: null },
      ],
      job: {
        id: 'job-1',
        type: 'validate-yaml',
        status: 'error',
        submitted_at: '2026-10-10T00:00:00Z',
        finished_at: '2026-10-10T00:00:01Z',
        error_code: 'exception',
        error_message: "KeyError: 'x'",
        traceback: "Traceback (most recent call last):\nKeyError: 'x'",
        log_tail: null,
      },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/uploads') return Promise.resolve(Response.json([rejected]))
        if (url === '/api/logs/uploads') return Promise.resolve(Response.json([entry]))
        if (url === '/api/logs/uploads/yaml/5') return Promise.resolve(Response.json(entry))
        if (url === '/api/apworlds' || url === '/api/worlds')
          return Promise.resolve(Response.json([]))
        if (url === '/api/game') return Promise.resolve(Response.json(openGame))
        return fallback(input)
      }),
    )
    renderRoute('/admin')
    const [code] = await screen.findAllByRole('button', { name: 'check-failed' })
    await userEvent.click(code!)
    expect(await screen.findByText('Upload log: yaml-5')).toBeInTheDocument()
    expect(screen.getByText(/Traceback \(most recent call last\)/)).toBeInTheDocument()
  })
})

describe('generation', () => {
  it('generates from Locked and shows which upload a failure points at', async () => {
    const locked = { ...openGame, state: 'locked', actions: ['unlock', 'generate'] }
    const failed = {
      id: 1,
      status: 'failed',
      started_at: '2026-10-10T00:00:00Z',
      finished_at: '2026-10-10T00:00:05Z',
      seed_name: null,
      output_file: null,
      players: [],
      error_code: 'exception',
      error_message: 'ValueError: Encountered 1 error(s) in player files.',
      culprits: [{ upload_id: 2, filename: 'hornet.yaml', slots: ['Hornet'] }],
      traceback: 'Traceback ...',
      log_tail: null,
    }
    let generations: unknown[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/generate' && init?.method === 'POST') {
        generations = [failed]
        return Promise.resolve(Response.json({ ...failed, status: 'running' }, { status: 202 }))
      }
      if (url === '/api/game') return Promise.resolve(Response.json(locked))
      if (url === '/api/game/generations') return Promise.resolve(Response.json(generations))
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByText('Generation failed')).toBeInTheDocument()
    expect(screen.getByText(/Archipelago points at: hornet\.yaml \(Hornet\)/)).toBeInTheDocument()
  })
})

describe('server control', () => {
  it('starts the server, shows it running, and saves', async () => {
    const generatedGame = { ...openGame, state: 'generated', actions: ['discard-output', 'start'] }
    const runningGame = { ...openGame, state: 'running', actions: ['stop'] }
    let current = generatedGame
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/start' && init?.method === 'POST') {
        current = runningGame
        return Promise.resolve(Response.json(current))
      }
      if (url === '/api/game/patches')
        return Promise.resolve(
          Response.json([
            { file: 'AP_12345_P1_Knight.apz5', player: 1, slot: 'Knight', size: 2048 },
          ]),
        )
      if (url === '/api/server/save' && init?.method === 'POST')
        return Promise.resolve(Response.json({ reachable: true, state: 'running' }))
      if (url === '/api/server/command' && init?.method === 'POST')
        return Promise.resolve(Response.json({ reachable: true, state: 'running' }))
      if (url === '/api/game') return Promise.resolve(Response.json(current))
      if (url === '/api/server')
        return Promise.resolve(
          Response.json({
            reachable: true,
            state: 'running',
            archipelago_version: '0.6.8',
            multidata: 'AP_12345.zip',
            port: 38281,
            started_at: '2026-10-10T00:00:00Z',
            exit_code: null,
            log_tail: [],
          }),
        )
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Start server' }))
    expect(
      await screen.findByText('Server running on port 38281 (AP_12345.zip)'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop server' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'AP_12345_P1_Knight.apz5' })).toHaveAttribute(
      'href',
      '/api/game/patches/AP_12345_P1_Knight.apz5',
    )
    expect(screen.getByRole('link', { name: /Download all/ })).toHaveAttribute(
      'href',
      '/api/game/patches-all.zip',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith('/api/server/save', expect.anything()),
    )

    await userEvent.type(screen.getByRole('textbox', { name: 'Console' }), '/players')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByLabelText('Sent commands')).toHaveTextContent('/players')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/server/command',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ text: '/players' }) }),
    )
    const input = screen.getByRole('textbox', { name: 'Console' })
    expect(input).toHaveValue('')
    await userEvent.type(input, '{ArrowUp}')
    expect(input).toHaveValue('/players')
    await userEvent.type(input, '{ArrowDown}')
    expect(input).toHaveValue('')
  })
})

describe('resuming the server', () => {
  it('offers Start while the game is Running and the server stopped itself', async () => {
    const runningGame = { ...openGame, state: 'running', actions: ['stop'] }
    let serverState = 'idle'
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/start' && init?.method === 'POST') {
        serverState = 'starting'
        return Promise.resolve(Response.json(runningGame))
      }
      if (url === '/api/game') return Promise.resolve(Response.json(runningGame))
      if (url === '/api/server')
        return Promise.resolve(
          Response.json({ reachable: true, state: serverState, exit_code: 0, log_tail: [] }),
        )
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    expect(await screen.findByText(/Start resumes it from the save/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop server' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Start server' }))
    expect(await screen.findByText('Server starting')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start server' })).not.toBeInTheDocument()
  })
})

describe('console', () => {
  const runningGame = { ...openGame, state: 'running', actions: ['stop'] }
  const arg = (name: string, kind: string, rest = false) => ({
    name,
    kind,
    required: true,
    rest,
    default: null,
    choices: [],
  })
  const commands = [
    {
      name: 'send',
      help: 'Sends an item to the specified player',
      raw: false,
      args: [arg('player_name', 'player'), arg('item_name', 'item', true)],
    },
    { name: 'release', help: 'Release a player', raw: true, args: [arg('player_name', 'player')] },
  ]
  const names = {
    players: [
      { slot: 1, name: 'Knight', game: 'APQuest' },
      { slot: 2, name: 'Big Hornet', game: 'Hollow Knight' },
    ],
    games: {
      APQuest: { items: ['Hammer', 'Sword'], locations: [] },
      'Hollow Knight': { items: ['Mantis Claw', 'Monarch Wings'], locations: [] },
    },
  }

  it('builds a command from the game names, quoted the way AP reads it', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game') return Promise.resolve(Response.json(runningGame))
      if (url === '/api/server')
        return Promise.resolve(Response.json({ reachable: true, state: 'running', port: 38281 }))
      if (url === '/api/console/commands') return Promise.resolve(Response.json(commands))
      if (url === '/api/console/names') return Promise.resolve(Response.json(names))
      if (url === '/api/server/command' && init?.method === 'POST')
        return Promise.resolve(Response.json({ reachable: true, state: 'running' }))
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')
    const pickOption = async (label: string, option: string) => {
      await userEvent.click(await screen.findByRole('combobox', { name: label }))
      await userEvent.click(await screen.findByRole('option', { name: option }))
    }
    const line = await screen.findByRole('textbox', { name: 'Console' })

    await pickOption('Command', '/send')
    expect(line).toHaveValue('/send')
    expect(screen.getByRole('combobox', { name: 'Item' })).toBeDisabled()
    await pickOption('Player', 'Big Hornet')
    await userEvent.click(screen.getByRole('combobox', { name: 'Item' }))
    expect(screen.queryByRole('option', { name: 'Hammer' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('option', { name: 'Monarch Wings' }))
    expect(line).toHaveValue('/send "Big Hornet" "Monarch Wings"')

    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByLabelText('Sent commands')).toHaveTextContent(
      '/send "Big Hornet" "Monarch Wings"',
    )
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/server/command',
      expect.objectContaining({
        body: JSON.stringify({ text: '/send "Big Hornet" "Monarch Wings"' }),
      }),
    )

    await pickOption('Command', '/release')
    await pickOption('Player', 'Big Hornet')
    expect(line).toHaveValue('/release Big Hornet')
  })
})

describe('server feed', () => {
  class FakeWebSocket {
    static sockets: FakeWebSocket[] = []
    onopen: (() => void) | null = null
    onmessage: ((event: { data: string }) => void) | null = null
    onclose: (() => void) | null = null
    url: string
    constructor(url: string) {
      this.url = url
      FakeWebSocket.sockets.push(this)
    }
    close() {}
    send(message: unknown) {
      this.onmessage?.({ data: JSON.stringify(message) })
    }
  }

  it('shows the scrollback, then each new line, and reconnects', async () => {
    FakeWebSocket.sockets = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    stubHealth(okHealth)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    renderRoute('/admin')
    const feed = await screen.findByLabelText('Server feed')
    expect(feed).toHaveTextContent('No server output yet.')
    const [socket] = FakeWebSocket.sockets
    expect(socket.url).toMatch(/^ws:\/\/.+\/api\/server\/feed$/)

    act(() => {
      socket.onopen?.()
      socket.send({ reset: true, lines: ['Hosting game at 0.0.0.0:38281'] })
      socket.send({ reset: false, lines: ['Notice (all): [Server]: hello'] })
    })
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(feed).toHaveTextContent('Hosting game at 0.0.0.0:38281 Notice (all): [Server]: hello')

    act(() => socket.send({ reset: true, lines: ['a new game'] }))
    expect(feed).toHaveTextContent(/^a new game$/)

    act(() => socket.onclose?.())
    expect(screen.getByText('Reconnecting')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(2000))
    expect(FakeWebSocket.sockets).toHaveLength(2)
    vi.useRealTimers()
  })
})

describe('settings page', () => {
  const field = (key: string, label: string, extra: Record<string, unknown>) => ({
    key,
    label,
    help: `${label} help`,
    choices: [],
    min: null,
    max: null,
    warning: null,
    ...extra,
  })
  const page = {
    values: {
      hint_cost: 10,
      spoiler: 3,
      plando_options: ['bosses'],
      log_network: false,
    },
    fields: [
      field('hint_cost', 'Hint cost', {
        group: 'server',
        kind: 'number',
        applies: 'live',
        min: 0,
        max: 100,
      }),
      field('spoiler', 'Spoiler log', {
        group: 'generation',
        kind: 'choice',
        applies: 'generation',
        choices: [
          { value: 0, label: 'None' },
          { value: 3, label: 'Full' },
        ],
      }),
      field('plando_options', 'Plando', {
        group: 'generation',
        kind: 'multi',
        applies: 'generation',
        choices: [
          { value: 'bosses', label: 'Bosses' },
          { value: 'items', label: 'Items' },
        ],
      }),
      field('log_network', 'Log network traffic', {
        group: 'advanced',
        kind: 'bool',
        applies: 'start',
        warning: 'Very large logs.',
      }),
    ],
  }

  it('saves the settings and says which applied at once', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/settings' && init?.method === 'PUT') {
        const values = JSON.parse(String(init.body)) as Record<string, unknown>
        return Promise.resolve(Response.json({ values, applied_now: ['hint_cost'] }))
      }
      if (url === '/api/settings') return Promise.resolve(Response.json(page))
      return Promise.resolve(Response.json([]))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/settings')

    const hintCost = await screen.findByRole('textbox', { name: /Hint cost/ })
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0)
    await userEvent.clear(hintCost)
    await userEvent.type(hintCost, '25')
    await userEvent.click(screen.getByRole('combobox', { name: /Spoiler log/ }))
    await userEvent.click(await screen.findByRole('option', { name: 'None' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Items' }))
    expect(screen.queryByRole('switch', { name: /Log network traffic/ })).toBeNull() // collapsed
    await userEvent.click(screen.getByRole('button', { name: 'Advanced' }))
    await userEvent.click(screen.getByRole('switch', { name: /Log network traffic/ }))

    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(
      await screen.findByText(/Applied to the running server now: Hint cost\./),
    ).toBeInTheDocument()
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      hint_cost: 25,
      spoiler: 0,
      plando_options: ['bosses', 'items'],
      log_network: true,
    })
  })

  it('shows a validation error from the server', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input) === '/api/settings' && init?.method === 'PUT')
          return Promise.resolve(
            Response.json(
              {
                detail: [
                  { loc: ['body', 'hint_cost'], msg: 'Input should be less than or equal to 100' },
                ],
              },
              { status: 422 },
            ),
          )
        if (String(input) === '/api/settings') return Promise.resolve(Response.json(page))
        return Promise.resolve(Response.json([]))
      }),
    )
    renderRoute('/settings')
    await userEvent.click(await screen.findByRole('button', { name: 'Save settings' }))
    expect(
      await screen.findByText('hint_cost: Input should be less than or equal to 100'),
    ).toBeInTheDocument()
  })
})

describe('spoiler log', () => {
  it('asks first, then shows the log with a line filter', async () => {
    const generatedGame = { ...openGame, state: 'generated', actions: ['discard-output', 'start'] }
    const spoiler = 'Seed: 12345\n\nKnight Hookshot: Hornet Shop\nHornet Needle: Knight Cave\n'
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/game') return Promise.resolve(Response.json(generatedGame))
      if (url === '/api/game/spoiler')
        return Promise.resolve(Response.json({ file: 'AP_12345_Spoiler.txt', size: 80 }))
      if (url === '/api/game/spoiler.txt') return Promise.resolve(new Response(spoiler))
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Spoiler log' }))
    const prompt = await screen.findByRole('dialog', { name: 'Are you sure?' })
    expect(within(prompt).getByRole('link', { name: 'Yes, download it' })).toHaveAttribute(
      'href',
      '/api/game/spoiler.txt',
    )
    expect(fetchMock).not.toHaveBeenCalledWith('/api/game/spoiler.txt', expect.anything())

    await userEvent.click(within(prompt).getByRole('button', { name: 'Yes, show it' }))
    const viewer = await screen.findByRole('dialog', { name: 'AP_12345_Spoiler.txt' })
    expect(await within(viewer).findByText(/Knight Hookshot: Hornet Shop/)).toBeInTheDocument()

    await userEvent.type(within(viewer).getByRole('textbox', { name: 'Filter lines' }), 'needle')
    expect(within(viewer).getByText('Hornet Needle: Knight Cave')).toBeInTheDocument()
    expect(within(viewer).queryByText(/Hookshot/)).not.toBeInTheDocument()
  })

  it('offers a very large log as a download only', async () => {
    const generatedGame = { ...openGame, state: 'generated', actions: ['discard-output', 'start'] }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/game') return Promise.resolve(Response.json(generatedGame))
        if (url === '/api/game/spoiler')
          return Promise.resolve(Response.json({ file: 'AP_1_Spoiler.txt', size: 12 * 1024 ** 2 }))
        if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
          return Promise.resolve(Response.json([]))
        return fallback(input)
      }),
    )
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Spoiler log' }))
    const prompt = await screen.findByRole('dialog', { name: 'Are you sure?' })
    expect(within(prompt).getByText(/12 MB, too large to show here/)).toBeInTheDocument()
    expect(within(prompt).getByRole('link', { name: 'Yes, download it' })).toBeInTheDocument()
    expect(within(prompt).queryByRole('button', { name: 'Yes, show it' })).not.toBeInTheDocument()
  })
})

describe('health page', () => {
  it('shows each service, ports, disk use, host names and their warnings', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        if (String(input) === '/api/health/details')
          return Promise.resolve(
            Response.json({
              version: '1.2.3',
              archipelago_version: '0.6.8',
              isolation: 'none',
              isolation_warning: "Services aren't isolated",
              host_names: ['any IP address', 'localhost', '*.local', 'apsui.home.example'],
              host_names_warning: 'The web UI answers to any host name',
              services: [
                { name: 'web', up: true, detail: 'v1.2.3, database ok' },
                { name: 'worker', up: true, detail: 'Heartbeat 2s ago; 0 queued, 0 running' },
                { name: 'server', up: false, detail: 'Not answering' },
              ],
              ports: [
                { name: 'Web UI', port: 8000 },
                { name: 'Game (Archipelago clients)', port: 38281 },
              ],
              disks: [
                {
                  name: 'Data',
                  path: '/data',
                  total: 10 * 1024 ** 3,
                  used: 4 * 1024 ** 3,
                  free: 6 * 1024 ** 3,
                },
              ],
            }),
          )
        return fallback(input)
      }),
    )
    renderRoute('/health')
    expect(await screen.findByText(/Heartbeat 2s ago/)).toBeInTheDocument()
    expect(screen.getByText('Down')).toBeInTheDocument()
    expect(screen.getByText('Reduced isolation')).toBeInTheDocument()
    expect(screen.getByText('Any host name accepted')).toBeInTheDocument()
    expect(
      screen.getByText('any IP address, localhost, *.local, apsui.home.example'),
    ).toBeInTheDocument()
    expect(screen.getByText('38281')).toBeInTheDocument()
    expect(screen.getByText('6.0 GB free of 10.0 GB')).toBeInTheDocument()
  })
})

describe('archives', () => {
  const generatedGame = { ...openGame, id: 3, state: 'generated', actions: ['start'] }
  const archived = {
    id: 2,
    created_at: '2026-10-01T00:00:00Z',
    archived_at: '2026-10-02T00:00:00Z',
    archived_from: 'generated',
    size: 2048,
    seed_name: '12345',
    slots: ['Knight', 'Hornet'],
    worlds: ['APQuest · official · AP 0.6.8'],
  }

  it('asks before ARCHIVE, then archives the current game', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/archive' && init?.method === 'POST')
        return Promise.resolve(Response.json({ ...openGame, id: 4 }))
      if (url === '/api/game')
        return Promise.resolve(Response.json({ ...generatedGame, archivable: true }))
      if (url.startsWith('/api/') && url !== '/api/health' && url !== '/api/archives')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'ARCHIVE' }))
    const dialog = await screen.findByRole('dialog', { name: 'Archive this game?' })
    expect(fetchMock).not.toHaveBeenCalledWith('/api/game/archive', expect.anything())
    await userEvent.click(within(dialog).getByRole('button', { name: 'ARCHIVE' }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/game/archive',
        expect.objectContaining({ method: 'POST' }),
      ),
    )
  })

  it('asks what to do with a current game in the way of a restore', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/archives/2/restore') {
        const body = JSON.parse(String(init?.body)) as { current: string | null }
        if (body.current === null)
          return Promise.resolve(
            Response.json(
              {
                detail: {
                  code: 'current-game',
                  message: 'Archive or delete the current game first',
                  current: { id: 3, state: 'locked', slots: 2 },
                },
              },
              { status: 409 },
            ),
          )
        return Promise.resolve(Response.json({ ...generatedGame, id: 2 }))
      }
      if (url === '/api/archives')
        return Promise.resolve(Response.json({ ...noArchives, archives: [archived] }))
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
      if (url.startsWith('/api/') && url !== '/api/health')
        return Promise.resolve(Response.json([]))
      return fallback(input)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    expect(await screen.findByText('2: Knight, Hornet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
    const dialog = await screen.findByRole('dialog', { name: 'Restore game #2?' })
    expect(within(dialog).getByText(/The current game #3 is/)).toHaveTextContent('locked')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Archive it, then restore' }))
    await waitFor(() => {
      const bodies = fetchMock.mock.calls
        .filter(([u]) => String(u) === '/api/archives/2/restore')
        .map(([, init]) => JSON.parse(String(init?.body)) as unknown)
      expect(bodies).toEqual([{ current: null }, { current: 'archive' }])
    })
  })
})

describe('player page', () => {
  const view = {
    slot: { name: 'Knight', game: 'APQuest', team: 0, slot: 1 },
    live: true,
    goal: false,
    hint_points: 5,
    checked: 1,
    locations: 3,
    received: [{ item: 'Sword', player: 'Hornet', location: 'Cave', flags: 1 }],
    unreceived: null,
    unreceived_rule: 'goal',
    unchecked: ['Chest B', 'Chest C'],
    hints: [
      {
        item: 'Key',
        receiving: 'Knight',
        finding: 'Hornet',
        location: 'Cave',
        entrance: '',
        found: false,
        status: 'priority',
        flags: 1,
      },
    ],
  }

  it('logs in with the slot name and room password, then shows the slot', async () => {
    let loggedIn = false
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/slot/login') {
        const body = JSON.parse(String(init?.body)) as { name: string; password: string }
        if (body.password !== 'room pw')
          return Promise.resolve(
            Response.json({ detail: { code: 'login-refused', message: 'wrong' } }, { status: 401 }),
          )
        loggedIn = true
        return Promise.resolve(Response.json({ name: body.name }))
      }
      if (url === '/api/slot')
        return Promise.resolve(
          loggedIn ? Response.json(view) : Response.json(notLoggedIn, { status: 401 }),
        )
      return okHealth()
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/player')

    await userEvent.type(await screen.findByLabelText(/Slot name/), 'Knight')
    await userEvent.type(screen.getByLabelText('Room password'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('That slot name or room password is wrong.')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('Room password'))
    await userEvent.type(screen.getByLabelText('Room password'), 'room pw')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('heading', { name: 'Knight' })).toBeInTheDocument()
    expect(screen.getByText('1 of 3 locations checked · 5 hint points')).toBeInTheDocument()
    expect(screen.getByText('Sword')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Still out there/ }))
    expect(await screen.findByText(/Shown once you reach your goal/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Hints/ }))
    expect(await screen.findByText('priority')).toBeInTheDocument()
  })

  it('tells the player to contact the admin while the server is stopped', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/slot/login')
        return Promise.resolve(
          Response.json(
            { detail: { code: 'server-stopped', message: 'The server is stopped' } },
            { status: 503 },
          ),
        )
      if (url === '/api/slot') return Promise.resolve(Response.json(notLoggedIn, { status: 401 }))
      return okHealth()
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/player')

    await userEvent.type(await screen.findByLabelText(/Slot name/), 'Knight')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(
      await screen.findByRole('heading', { name: 'The server is stopped' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Please reach out to your admin/)).toBeInTheDocument()
  })
})
