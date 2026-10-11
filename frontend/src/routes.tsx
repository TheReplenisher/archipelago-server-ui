import { Navigate, type RouteObject } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { AdminPage } from './pages/AdminPage'
import { HealthPage } from './pages/HealthPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { PlayerPage } from './pages/PlayerPage'
import { SettingsPage } from './pages/SettingsPage'

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/player" replace /> },
      { path: 'player/*', element: <PlayerPage /> },
      { path: 'admin/*', element: <AdminPage /> },
      { path: 'settings/*', element: <SettingsPage /> },
      { path: 'health/*', element: <HealthPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
