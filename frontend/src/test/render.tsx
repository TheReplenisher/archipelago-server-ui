import { MantineProvider } from '@mantine/core'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { routes } from '../routes'
import { theme } from '../theme'

export function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  return {
    router,
    ...render(
      <MantineProvider theme={theme}>
        <RouterProvider router={router} />
      </MantineProvider>,
    ),
  }
}
