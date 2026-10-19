import { Navigate, type RouteObject } from 'react-router'
import { AdminGate } from './components/AdminGate'
import { AppLayout } from './components/AppLayout'
import { AdminPage } from './pages/AdminPage'
import { AuditPage } from './pages/AuditPage'
import { BackupsPage } from './pages/BackupsPage'
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
      // The admin's pages: behind the admin login (#32).
      {
        path: 'admin/*',
        element: (
          <AdminGate>
            <AdminPage />
          </AdminGate>
        ),
      },
      {
        path: 'settings/*',
        element: (
          <AdminGate>
            <SettingsPage />
          </AdminGate>
        ),
      },
      {
        path: 'health/*',
        element: (
          <AdminGate>
            <HealthPage />
          </AdminGate>
        ),
      },
      {
        path: 'audit/*',
        element: (
          <AdminGate>
            <AuditPage />
          </AdminGate>
        ),
      },
      {
        path: 'backups/*',
        element: (
          <AdminGate>
            <BackupsPage />
          </AdminGate>
        ),
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
