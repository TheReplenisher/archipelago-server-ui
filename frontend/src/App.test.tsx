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
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/game/lock' && init?.method === 'POST')
        return Promise.resolve(Response.json({ ...openGame, state: 'locked', actions: ['unlock'] }))
      if (url === '/api/game') return Promise.resolve(Response.json(openGame))
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
        return okHealth()
      }),
    )
    renderRoute('/admin')
    expect(await screen.findByText('Slot name is longer than 16 characters')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  })
})
