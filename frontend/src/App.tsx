import '@mantine/core/styles.css'

import { MantineProvider } from '@mantine/core'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { routes } from './routes'
import { theme } from './theme'

const router = createBrowserRouter(routes)

export function App() {
  return (
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <RouterProvider router={router} />
    </MantineProvider>
  )
}
