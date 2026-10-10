import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { renderRoute } from './test/render'

const openGame = {
  id: 1,
  state: 'open',
  created_at: '2026-10-09T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
  actions: ['lock'],
}

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
    return health()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const okHealth = () =>
  Promise.resolve(Response.json({ status: 'ok', version: '1.2.3', database: 'ok' }))

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
      return okHealth()
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
        return okHealth()
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
      return okHealth()
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
        return okHealth()
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
      return okHealth()
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
      return okHealth()
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
      return okHealth()
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
        return okHealth()
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
      if (url.startsWith('/api/') && url !== '/api/health')
        return Promise.resolve(Response.json([]))
      return okHealth()
    })
    vi.stubGlobal('fetch', fetchMock)
    renderRoute('/admin')

    await userEvent.click(await screen.findByRole('button', { name: 'Generate' }))
    expect(await screen.findByText('Generation failed')).toBeInTheDocument()
    expect(screen.getByText(/Archipelago points at: hornet\.yaml \(Hornet\)/)).toBeInTheDocument()
  })
})
