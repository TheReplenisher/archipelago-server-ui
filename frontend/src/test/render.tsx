import { MantineProvider } from '@mantine/core'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { routes } from '../routes'
import { theme } from '../theme'

const loggedIn = { password_set: true, logged_in: true, username: 'admin' }

/** Renders a route. The admin is logged in (GET /api/admin/session answers so, whatever
 * fetch is stubbed with), unless `realAdminSession` leaves that to the test's own stub. */
export function renderRoute(path: string, { realAdminSession = false } = {}) {
  if (!realAdminSession) {
    const inner = globalThis.fetch
    vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/admin/session'
        ? Promise.resolve(Response.json(loggedIn))
        : inner(input, init),
    )
  }
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return {
    router,
    ...render(
      // env="test": no transitions or portals, as Mantine's testing guide suggests
      <MantineProvider theme={theme} env="test">
        <RouterProvider router={router} />
      </MantineProvider>,
    ),
  }
}
