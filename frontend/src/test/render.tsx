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
      // env="test": no transitions or portals, as Mantine's testing guide suggests
      <MantineProvider theme={theme} env="test">
        <RouterProvider router={router} />
      </MantineProvider>,
    ),
  }
}
