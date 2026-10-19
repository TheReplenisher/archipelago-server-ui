import {
  Alert,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  PasswordInput,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { IconLock } from '@tabler/icons-react'
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  ADMIN_LOGGED_OUT,
  adminLogin,
  adminLogout,
  adminSetup,
  changeAdminPassword,
  getAdminSession,
  type AdminSession,
} from '../api/client'

const MIN_PASSWORD = 8

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** First run: whoever opens the admin pages first sets the password (#32). */
function SetupForm({ onDone }: { onDone: (s: AdminSession) => void }) {
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== again) return setError("The passwords don't match")
    setBusy(true)
    setError(null)
    try {
      onDone(await adminSetup(password))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card withBorder maw={480}>
      <form onSubmit={submit}>
        <Stack>
          <Title order={2}>Set the admin password</Title>
          <Text size="sm">
            No admin password is set yet. Whoever sets it now becomes this server's admin.
          </Text>
          <Alert color="yellow" title="Not you who set it?">
            If someone else gets here first, take it back from a shell on the host:{' '}
            <code>apsui-admin set-password</code> (see the README).
          </Alert>
          <PasswordInput
            label="New password"
            description={`At least ${MIN_PASSWORD} characters`}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="new-password"
            required
          />
          <PasswordInput
            label="Again"
            value={again}
            onChange={(e) => setAgain(e.currentTarget.value)}
            autoComplete="new-password"
            required
          />
          {error && <Alert color="red">{error}</Alert>}
          <Group>
            <Button type="submit" loading={busy} disabled={password.length < MIN_PASSWORD}>
              Set password
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  )
}

function LoginForm({ onDone }: { onDone: (s: AdminSession) => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onDone(await adminLogin(password))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card withBorder maw={420}>
      <form onSubmit={submit}>
        <Stack>
          <Title order={2}>Admin login</Title>
          <PasswordInput
            label="Admin password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="current-password"
            data-autofocus
            required
          />
          {error && <Alert color="red">{error}</Alert>}
          <Group>
            <Button type="submit" loading={busy} leftSection={<IconLock size={16} />}>
              Log in
            </Button>
          </Group>
          <Text size="xs" c="dimmed">
            Forgotten it? Set a new one from a shell on the host: apsui-admin set-password.
          </Text>
        </Stack>
      </form>
    </Card>
  )
}

function ChangePassword({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const close = () => {
    setCurrent('')
    setNext('')
    setError(null)
    setDone(false)
    onClose()
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await changeAdminPassword(current, next)
      setDone(true)
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal opened={opened} onClose={close} title="Change the admin password">
      {done ? (
        <Stack>
          <Alert color="green">
            Changed. Every other browser logged in as the admin is logged out.
          </Alert>
          <Group justify="flex-end">
            <Button onClick={close}>Close</Button>
          </Group>
        </Stack>
      ) : (
        <form onSubmit={submit}>
          <Stack>
            <PasswordInput
              label="Current password"
              value={current}
              onChange={(e) => setCurrent(e.currentTarget.value)}
              autoComplete="current-password"
              required
            />
            <PasswordInput
              label="New password"
              description={`At least ${MIN_PASSWORD} characters`}
              value={next}
              onChange={(e) => setNext(e.currentTarget.value)}
              autoComplete="new-password"
              required
            />
            {error && <Alert color="red">{error}</Alert>}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                Cancel
              </Button>
              <Button type="submit" loading={busy} disabled={next.length < MIN_PASSWORD}>
                Change
              </Button>
            </Group>
          </Stack>
        </form>
      )}
    </Modal>
  )
}

/** The admin pages (Admin, Settings, Health), behind the admin login (#32). Shows the
 * first-run setup or the login until the admin is logged in, and again if a request
 * finds the session gone. */
export function AdminGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AdminSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [changing, setChanging] = useState(false)

  const refresh = useCallback((signal?: AbortSignal) => {
    getAdminSession(signal)
      .then(setSession)
      .catch((e: unknown) => {
        if (!signal?.aborted) setError(message(e))
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    const loggedOut = () => refresh()
    window.addEventListener(ADMIN_LOGGED_OUT, loggedOut)
    return () => {
      controller.abort()
      window.removeEventListener(ADMIN_LOGGED_OUT, loggedOut)
    }
  }, [refresh])

  const logout = async () => {
    try {
      setSession(await adminLogout())
    } catch (e) {
      setError(message(e))
    }
  }

  if (error && !session) return <Alert color="red">{error}</Alert>
  if (!session) return <Loader size="sm" />
  if (!session.password_set) return <SetupForm onDone={setSession} />
  if (!session.logged_in) return <LoginForm onDone={setSession} />
  return (
    <Stack>
      <Group justify="flex-end" gap="xs">
        <Text size="sm" c="dimmed">
          Logged in as {session.username}
        </Text>
        <Button size="compact-sm" variant="subtle" onClick={() => setChanging(true)}>
          Change password
        </Button>
        <Button size="compact-sm" variant="subtle" onClick={logout}>
          Log out
        </Button>
      </Group>
      <ChangePassword opened={changing} onClose={() => setChanging(false)} />
      {children}
    </Stack>
  )
}
