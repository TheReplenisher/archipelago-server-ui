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
  const fetchMock = vi.fn((input: RequestInfo | URL) =>
    String(input) === '/api/game' ? Promise.resolve(Response.json(openGame)) : health(),
  )
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
        return okHealth()
      }),
    )
    renderRoute('/admin')
    await userEvent.click(await screen.findByRole('button', { name: 'Lock uploads' }))
    expect(await screen.findByText("Can't lock a game that is locked")).toBeInTheDocument()
  })
})
